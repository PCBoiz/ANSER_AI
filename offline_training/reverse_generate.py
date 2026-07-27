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
import re
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


def _fact_lines(facts: dict) -> list[str]:
    """Các dòng 'phải có' trong prompt teacher, theo thứ tự nhãn cố định."""
    lines = []
    for key, label in _FACT_LABELS.items():
        if key in facts:
            value = facts[key]
            if key in ("vehicle_phrase", "date_phrase"):
                lines.append(f'- {label} "{value}"')   # cụm phải dùng nguyên văn
            else:
                lines.append(f"- {label}: {value}")
    return lines


def build_teacher_prompt(seed: dict) -> str:
    lines = ["Viết MỘT tin nhắn duy nhất theo ràng buộc sau.", "",
             "THÔNG TIN PHẢI CÓ (diễn đạt tự nhiên, không liệt kê máy móc):"]
    lines += _fact_lines(seed["facts"])

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


def build_followup_prompt(seed: dict) -> str:
    """
    Prompt cho seed 2 lượt: teacher viết CẢ HAI lượt trong một lần gọi.

    Lượt 2 cố tình KHÔNG được nhắc lại thông tin cũ — đó chính là điều làm bài
    toán bất khả nếu thiếu lịch sử, và là kỹ năng cần dạy.
    """
    lines = [
        "Viết HAI tin nhắn liên tiếp của cùng một người, theo đúng mẫu:",
        "LƯỢT 1: <tin nhắn>",
        "LƯỢT 2: <tin nhắn>",
        "",
        "LƯỢT 1 — yêu cầu báo giá đầy đủ, phải có:",
    ]
    lines += _fact_lines(seed["facts"])
    lines += [
        "",
        f"LƯỢT 2 — câu hỏi NGẮN nối tiếp, {seed['change_desc']}, phải có:",
    ]
    lines += _fact_lines(seed["facts2"])

    lines += [
        "",
        "LƯỢT 2 TUYỆT ĐỐI KHÔNG nhắc lại điểm lấy hàng, điểm giao hàng hay các",
        "thông tin đã nêu ở lượt 1 (trừ đúng thứ thay đổi). Viết như người ta",
        'nhắn tiếp thật: "thế xe 3 tấn thì sao", "đổi sang thứ 6 được không".',
        "",
        f"PHONG CÁCH cả hai lượt: {seed['style']}.",
        "LƯỢT 1 dưới 220 ký tự; LƯỢT 2 dưới 90 ký tự.",
    ]
    return "\n".join(lines)


