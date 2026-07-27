"""
train_v3.py — BƯỚC 6 pipeline v3: QLoRA Qwen3-8B trên train_v3.jsonl.

KHÁC GÌ train_v2.py (và vì sao)
--------------------------------
1. KHÔNG dùng trl. train_v2 gãy trên Colab mới vì API trl trôi
   (`SFTTrainer(tokenizer=...)` đã bị bỏ). Bản này chỉ dùng transformers
   Trainer + tokenize tay — ít tầng abstraction, ít chỗ gãy.
2. Loss CHỈ tính trên phần trả lời (label = -100 cho prompt). train_v2 tính
   loss trên cả câu hỏi -> model học cả cách "tự viết câu hỏi của user",
   một nguồn của bệnh tự hỏi tự đáp.
3. Có eval split (eval_v3.jsonl) + load_best_model_at_end — train_v2 train mù
   3 epochs không có gì để chọn checkpoint.
4. bf16/fp16 TỰ NHẬN theo GPU — train_v2 fix cứng bf16, sập trên T4.
5. Prompt dựng bằng apply_chat_template(enable_thinking=False) — KHỚP TỪNG
   TOKEN với cách engine.py dựng lúc serve (P4). Dataset v3 không có <think>.
6. Mẫu vượt MAX_SEQ_LEN bị LOẠI chứ không cắt — cắt giữa JSON là dạy model
   xuất JSON cụt.

CHẠY TRONG COLAB (GPU L4 trở lên; T4 chạy được, chậm hơn, tự chuyển fp16):
  !pip install -r offline_training/requirements_training.txt
  !python offline_training/build_dataset_v3.py       # nếu chưa có train_v3.jsonl
  exec(open('/content/ANSER_AI/offline_training/train_v3.py').read())

Biến env tuỳ chọn: BASE_MODEL_ID, MAX_SEQ_LEN, LORA_R, LR, EPOCHS, OUT_DIR, LORA_DIR
"""

import json
import os
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()
DATA_DIR = ROOT / "offline_training" / "generated"

MODEL_ID = os.getenv("BASE_MODEL_ID", "Qwen/Qwen3-8B")
MAX_LEN = int(os.getenv("MAX_SEQ_LEN", "8192"))
LORA_R = int(os.getenv("LORA_R", "32"))
LR = float(os.getenv("LR", "1e-4"))
EPOCHS = float(os.getenv("EPOCHS", "2"))
OUT_DIR = os.getenv("OUT_DIR", "/content/checkpoints/anser-v3")
LORA_DIR = os.getenv("LORA_DIR", "/content/checkpoints/anser-v3-lora")

