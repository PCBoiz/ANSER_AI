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
# ANSER_GENERATED_DIR cho phép trỏ thẳng vào Drive — xem dgen_common.GENERATED_DIR
DATA_FILE = Path(
    os.getenv("ANSER_GENERATED_DIR", "").strip()
    or (ROOT / "offline_training" / "generated")
) / "train_v3.jsonl"

MODEL_ID = os.getenv("BASE_MODEL_ID", "Qwen/Qwen3-8B")
LORA_DIR = os.getenv("LORA_DIR", "/content/checkpoints/anser-v3-lora")
MERGED_DIR = os.getenv("MERGED_DIR", "/content/checkpoints/anser-v3-merged")
AWQ_DIR = os.getenv("AWQ_DIR", "/content/drive/MyDrive/ANSER_data/anser-v3-awq")

N_CALIB = 128           # số mẫu calibration
CALIB_MAX_CHARS = 6_000


def _require_dir(path: str, marker: str, what: str, hints: list[str]) -> None:
    """
    Chặn TRƯỚC khi nạp model. Thiếu file thì báo ngay, đừng nạp 16GB weights rồi
    mới phát hiện — mỗi lần sai đường dẫn tốn 4-5 phút và một lượt nạp vô ích.

    Đây là lỗi có thật (30/07/2026): sau Runtime > Restart, Colab xoá sạch
    /content nên LORA_DIR mặc định biến mất. Script nạp xong toàn bộ Qwen3-8B
    rồi mới ném "Can't find 'adapter_config.json'" — và vì PEFT thử tiếp đường
    Hugging Face Hub, thông báo cuối cùng lại là "Repo id must be in the form
    'repo_name'", che mất nguyên nhân thật.
    """
    if Path(path, marker).exists():
        return
    exists = Path(path).exists()
    lines = [
        f"Không thấy {marker} trong {what}: {path}",
        f"  (thư mục {'có tồn tại nhưng thiếu file' if exists else 'KHÔNG tồn tại'})",
        "",
        "Nhiều khả năng: Runtime > Restart đã xoá /content. Thử các đường sau:",
    ]
    lines += [f"  - {h}" for h in hints]
    for candidate in hints:
        if Path(candidate, marker).exists():
            lines += ["", f"✓ TÌM THẤY ở: {candidate}",
                      f"  Chạy lại sau khi đặt:  os.environ['{what}'] = '{candidate}'"]
            break
    raise SystemExit("\n".join(lines))


def _neutralize_torchao() -> None:
    """
    Vô hiệu hoá đường torchao của PEFT. An toàn: pipeline này không dùng torchao
    ở bất kỳ đâu (lượng tử hoá đi đường bitsandbytes lúc train, AWQ lúc serve).

    VÌ SAO PHẢI LÀM: `peft.import_utils.is_torchao_available()` — một hàm tên
    "is X available" — lại NÉM ImportError khi bản torchao cũ hơn yêu cầu, thay
    vì trả về False. Colab cài sẵn torchao 0.10.0 còn PEFT mới đòi > 0.16.0, mà
    `dispatch_torchao` được gọi cho MỌI module khi tiêm LoRA. Kết quả: merge
    chết giữa chừng SAU KHI đã nạp xong 16GB weights (30/07/2026).

    Vá ở HAI chỗ. `peft/tuners/lora/torchao.py` làm
    `from peft.import_utils import is_torchao_available` ở đầu module, tức là
    nó giữ tham chiếu RIÊNG — vá mỗi `import_utils` là không đủ.
    """
    try:
        from peft import import_utils
    except ImportError:
        return
    try:
        import_utils.is_torchao_available()
        return                              # bản torchao hợp lệ, không cần vá
    except ImportError as exc:
        reason = str(exc).split(".")[0]
    except Exception:
        return

    import_utils.is_torchao_available = lambda: False
    try:
        from peft.tuners.lora import torchao as lora_torchao

        lora_torchao.is_torchao_available = lambda: False
    except ImportError:
        pass
    print(f"⚠ Bỏ qua nhánh torchao của PEFT ({reason}) — pipeline này không dùng torchao.")


