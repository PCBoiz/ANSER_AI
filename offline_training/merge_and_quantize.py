"""
merge_and_quantize.py — BƯỚC 7 pipeline v3: gộp LoRA + lượng tử hoá AWQ.

Bước này TỪNG KHÔNG TỒN TẠI trong repo — train_v2.py kết thúc bằng dòng ghi
chú "gộp LoRA + AWQ" và file anser-retail-v2-awq (thứ config.py trỏ vào) được
tạo thủ công không ai tái tạo được. Bản này đóng lại lỗ hổng đó.

HAI GIAI ĐOẠN (Colab nên chạy tách — quantize ngốn RAM, restart runtime giữa
hai giai đoạn nếu OOM):
  python offline_training/merge_and_quantize.py --stage merge
  python offline_training/merge_and_quantize.py --stage quant

Calibration data cho AWQ lấy từ CHÍNH train_v3.jsonl (in-domain — chuẩn hơn
wikitext mặc định cho tiếng Việt + JSON n8n).

Env: BASE_MODEL_ID, LORA_DIR, MERGED_DIR, AWQ_DIR
Sau khi xong:  export TEXT_MODEL_ID=<AWQ_DIR>  là vLLM nạp được ngay
(config.py đọc env này, vllm_config đã đặt quantization="awq").
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "offline_training" / "generated" / "train_v3.jsonl"

MODEL_ID = os.getenv("BASE_MODEL_ID", "Qwen/Qwen3-8B")
LORA_DIR = os.getenv("LORA_DIR", "/content/checkpoints/anser-v3-lora")
MERGED_DIR = os.getenv("MERGED_DIR", "/content/checkpoints/anser-v3-merged")
AWQ_DIR = os.getenv("AWQ_DIR", "/content/drive/MyDrive/ANSER_data/anser-v3-awq")

N_CALIB = 128           # số mẫu calibration
CALIB_MAX_CHARS = 6_000


def stage_merge() -> None:
    """LoRA (train trên nền 4-bit) phải gộp vào weights ĐỦ PRECISION."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    print(f"Tải {MODEL_ID} ({dtype}) để gộp LoRA...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, torch_dtype=dtype, device_map="auto", low_cpu_mem_usage=True
    )
    model = PeftModel.from_pretrained(model, LORA_DIR)
    model = model.merge_and_unload()
    model.save_pretrained(MERGED_DIR, safe_serialization=True)
    AutoTokenizer.from_pretrained(LORA_DIR).save_pretrained(MERGED_DIR)
    print(f"✓ Model đã gộp: {MERGED_DIR}")
    print("  Colab: nên Runtime > Restart trước khi chạy --stage quant (giải phóng VRAM)")


def _calibration_texts() -> list[str]:
    """Mẫu in-domain từ train_v3 — render đúng chat template như lúc serve."""
    from transformers import AutoTokenizer

    assert DATA_FILE.exists(), f"Thiếu {DATA_FILE} — cần cho calibration AWQ"
    tokenizer = AutoTokenizer.from_pretrained(MERGED_DIR)
    rows = [json.loads(line) for line in DATA_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    random.Random(42).shuffle(rows)
    texts = []
    for row in rows[:N_CALIB]:
        text = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, enable_thinking=False
        )
        texts.append(text[:CALIB_MAX_CHARS])
    return texts


def stage_quant() -> None:
    try:
        from awq import AutoAWQForCausalLM
    except ImportError as exc:
        raise SystemExit(
            f"Thiếu autoawq ({exc}). Cài: pip install autoawq==0.2.9\n"
            "Nếu xung đột version transformers: cài autoawq ở bước RIÊNG sau khi "
            "train xong, hoặc dùng đường llm-compressor (xem README)."
        )
    from transformers import AutoTokenizer

    print(f"Tải model đã gộp từ {MERGED_DIR}...")
    model = AutoAWQForCausalLM.from_pretrained(
        MERGED_DIR, safetensors=True, low_cpu_mem_usage=True
    )
    tokenizer = AutoTokenizer.from_pretrained(MERGED_DIR)

    quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": 4, "version": "GEMM"}
    print(f"Quantize AWQ 4-bit với {N_CALIB} mẫu calibration in-domain...")
    model.quantize(tokenizer, quant_config=quant_config, calib_data=_calibration_texts())

    model.save_quantized(AWQ_DIR)
    tokenizer.save_pretrained(AWQ_DIR)
    size_gb = sum(f.stat().st_size for f in Path(AWQ_DIR).rglob("*") if f.is_file()) / 1e9
    print(f"\n{'=' * 54}")
    print(f"  AWQ lưu tại : {AWQ_DIR} ({size_gb:.1f} GB)")
    print(f"  Dùng ngay   : export TEXT_MODEL_ID={AWQ_DIR}")
    print(f"  Bước tiếp   : python offline_training/benchmark_v3.py --model {AWQ_DIR}")
    print(f"{'=' * 54}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["merge", "quant", "all"], default="all")
    args = parser.parse_args()
    if args.stage in ("merge", "all"):
        stage_merge()
    if args.stage in ("quant", "all"):
        stage_quant()


if __name__ == "__main__":
    main()
