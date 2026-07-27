"""
make_narration_pairs.py — BƯỚC 3 pipeline v3: data diễn giải kết quả tính toán (XAI).

NGUYÊN TẮC (P1 + P2)
--------------------
- Mọi CON SỐ trong context đều do engine thật tính (`compute_quote`,
  `select_carrier`) trên kịch bản hư cấu — teacher CHỈ viết lời diễn giải.
- Chốt chặn tất định sau khi teacher trả lời:
    * mọi số >= 4 chữ số trong câu trả lời PHẢI có trong context (không bịa số)
    * loại "customer": context chỉ chứa phần `quote` (không thể lộ biên theo
      cấu trúc) + quét từ cấm (biên/lãi/giá gốc...)
- Sample dùng ĐÚNG Prompts.DATA_SYSTEM của runtime (P4): context là JSON,
  model trả lời chỉ dựa trên dữ liệu đó.

CHẠY (cần DEEPSEEK_API_KEY):
  python offline_training/make_narration_pairs.py --n 180
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from offline_training.dgen_common import (
    GENERATED_DIR,
    append_jsonl,
    customer_leak,
    done_ids,
    get_async_client,
    narration_numbers_ok,
)
from src.core.carrier_selection import Carrier, QuoteOffer, RouteRequest, select_carrier
from src.core.pricing import PricingRule, Surcharge, compute_quote
from src.core.prompts import Prompts

MODEL = "deepseek-chat"
CONCURRENT = 5
EVAL_RATIO = 0.15

TEACHER_SYSTEM = (
    "Bạn là ANSER Brain — trợ lý cho chủ doanh nghiệp vận tải Việt Nam. "
    "Trả lời CHỈ dựa trên DỮ LIỆU JSON được đưa, bằng tiếng Việt, văn xuôi, "
    "tối đa 5 câu. Mọi con số phải lấy nguyên văn từ dữ liệu — không tự tính, "
    "không làm tròn khác đi, không bịa. Không xuất JSON."
)

_SURCHARGE_POOL = [
    Surcharge("Phụ phí hàng lạnh", amount=250_000),
    Surcharge("Bốc xếp hai đầu", amount=150_000),
    Surcharge("Phí chờ", pct=3.0),
    Surcharge("Cầu đường", amount=120_000),
]
_CARRIER_NAMES = [
    "Vận tải Minh Long", "Nhà xe Hòa Phát Trans", "Vận tải Sông Hồng",
    "Nhà xe Đại An", "Vận tải Tân Cảng Bắc", "Nhà xe Trường Thịnh",
]
_ROUTES = [
    ("Hữu Nghị", "Hải Phòng"), ("KCN Quế Võ", "Hà Nội"),
    ("cảng Đình Vũ", "Bắc Giang"), ("Nội Bài", "Lạng Sơn"),
]
_VEHICLES = ["1.5T", "3T", "5T", "dau_keo"]

QUESTIONS_QUOTE = [
    "Vì sao giá chốt ra con số này? Giải thích ngắn cho tôi.",
    "Breakdown báo giá này thế nào?",
    "Giá dầu đang ảnh hưởng bao nhiêu vào báo giá này?",
]
QUESTIONS_CARRIER = [
    "Vì sao chọn hãng xe đứng đầu?",
    "So sánh hai hãng đứng đầu giúp tôi.",
    "Có hãng nào bị loại không, vì sao?",
]
QUESTIONS_CUSTOMER = [
    "Soạn tin nhắn báo giá ngắn gọn để gửi khách.",
    "Viết nội dung email báo giá lịch sự cho khách từ dữ liệu này.",
]


def _make_quote_scenario(rng: random.Random) -> dict:
    rule = PricingRule(
        base_margin_pct=rng.uniform(6, 15),
        fuel_sensitivity=rng.uniform(0.30, 0.40),
        fuel_baseline_price=rng.choice([23_000, 24_500, 25_000, 26_500]),
        min_margin_amount=rng.choice([0, 300_000, 500_000]),
        surcharges=rng.sample(_SURCHARGE_POOL, k=rng.randrange(0, 3)),
    )
    carrier_cost = rng.randrange(40, 360) * 50_000            # 2tr .. 18tr
    current_fuel = rule.fuel_baseline_price * rng.uniform(0.88, 1.12)
    result = compute_quote(carrier_cost, rule, current_fuel_price=round(current_fuel))
    origin, destination = rng.choice(_ROUTES)
    route = {"origin": origin, "destination": destination,
             "vehicle_type": rng.choice(_VEHICLES)}
    return {"route": route, "result": result}


def _make_carrier_scenario(rng: random.Random) -> dict:
    origin, destination = rng.choice(_ROUTES)
    vehicle = rng.choice(_VEHICLES)
    request = RouteRequest(origin=origin, destination=destination, vehicle_type=vehicle)

    carriers, offers = [], []
    for i, name in enumerate(rng.sample(_CARRIER_NAMES, k=rng.randrange(3, 6))):
        # Hãng đầu luôn chạy được loại xe yêu cầu -> luôn có ứng viên hợp lệ
        has_vehicle = i == 0 or rng.random() < 0.75
        carriers.append(Carrier(
            id=f"C{i + 1}",
            name=name,
            vehicle_types={vehicle} if has_vehicle else {rng.choice(_VEHICLES)},
            discount_pct=rng.choice([None, 3.0, 5.0, 8.0]),
            credit_days=rng.choice([None, 15, 30, 45]),
            years_partner=rng.choice([None, 1.0, 3.0, 7.0]),
            on_time_rate=rng.choice([None, 0.85, 0.92, 0.97]),
        ))
        if i == 0 or rng.random() < 0.9:
            offers.append(QuoteOffer(
                carrier_id=f"C{i + 1}",
                price=rng.randrange(50, 300) * 50_000,
            ))
    result = select_carrier(carriers, offers, request)
    return {"request": request.__dict__, "result": result}


def make_scenarios(n: int, seed: int) -> list[dict]:
    """Sinh kịch bản tất định theo seed. kind: quote/carrier (chủ DN) + customer."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        kind = rng.choices(["quote", "carrier", "customer"], weights=[40, 35, 25])[0]
        if kind == "quote":
            scenario = _make_quote_scenario(rng)
            context = {"route": scenario["route"], **scenario["result"]}
            question = rng.choice(QUESTIONS_QUOTE)
        elif kind == "carrier":
            scenario = _make_carrier_scenario(rng)
            context = scenario["result"]
            question = rng.choice(QUESTIONS_CARRIER)
        else:
            scenario = _make_quote_scenario(rng)
            # KHÁCH CUỐI: chỉ phần quote — biên không thể lộ theo cấu trúc (P2)
            context = {"route": scenario["route"], "quote": scenario["result"]["quote"]}
            question = rng.choice(QUESTIONS_CUSTOMER)
        rows.append({
            "_id": f"NA{i:04d}",
            "kind": kind,
            "context": json.dumps(context, ensure_ascii=False),
            "question": question,
        })
    return rows