def stage_merge() -> None:
    """LoRA (train trên nền 4-bit) phải gộp vào weights ĐỦ PRECISION."""
    _require_dir(
        LORA_DIR, "adapter_config.json", "LORA_DIR",
        [
            "/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-lora",
            "/content/drive/MyDrive/ANSER_data/anser-v3-lora",
            "/content/checkpoints/anser-v3-lora",
        ],
    )

    import torch

    # PHẢI gọi trước PeftModel.from_pretrained — sau đó là đã muộn.
    _neutralize_torchao()

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

    # `chat_template.jinja` là FILE RIÊNG (transformers >= 4.49). Bước quantize
    # cài autoawq, mà gói đó hay kéo transformers XUỐNG bản cũ — bản cũ chỉ tìm
    # template trong tokenizer_config.json nên không thấy file này, và
    # apply_chat_template sẽ vỡ. Bắt ở đây, trước khi nạp 16GB.
    if not getattr(tokenizer, "chat_template", None):
        template_file = Path(MERGED_DIR, "chat_template.jinja")
        raise SystemExit(
            "Tokenizer không có chat template — mẫu calibration sẽ sai định dạng "
            "so với lúc train (P4).\n"
            + (
                f"  File {template_file.name} CÓ trong {MERGED_DIR}, nhưng bản "
                "transformers hiện tại không đọc được.\n"
                "  Nhiều khả năng autoawq đã hạ cấp transformers. Cài lại:\n"
                '    !pip install -q "transformers>=4.51.3"\n'
                if template_file.exists()
                else f"  Không thấy {template_file}. Bản gộp thiếu template.\n"
            )
        )
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
    # Cùng lý do như stage_merge: bản gộp ~16GB nằm ở /content nên cũng bay
    # theo mỗi lần restart. Biết sớm hơn 4 phút.
    _require_dir(
        MERGED_DIR, "config.json", "MERGED_DIR",
        ["/content/checkpoints/anser-v3-merged"],
    )

    # File calibration cũng phải kiểm TẠI ĐÂY. Trước đây `_calibration_texts()`
    # chỉ chạy khi đã tới lúc truyền tham số cho `model.quantize()`, tức là SAU
    # khi nạp xong 16GB bản gộp — cùng đúng cái bẫy vừa vá cho stage_merge.
    # Sau mỗi lần Runtime > Restart, ANSER_GENERATED_DIR mất theo, DATA_FILE
    # tụt về đường trong repo và assert vỡ ở phút thứ tư.
    if not DATA_FILE.exists():
        raise SystemExit(
            f"Thiếu dữ liệu calibration: {DATA_FILE}\n"
            "  AWQ cần mẫu in-domain từ train_v3.jsonl để hiệu chuẩn.\n\n"
            "Nhiều khả năng: sau Runtime > Restart thì ANSER_GENERATED_DIR mất.\n"
            "Chạy lại cell 1.2, hoặc đặt tay:\n"
            "  os.environ['ANSER_GENERATED_DIR'] = "
            "'/content/drive/MyDrive/ANSER_AI_Logistics/generated'"
        )

    try:
        from awq import AutoAWQForCausalLM
    except ImportError as exc:
        raise SystemExit(
            f"Thiếu autoawq ({exc}). Cài: pip install autoawq==0.2.9\n"
            "Nếu xung đột version transformers: cài autoawq ở bước RIÊNG sau khi "
            "train xong, hoặc dùng đường llm-compressor (xem README)."
        )
    from transformers import AutoTokenizer

    # Dựng mẫu calibration TRƯỚC khi nạp model. Chỉ mất vài giây, nhưng nó kiểm
    # luôn cả ba thứ hay hỏng: file dữ liệu, tokenizer, và chat template. Trước
    # đây `_calibration_texts()` nằm ở vị trí tham số của `model.quantize()` nên
    # chỉ chạy SAU khi đã nạp xong 16GB — hỏng gì cũng phải chờ hết bốn phút.
    calib = _calibration_texts()
    print(f"✓ {len(calib)} mẫu calibration in-domain, đã render đúng chat template")

    print(f"Tải model đã gộp từ {MERGED_DIR}...")
    model = AutoAWQForCausalLM.from_pretrained(
        MERGED_DIR, safetensors=True, low_cpu_mem_usage=True
    )
    tokenizer = AutoTokenizer.from_pretrained(MERGED_DIR)

    quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": 4, "version": "GEMM"}
    print(f"Quantize AWQ 4-bit với {N_CALIB} mẫu calibration in-domain...")
    model.quantize(tokenizer, quant_config=quant_config, calib_data=calib)

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