# ── 1. Môi trường ───────────────────────────────────────────────────────
assert torch.cuda.is_available(), "Không thấy GPU"
bf16_ok = torch.cuda.is_bf16_supported()
compute_dtype = torch.bfloat16 if bf16_ok else torch.float16
print(f"GPU  : {torch.cuda.get_device_name(0)}")
print(f"VRAM : {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
print(f"dtype: {'bf16' if bf16_ok else 'fp16 (GPU không hỗ trợ bf16)'}\n")

train_file = DATA_DIR / "train_v3.jsonl"
eval_file = DATA_DIR / "eval_v3.jsonl"
assert train_file.exists(), f"Thiếu {train_file} — chạy build_dataset_v3.py trước"
assert eval_file.exists(), f"Thiếu {eval_file} — chạy build_dataset_v3.py trước"

# ── 2. Model + tokenizer ────────────────────────────────────────────────
print(f"Tải {MODEL_ID}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    ),
    device_map="auto",
)
model.config.use_cache = False          # bắt buộc khi gradient checkpointing
print(f"✓ Model loaded | VRAM: {torch.cuda.memory_allocated() / 1e9:.1f} GB\n")

model = get_peft_model(model, LoraConfig(
    r=LORA_R,
    lora_alpha=LORA_R * 2,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
))
model.enable_input_require_grads()
model.print_trainable_parameters()

# ── 3. Tokenize: prompt (masked) + completion ───────────────────────────
IM_END = "<|im_end|>"


def encode(example):
    """
    prompt  = chat template của [system, user] + generation prompt
              (enable_thinking=False -> KHỚP với engine.generate_chat lúc serve)
    labels  = -100 cho toàn bộ prompt, chỉ học phần trả lời + <|im_end|>
    """
    msgs = example["messages"]
    prompt = tokenizer.apply_chat_template(
        msgs[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    completion_ids = tokenizer(
        msgs[-1]["content"] + IM_END, add_special_tokens=False
    )["input_ids"]
    input_ids = prompt_ids + completion_ids
    labels = [-100] * len(prompt_ids) + completion_ids
    return {"input_ids": input_ids, "labels": labels, "n_tokens": len(input_ids)}


def load_split(path: Path, name: str) -> Dataset:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    ds = Dataset.from_list(rows).map(encode, remove_columns=["messages"])
    n_before = len(ds)
    ds = ds.filter(lambda ex: ex["n_tokens"] <= MAX_LEN)
    dropped = n_before - len(ds)
    lengths = sorted(ds["n_tokens"])
    print(f"{name}: {len(ds)} mẫu"
          + (f" (LOẠI {dropped} mẫu > {MAX_LEN} token — không cắt JSON giữa chừng)"
             if dropped else "")
          + f" | token p50={lengths[len(lengths) // 2]:,}"
            f" p95={lengths[int(len(lengths) * 0.95)]:,} max={lengths[-1]:,}")
    return ds.remove_columns(["n_tokens"])


train_ds = load_split(train_file, "train")
eval_ds = load_split(eval_file, "eval")
print()


def collate(batch):
    max_len = max(len(ex["input_ids"]) for ex in batch)
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    input_ids, labels, attention = [], [], []
    for ex in batch:
        pad = max_len - len(ex["input_ids"])
        input_ids.append(ex["input_ids"] + [pad_id] * pad)
        labels.append(ex["labels"] + [-100] * pad)
        attention.append([1] * len(ex["input_ids"]) + [0] * pad)
    return {
        "input_ids": torch.tensor(input_ids),
        "labels": torch.tensor(labels),
        "attention_mask": torch.tensor(attention),
    }


# ── 4. Trainer ──────────────────────────────────────────────────────────
trainer = Trainer(
    model=model,
    train_dataset=train_ds,
    eval_dataset=eval_ds,
    data_collator=collate,
    args=TrainingArguments(
        output_dir=OUT_DIR,
        per_device_train_batch_size=1,      # seq 8k — bù bằng grad accum
        gradient_accumulation_steps=16,     # lô hiệu dụng 16
        num_train_epochs=EPOCHS,
        learning_rate=LR,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        bf16=bf16_ok,
        fp16=not bf16_ok,
        gradient_checkpointing=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=2,
        logging_steps=10,
        optim="paged_adamw_8bit",
        report_to="none",
        seed=42,
    ),
)

steps = int(len(train_ds) * EPOCHS // 16)
print(f"Số bước dự kiến: ~{steps}\n🚀 Bắt đầu huấn luyện...\n")
trainer.train()
print(f"\nBest eval_loss: {trainer.state.best_metric}")

# ── 5. Lưu LoRA (checkpoint tốt nhất đã được load lại) ──────────────────
model.save_pretrained(LORA_DIR)
tokenizer.save_pretrained(LORA_DIR)
size_mb = sum(f.stat().st_size for f in Path(LORA_DIR).rglob("*") if f.is_file()) / 1e6
print(f"\n{'=' * 54}")
print(f"  LoRA lưu tại : {LORA_DIR} ({size_mb:.0f} MB)")
print("  Bước tiếp    : python offline_training/merge_and_quantize.py")
print(f"{'=' * 54}")