def verify_answer(answer: str, row: dict) -> str | None:
    if not answer or len(answer) > 1200:
        return "rỗng hoặc quá dài"
    ok, bad = narration_numbers_ok(answer, row["context"])
    if not ok:
        return f"chứa số không có trong dữ liệu: {bad}"
    if row["kind"] == "customer":
        leaks = customer_leak(answer)
        if leaks:
            return f"lộ thông tin nội bộ: {', '.join(leaks)}"
    return None


def to_train_entry(row: dict, answer: str) -> dict:
    return {
        "_id": row["_id"],
        "_source": "narration",
        "messages": [
            {"role": "system", "content": Prompts.DATA_SYSTEM.format(context=row["context"])},
            {"role": "user", "content": row["question"]},
            {"role": "assistant", "content": answer},
        ],
    }


async def process_row(client, semaphore, row: dict, out_path: Path, stats: dict) -> None:
    async with semaphore:
        feedback = ""
        for attempt in (1, 2):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": TEACHER_SYSTEM},
                        {"role": "user",
                         "content": f"DỮ LIỆU:\n{row['context']}\n\n"
                                    f"CÂU HỎI: {row['question']}{feedback}"},
                    ],
                    temperature=0.7,
                    max_tokens=400,
                )
            except Exception as exc:
                print(f"  ✗ {row['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return

            answer = (resp.choices[0].message.content or "").strip()
            reason = verify_answer(answer, row)
            if reason is None:
                append_jsonl(out_path, to_train_entry(row, answer))
                stats["ok"] += 1
                return
            feedback = f"\n\nCâu trả lời trước bị loại vì: {reason}. Viết lại cho đúng."
            if attempt == 2:
                print(f"  ⚠ {row['_id']} loại sau retry: {reason}")
                stats["rejected"] += 1


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=180)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()

    rows = make_scenarios(args.n, args.seed)

    # Tách eval TRƯỚC khi gọi API — benchmark chấm tất định, không cần teacher
    n_eval = max(1, int(len(rows) * EVAL_RATIO))
    eval_rows, train_rows = rows[:n_eval], rows[n_eval:]
    eval_path = GENERATED_DIR / "eval_narration.jsonl"
    if not eval_path.exists():
        for row in eval_rows:
            append_jsonl(eval_path, row)
        print(f"✓ {eval_path} — {len(eval_rows)} kịch bản benchmark")

    out_path = GENERATED_DIR / "train_narration.jsonl"
    done = done_ids(out_path)
    todo = [r for r in train_rows if r["_id"] not in done]
    print(f"[narration] tổng {len(train_rows)} — đã có {len(done)} — cần chạy {len(todo)}")
    if not todo:
        return

    client = get_async_client()
    semaphore = asyncio.Semaphore(CONCURRENT)
    stats = {"ok": 0, "rejected": 0, "api_fail": 0}
    t0 = time.time()
    await asyncio.gather(*[
        process_row(client, semaphore, r, out_path, stats) for r in todo
    ])
    print(f"[narration] xong {stats['ok']} — loại {stats['rejected']} — "
          f"lỗi API {stats['api_fail']} — {(time.time() - t0) / 60:.1f} phút")


if __name__ == "__main__":
    asyncio.run(main())