def split_two_turns(raw: str):
    """Bóc 'LƯỢT 1: ... LƯỢT 2: ...'. Trả (t1, t2) hoặc (None, None)."""
    match = re.search(
        r"LƯỢT\s*1\s*:\s*(.+?)\s*LƯỢT\s*2\s*:\s*(.+)", raw, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return None, None
    return match.group(1).strip().strip('"'), match.group(2).strip().strip('"')


def verify_message(message: str, seed: dict, gt_key: str = "ground_truth") -> str | None:
    """Trả None nếu đạt, ngược lại trả lý do rớt (đưa vào retry feedback)."""
    if not message or len(message) > 350:
        return "tin nhắn rỗng hoặc quá dài"
    if "{" in message or "json" in message.lower():
        return "tin nhắn chứa JSON/markup"

    gt = seed[gt_key]
    for field in ("origin", "destination", "customer_name"):
        if gt[field] and not fuzzy_contains(message, gt[field]):
            return f"thiếu thông tin bắt buộc: {gt[field]!r}"

    if gt["customer_email"]:
        if gt["customer_email"] not in message:
            return f"thiếu email nguyên văn {gt['customer_email']!r}"
    elif "@" in message:
        return "chứa email trong khi ground truth không có email"

    return None


def verify_followup(turn1: str, turn2: str, seed: dict) -> str | None:
    """Lượt 1 đủ thông tin; lượt 2 nêu thứ đổi và KHÔNG lặp lại ngữ cảnh cũ."""
    reason = verify_message(turn1, seed, "ground_truth")
    if reason:
        return f"lượt 1: {reason}"
    if not turn2 or len(turn2) > 200:
        return "lượt 2 rỗng hoặc quá dài"

    gt1, gt2 = seed["ground_truth"], seed["ground_truth2"]

    # Lượt 2 phải nhắc thứ đã đổi (trừ ngày — cụm ngày được diễn đạt tự do)
    field = seed["changed_field"]
    if field in ("destination", "cargo_type"):
        if not fuzzy_contains(turn2, gt2[field]):
            return f"lượt 2 không nêu {gt2[field]!r}"

    # Lượt 2 KHÔNG được lặp lại ngữ cảnh kế thừa — nếu lặp thì mẫu này không
    # còn dạy được kỹ năng kế thừa nữa (model chỉ cần đọc lượt 2 là đủ).
    for inherited in ("origin", "destination"):
        if inherited == field:
            continue
        value = gt1.get(inherited)
        if value and fuzzy_contains(turn2, value):
            return f"lượt 2 lặp lại thông tin cũ {value!r} — phải để ngầm hiểu"

    return None


def to_train_entry(seed: dict, message) -> dict:
    """
    Format messages — system/user dựng bằng ĐÚNG code runtime (P4).

    Seed 2 lượt cho ra 5 message; train_v3.py tính loss trên message CUỐI nên
    model học đúng việc: sinh JSON lượt 2 KHI ĐÃ CÓ ngữ cảnh lượt 1.
    """
    today = date.fromisoformat(seed["today"])
    system = {"role": "system", "content": Prompts.LOGISTICS_EXTRACT_SYSTEM}

    if seed.get("kind") == "followup":
        turn1, turn2 = message
        return {
            "_id": seed["_id"],
            "_source": "logistics_extract_multiturn",
            "messages": [
                system,
                {"role": "user",
                 "content": Prompts.format_extraction_user(turn1, today)},
                {"role": "assistant",
                 "content": json.dumps(seed["ground_truth"], ensure_ascii=False)},
                {"role": "user",
                 "content": Prompts.format_extraction_user(turn2, today)},
                {"role": "assistant",
                 "content": json.dumps(seed["ground_truth2"], ensure_ascii=False)},
            ],
        }

    return {
        "_id": seed["_id"],
        "_source": "logistics_extract",
        "messages": [
            system,
            {"role": "user", "content": Prompts.format_extraction_user(message, today)},
            # Xuất đủ 7 key, thiếu = null tường minh — dạy kỷ luật không đoán
            {"role": "assistant",
             "content": json.dumps(seed["ground_truth"], ensure_ascii=False)},
        ],
    }


def to_eval_entry(seed: dict, message) -> dict:
    if seed.get("kind") == "followup":
        turn1, turn2 = message
        return {
            "_id": seed["_id"],
            "today": seed["today"],
            "kind": "followup",
            "history": [
                {"role": "user", "content": turn1},
                {"role": "assistant",
                 "content": json.dumps(seed["ground_truth"], ensure_ascii=False)},
            ],
            "message": turn2,
            "ground_truth": seed["ground_truth2"],
        }
    return {
        "_id": seed["_id"],
        "today": seed["today"],
        "kind": "single",
        "message": message,
        "ground_truth": seed["ground_truth"],
    }


async def process_seed(client, semaphore, seed: dict, out_path: Path,
                       formatter, stats: dict) -> None:
    is_followup = seed.get("kind") == "followup"
    prompt = build_followup_prompt(seed) if is_followup else build_teacher_prompt(seed)

    async with semaphore:
        feedback = ""
        for attempt in (1, 2):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": TEACHER_SYSTEM},
                        {"role": "user", "content": prompt + feedback},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS * (2 if is_followup else 1),
                )
            except Exception as exc:
                print(f"  ✗ {seed['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return

            raw = (resp.choices[0].message.content or "").strip()

            if is_followup:
                turn1, turn2 = split_two_turns(raw)
                if turn1 is None:
                    reason, payload = "không đúng mẫu 'LƯỢT 1:/LƯỢT 2:'", None
                else:
                    reason, payload = verify_followup(turn1, turn2, seed), (turn1, turn2)
            else:
                payload = raw.strip('"')
                reason = verify_message(payload, seed)

            if reason is None:
                append_jsonl(out_path, formatter(seed, payload))
                stats["ok"] += 1
                return
            feedback = f"\n\nBản trước bị loại vì: {reason}. Viết lại cho đúng."
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
