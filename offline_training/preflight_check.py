"""
preflight_check.py — kiểm tra MỌI thứ trước khi đốt giờ GPU Colab.

VÌ SAO CÓ FILE NÀY
------------------
Một buổi train hỏng vì lý do vặt (thiếu file, sai định dạng, hết dung lượng
Drive, prompt lệch so với data) tốn cả buổi và tiền Colab Pro. Mọi thứ kiểm
được bằng CPU thì phải kiểm TRƯỚC.

Chạy được ở cả máy dev (không GPU) lẫn Colab:
  python offline_training/preflight_check.py                  # kiểm cơ bản
  python offline_training/preflight_check.py --tokenizer      # + đo độ dài token (tải tokenizer ~12MB)
  python offline_training/preflight_check.py --drive /content/drive/MyDrive/ANSER_data

Thoát mã 1 nếu có lỗi CHẶN. Cảnh báo (⚠) không chặn nhưng phải đọc.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import GENERATED_DIR, load_jsonl  # noqa: E402
from offline_training.make_n8n_pairs import _stage_catalog_dir  # noqa: E402

# Ngân sách VRAM thực đo trên L4 22.5GB, QLoRA 8B, grad checkpointing bật.
# Vượt ngưỡng này gần như chắc chắn OOM giữa chừng.
SEQ_BUDGET = {"L4": 8192, "T4": 4096, "A100": 16384}
# Cần cho: model gốc tải về (~16GB) + checkpoint + AWQ. /content của Colab ~100GB.
MIN_DRIVE_FREE_GB = 8.0

_errors: list[str] = []
_warnings: list[str] = []


def fail(msg: str) -> None:
    _errors.append(msg)
    print(f"  ❌ {msg}")


def warn(msg: str) -> None:
    _warnings.append(msg)
    print(f"  ⚠  {msg}")


def ok(msg: str) -> None:
    print(f"  ✓  {msg}")


# ---------------------------------------------------------------------------
# 1. File dữ liệu
# ---------------------------------------------------------------------------

def check_files() -> tuple[list[dict], list[dict]]:
    print("\n[1] File dữ liệu")
    train = load_jsonl(GENERATED_DIR / "train_v3.jsonl")
    eval_ = load_jsonl(GENERATED_DIR / "eval_v3.jsonl")

    if not train:
        fail("Thiếu generated/train_v3.jsonl — chạy build_dataset_v3.py trước")
        return [], []
    ok(f"train_v3.jsonl: {len(train)} mẫu")

    if not eval_:
        fail("Thiếu generated/eval_v3.jsonl")
    else:
        ok(f"eval_v3.jsonl: {len(eval_)} mẫu")

    if len(train) < 300:
        warn(
            f"Chỉ {len(train)} mẫu train — quá ít cho fine-tune có ý nghĩa. "
            "Nhiều khả năng chưa chạy reverse_generate.py / make_narration_pairs.py "
            "(cần DEEPSEEK_API_KEY)."
        )

    for name in ("eval_extraction.jsonl", "eval_n8n.jsonl", "eval_narration.jsonl",
                 "eval_agent.jsonl"):
        rows = load_jsonl(GENERATED_DIR / name)
        if rows:
            ok(f"{name}: {len(rows)} ca benchmark")
        else:
            warn(f"Thiếu {name} — benchmark sẽ bỏ qua phần tương ứng")

    return train, eval_


# ---------------------------------------------------------------------------
# 2. Cấu trúc mẫu
# ---------------------------------------------------------------------------

def _guess_branch(msgs: list[dict]) -> str:
    """Đoán mẫu thuộc nhánh nào dựa trên system prompt — để báo lỗi CỤ THỂ."""
    from src.core.prompts import Prompts

    system = msgs[0].get("content", "") if msgs else ""
    for name in ("LOGISTICS_EXTRACT_SYSTEM", "GENERAL_SYSTEM", "REPORT_SYSTEM",
                 "DATA_SYSTEM", "RETRIEVAL_SYSTEM", "EXPLAIN_SYSTEM",
                 "CODER_SYSTEM", "AGENT_SYSTEM"):
        prompt = getattr(Prompts, name, "")
        if prompt and system.startswith(prompt.split("{")[0][:60]):
            return name
    return "(không nhận ra prompt)"


def check_shape(train: list[dict]) -> None:
    print("\n[2] Cấu trúc mẫu")
    bad_role, bad_order, empty = 0, 0, 0
    empty_detail: list[str] = []

    for idx, row in enumerate(train):
        msgs = row.get("messages")
        if not isinstance(msgs, list) or len(msgs) < 3:
            bad_order += 1
            continue
        if msgs[0]["role"] != "system":
            bad_role += 1
        if msgs[-1]["role"] != "assistant":
            bad_order += 1
        if not str(msgs[-1].get("content", "")).strip():
            empty += 1
            if len(empty_detail) < 5:
                user = str(msgs[1].get("content", ""))[:70].replace("\n", " ")
                empty_detail.append(
                    f"#{idx} nhánh={_guess_branch(msgs)} "
                    f"({len(msgs)} message) user={user!r}"
                )
        # user/assistant phải xen kẽ sau system
        expected = "user"
        for m in msgs[1:]:
            if m["role"] != expected:
                bad_order += 1
                break
            expected = "assistant" if expected == "user" else "user"

    if bad_role:
        fail(f"{bad_role} mẫu không mở đầu bằng system")
    if bad_order:
        fail(f"{bad_order} mẫu sai thứ tự vai (phải system → user → assistant xen kẽ)")
    if empty:
        fail(f"{empty} mẫu có câu trả lời rỗng")
        for line in empty_detail:
            print(f"       {line}")
    if not (bad_role or bad_order or empty):
        ok("Mọi mẫu đúng thứ tự vai, không có câu trả lời rỗng")

    multiturn = [r for r in train if len(r["messages"]) > 3]
    if multiturn:
        ok(f"{len(multiturn)} mẫu đa lượt (dạy kế thừa ngữ cảnh)")
    else:
        warn("Không có mẫu đa lượt — hội thoại nhiều lượt sẽ không được dạy")

    # Nhánh nào có mẫu, nhánh nào TRỐNG. Nhánh trống nghĩa là model chạy zero-shot
    # ở đó — chạy được không có nghĩa là chạy đúng.
    by_branch: dict[str, int] = {}
    for row in train:
        by_branch[_guess_branch(row.get("messages", []))] = (
            by_branch.get(_guess_branch(row.get("messages", [])), 0) + 1
        )
    print("     phân bố nhánh:")
    for name, count in sorted(by_branch.items(), key=lambda kv: -kv[1]):
        print(f"       {name:26s} {count:5d}")
    for required in ("AGENT_SYSTEM", "EXPLAIN_SYSTEM", "REPORT_SYSTEM"):
        if not by_branch.get(required):
            warn(f"Nhánh {required} KHÔNG có mẫu train nào — sẽ chạy zero-shot")


# ---------------------------------------------------------------------------
# 3. Khớp prompt train ↔ serve  (P4 — lỗi âm thầm nguy hiểm nhất)
# ---------------------------------------------------------------------------

def check_prompt_parity(train: list[dict]) -> None:
    print("\n[3] Prompt trong data có khớp runtime không (P4)")
    from src.core.prompts import Prompts

    manifest_path = GENERATED_DIR / "dataset_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        from src.core.workflow_schema import catalog_fingerprint
        now = catalog_fingerprint()
        was = manifest.get("catalog_fingerprint")
        if was and was != now:
            fail(
                f"Catalog node ĐÃ ĐỔI kể từ lúc dựng dataset ({was} → {now}). "
                "CODER_SYSTEM trong data không còn khớp runtime — "
                "chạy lại build_dataset_v3.py."
            )
        else:
            ok(f"Vân tay catalog khớp ({now})")
    else:
        warn("Chưa có dataset_manifest.json — chạy lại build_dataset_v3.py để ghi vân tay")

    # System prompt trong data phải là bản runtime hiện hành
    runtime_prompts = {
        Prompts.LOGISTICS_EXTRACT_SYSTEM, Prompts.GENERAL_SYSTEM,
    }
    unknown = 0
    for row in train:
        system = row["messages"][0]["content"]
        if system in runtime_prompts:
            continue
        # Các prompt có {context}/{tools} được format nên chỉ so phần đầu
        if any(system.startswith(p.split("{")[0][:60])
               for p in (Prompts.RETRIEVAL_SYSTEM, Prompts.DATA_SYSTEM,
                         Prompts.REPORT_SYSTEM, Prompts.EXPLAIN_SYSTEM,
                         Prompts.CODER_SYSTEM)):
            continue
        unknown += 1
    if unknown:
        fail(
            f"{unknown} mẫu dùng system prompt KHÔNG có trong prompts.py hiện tại — "
            "model sẽ học hành vi gắn với một prompt không tồn tại lúc serve."
        )
    else:
        ok("Mọi system prompt trong data đều là bản runtime hiện hành")

    # Lượt user của nhánh trích xuất phải có dòng "Hôm nay là ..."
    extract_rows = [
        r for r in train
        if r["messages"][0]["content"] == Prompts.LOGISTICS_EXTRACT_SYSTEM
    ]
    if extract_rows:
        missing = sum(
            1 for r in extract_rows
            for m in r["messages"]
            if m["role"] == "user" and not m["content"].startswith("Hôm nay là")
        )
        if missing:
            fail(f"{missing} lượt user nhánh trích xuất thiếu dòng 'Hôm nay là...' "
                 "— lệch với format_extraction_user lúc serve")
        else:
            ok(f"{len(extract_rows)} mẫu trích xuất đều có mốc ngày đúng định dạng")


# ---------------------------------------------------------------------------
# 4. Nhãn hợp lệ theo schema runtime
# ---------------------------------------------------------------------------

def check_labels(train: list[dict]) -> None:
    print("\n[4] Nhãn có hợp lệ theo schema runtime không")
    from src.core.prompts import Prompts
    from src.core.schemas import QuoteExtraction
    from src.core.workflow_schema import validate_workflow

    n_extract, bad_extract = 0, 0
    n_wf, bad_wf = 0, 0

    for row in train:
        system = row["messages"][0]["content"]
        answer = row["messages"][-1]["content"]

        if system == Prompts.LOGISTICS_EXTRACT_SYSTEM:
            n_extract += 1
            try:
                QuoteExtraction(**json.loads(answer))
            except Exception:
                bad_extract += 1
        elif system.startswith(Prompts.CODER_SYSTEM.split("{")[0][:60]):
            n_wf += 1
            try:
                valid, _why = validate_workflow(json.loads(answer))
            except Exception:
                valid = False
            if not valid:
                bad_wf += 1

    if bad_extract:
        fail(f"{bad_extract}/{n_extract} nhãn trích xuất KHÔNG khớp QuoteExtraction")
    elif n_extract:
        ok(f"{n_extract} nhãn trích xuất hợp lệ theo schema runtime")

    if bad_wf:
        fail(f"{bad_wf}/{n_wf} workflow trong data KHÔNG qua validate_workflow")
    elif n_wf:
        ok(f"{n_wf} workflow trong data đều qua validator runtime")


# ---------------------------------------------------------------------------
# 5. Bí mật (R2b)
# ---------------------------------------------------------------------------

def check_secrets(train: list[dict], eval_: list[dict]) -> None:
    print("\n[5] Quét bí mật (R2b)")
    from offline_training.build_dataset_v3 import scan_secrets

    hits = 0
    for row in train + eval_:
        if scan_secrets(json.dumps(row, ensure_ascii=False)):
            hits += 1
    if hits:
        fail(f"{hits} mẫu chứa chuỗi giống secret — KHÔNG được train/đẩy lên Drive")
    else:
        ok("Không có secret trong tập train/eval")


# ---------------------------------------------------------------------------
# 6. Độ dài token (tuỳ chọn — cần tokenizer)
# ---------------------------------------------------------------------------

def check_token_lengths(train: list[dict], model_id: str, gpu: str) -> None:
    print(f"\n[6] Độ dài token (tokenizer {model_id})")
    try:
        from transformers import AutoTokenizer
    except ImportError:
        warn("Chưa cài transformers — bỏ qua đo độ dài token")
        return

    try:
        tok = AutoTokenizer.from_pretrained(model_id)
    except Exception as exc:
        warn(f"Không tải được tokenizer ({exc}) — bỏ qua")
        return

    lengths = []
    for row in train:
        text = tok.apply_chat_template(
            row["messages"], tokenize=False, enable_thinking=False
        )
        lengths.append(len(tok(text, add_special_tokens=False)["input_ids"]))

    lengths.sort()
    budget = SEQ_BUDGET.get(gpu, 8192)
    p50 = lengths[len(lengths) // 2]
    p95 = lengths[int(len(lengths) * 0.95)]
    over = sum(1 for x in lengths if x > budget)

    ok(f"token p50={p50:,}  p95={p95:,}  max={lengths[-1]:,}")
    print(f"     ngân sách {gpu}: MAX_SEQ_LEN={budget:,}")
    if over:
        pct = over / len(lengths) * 100
        (warn if pct < 10 else fail)(
            f"{over} mẫu ({pct:.0f}%) vượt {budget:,} token → sẽ bị LOẠI khi train. "
            + ("Chấp nhận được." if pct < 10 else
               "Mất quá nhiều dữ liệu — cân nhắc GPU lớn hơn hoặc chia nhỏ mẫu.")
        )
    else:
        ok("Không mẫu nào vượt ngân sách — không mất dữ liệu")


# ---------------------------------------------------------------------------
# 7. Dung lượng đĩa
# ---------------------------------------------------------------------------

def check_disk(drive_dir: str | None) -> None:
    print("\n[7] Dung lượng đĩa")
    free_content = shutil.disk_usage("/content" if Path("/content").exists() else ".").free / 1e9
    ok(f"Ổ làm việc còn trống {free_content:.1f} GB")
    if free_content < 40:
        warn("Dưới 40GB — model gốc (~16GB) + checkpoint + bản gộp có thể không đủ chỗ")

    if not drive_dir:
        return
    path = Path(drive_dir)
    if not path.exists():
        warn(f"{drive_dir} chưa tồn tại (chưa mount Drive?) — bỏ qua kiểm tra")
        return
    free_drive = shutil.disk_usage(str(path)).free / 1e9
    used = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9
    print(f"     {drive_dir}: đang dùng {used:.1f} GB, còn trống {free_drive:.1f} GB")
    if free_drive < MIN_DRIVE_FREE_GB:
        fail(
            f"Drive chỉ còn {free_drive:.1f} GB, cần ≥ {MIN_DRIVE_FREE_GB} GB cho model "
            "AWQ (~5.5GB). Xoá bớt model cũ (anser-retail-v2-awq, anser-qwen-lora) "
            "hoặc đổi chỗ lưu."
        )
    else:
        ok("Đủ chỗ cho model AWQ (~5.5GB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", action="store_true",
                        help="đo độ dài token (tải tokenizer)")
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--gpu", default="L4", choices=sorted(SEQ_BUDGET))
    parser.add_argument("--drive", default="", help="thư mục Drive để kiểm dung lượng")
    args = parser.parse_args()

    _stage_catalog_dir()
    from src.core.workflow_schema import reload_catalog
    reload_catalog()

    print("=" * 62)
    print("  PREFLIGHT — kiểm tra trước khi train trên Colab")
    print("=" * 62)

    train, eval_ = check_files()
    if train:
        check_shape(train)
        check_prompt_parity(train)
        check_labels(train)
        check_secrets(train, eval_)
        if args.tokenizer:
            check_token_lengths(train, args.model, args.gpu)
    check_disk(args.drive or None)

    print("\n" + "=" * 62)
    if _errors:
        print(f"  ❌ {len(_errors)} LỖI CHẶN — sửa xong mới train:")
        for e in _errors:
            print(f"     • {e}")
        print("=" * 62)
        sys.exit(1)
    if _warnings:
        print(f"  ✅ Không có lỗi chặn. {len(_warnings)} cảnh báo cần đọc:")
        for w in _warnings:
            print(f"     • {w}")
    else:
        print("  ✅ Sẵn sàng train.")
    print("=" * 62)


if __name__ == "__main__":
    main()
