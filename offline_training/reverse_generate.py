"""
reverse_generate.py — BƯỚC 2 pipeline v3: DeepSeek viết tin nhắn cho seed có sẵn.

Đầu vào : generated/seeds_extraction_{train,eval}.jsonl (từ make_extraction_seeds.py)
Đầu ra  : generated/train_extraction.jsonl  — format messages, sẵn sàng train
          generated/eval_extraction.jsonl   — format benchmark (id/today/message/gt)

Teacher CHỈ viết phần ngôn ngữ; nhãn (ground truth) đã chốt từ bước 1.
Mỗi tin nhắn sinh xong được VERIFY tất định (điểm lấy/giao, tên khách phải
xuất hiện — so khớp bỏ dấu; trường thiếu không được nhắc tới) — rớt thì retry
1 lần kèm lý do, vẫn rớt thì loại và ghi log.

Incremental + resume: đứt API giữa chừng, chạy lại là tiếp tục.

CHẠY (cần DEEPSEEK_API_KEY trong env / Colab Secrets):
  python offline_training/reverse_generate.py            # cả train lẫn eval
  python offline_training/reverse_generate.py --split eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date

from offline_training.dgen_common import (
    GENERATED_DIR,
    append_jsonl,
    done_ids,
    fuzzy_contains,
    get_async_client,
    load_jsonl,
)
from src.core.prompts import Prompts

MODEL = "deepseek-chat"      # viết văn không cần R1 — V3 rẻ hơn ~4 lần
TEMPERATURE = 1.0            # cần đa dạng câu chữ
MAX_TOKENS = 200
CONCURRENT = 5

TEACHER_SYSTEM = (
    "Bạn tạo dữ liệu huấn luyện cho trợ lý logistics. Đóng vai chủ doanh nghiệp "
    "vận tải Việt Nam nhắn tin cho trợ lý AI để hỏi báo giá. Chỉ in ra đúng nội "
    "dung tin nhắn — không giải thích, không ngoặc kép, không tiêu đề."
)

# Nhãn tiếng Việt cho từng loại thông tin trong prompt teacher
_FACT_LABELS = {
    "origin": "Điểm lấy hàng",
    "destination": "Điểm giao hàng",
    "vehicle_phrase": "Loại xe — dùng đúng cụm",
    "cargo": "Loại hàng",
    "date_phrase": "Thời điểm lấy hàng — dùng đúng cụm",
    "customer_name": "Tên khách/người nhận báo giá",
    "customer_email": "Email nhận báo giá (ghi nguyên văn)",
}
_MISSING_LABELS = {
    "origin": "điểm lấy hàng",
    "destination": "điểm giao hàng",
    "vehicle_type": "loại xe / trọng tải",
}


def build_teacher_prompt(seed: dict) -> str:
    lines = ["Viết MỘT tin nhắn duy nhất theo ràng buộc sau.", "",
             "THÔNG TIN PHẢI CÓ (diễn đạt tự nhiên, không liệt kê máy móc):"]
    for key, label in _FACT_LABELS.items():
        if key in seed["facts"]:
            value = seed["facts"][key]
            if key in ("vehicle_phrase", "date_phrase"):
                lines.append(f'- {label} "{value}"')
            else:
                lines.append(f"- {label}: {value}")

    if seed["must_not_mention"]:
        lines.append("")
        lines.append("TUYỆT ĐỐI KHÔNG nhắc đến (kể cả gián tiếp):")
        for field in seed["must_not_mention"]:
            lines.append(f"- {_MISSING_LABELS[field]}")

    lines += [
        "",
        f"PHONG CÁCH: {seed['style']}.",
        "ĐỘ DÀI: 1-2 câu, dưới 220 ký tự.",
    ]
    return "\n".join(lines)


def verify_message(message: str, seed: dict) -> str | None:
    """Trả None nếu đạt, ngược lại trả lý do rớt (đưa vào retry feedback)."""
    if not message or len(message) > 350:
        return "tin nhắn rỗng hoặc quá dài"
    if "{" in message or "json" in message.lower():
        return "tin nhắn chứa JSON/markup"

    gt = seed["ground_truth"]
    for field in ("origin", "destination", "customer_name"):
        if gt[field] and not fuzzy_contains(message, gt[field]):
            return f"thiếu thông tin bắt buộc: {gt[field]!r}"

    if gt["customer_email"]:
        if gt["customer_email"] not in message:
            return f"thiếu email nguyên văn {gt['customer_email']!r}"
    elif "@" in message:
        return "chứa email trong khi ground truth không có email"

    return None


def to_train_entry(seed: dict, message: str) -> dict:
    """Format messages — system/user dựng bằng ĐÚNG code runtime (P4)."""
    today = date.fromisoformat(seed["today"])
    return {
        "_id": seed["_id"],
        "_source": "logistics_extract",
        "messages": [
            {"role": "system", "content": Prompts.LOGISTICS_EXTRACT_SYSTEM},
            {"role": "user", "content": Prompts.format_extraction_user(message, today)},
            # Xuất đủ 7 key, thiếu = null tường minh — dạy kỷ luật không đoán
            {"role": "assistant",
             "content": json.dumps(seed["ground_truth"], ensure_ascii=False)},
        ],
    }


def to_eval_entry(seed: dict, message: str) -> dict:
    return {
        "_id": seed["_id"],
        "today": seed["today"],
        "message": message,
        "ground_truth": seed["ground_truth"],
    }


async def process_seed(client, semaphore, seed: dict, out_path: Path,
                       formatter, stats: dict) -> None:
    async with semaphore:
        feedback = ""
        for attempt in (1, 2):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": TEACHER_SYSTEM},
                        {"role": "user", "content": build_teacher_prompt(seed) + feedback},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
            except Exception as exc:
                print(f"  ✗ {seed['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return

            message = (resp.choices[0].message.content or "").strip().strip('"')
            reason = verify_message(message, seed)
            if reason is None:
                append_jsonl(out_path, formatter(seed, message))
                stats["ok"] += 1
                return
            feedback = f"\n\nTin nhắn trước bị loại vì: {reason}. Viết lại cho đúng."
            if attempt == 2:
                print(f"  ⚠ {seed['_id']} loại sau retry: {reason}")
                stats["rejected"] += 1


async def run_split(client, split: str) -> None:
    seed_path = GENERATED_DIR / f"seeds_extraction_{split}.jsonl"
    seeds = load_jsonl(seed_path)
    if not seeds:
        raise SystemExit(f"Thiếu {seed_path} — chạy make_extraction_seeds.py trước")

    if split == "train":
        out_path, formatter = GENERATED_DIR / "train_extraction.jsonl", to_train_entry
    else:
        out_path, formatter = GENERATED_DIR / "eval_extraction.jsonl", to_eval_entry

    done = done_ids(out_path)
    todo = [s for s in seeds if s["_id"] not in done]
    print(f"[{split}] tổng {len(seeds)} — đã có {len(done)} — cần chạy {len(todo)}")
    if not todo:
        return

    semaphore = asyncio.Semaphore(CONCURRENT)
    stats = {"ok": 0, "rejected": 0, "api_fail": 0}
    t0 = time.time()
    await asyncio.gather(*[
        process_seed(client, semaphore, s, out_path, formatter, stats) for s in todo
    ])
    print(f"[{split}] xong {stats['ok']} — loại {stats['rejected']} — "
          f"lỗi API {stats['api_fail']} — {(time.time() - t0) / 60:.1f} phút")
    if stats["api_fail"]:
        print("  ⚠ chạy lại script để retry các entry lỗi API (tự resume)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["train", "eval", "both"], default="both")
    args = parser.parse_args()

    client = get_async_client()
    for split in (["train", "eval"] if args.split == "both" else [args.split]):
        await run_split(client, split)


if __name__ == "__main__":
    asyncio.run(main())
