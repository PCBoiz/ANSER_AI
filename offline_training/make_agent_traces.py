"""
make_agent_traces.py — dữ liệu cho VÒNG AGENTIC (nhánh đang trống hoàn toàn).

VÌ SAO CẦN
----------
`agents/agentic.py` + `Prompts.AGENT_SYSTEM` đã có, nhưng KHÔNG generator nào
sinh mẫu cho chúng — model đang chạy zero-shot, chỉ dựa vào tool-calling gốc
của Qwen3 + guided decoding ép cấu trúc. Cấu trúc đúng không có nghĩa là CHỌN
ĐÚNG TOOL và ĐIỀN ĐÚNG THAM SỐ.

DỮ LIỆU PHẢI PHẢN ÁNH ĐÚNG THỰC TẾ CHẠY
---------------------------------------
`/tools/*` là hàm THUẦN, không đọc DB (ARCHITECTURE §7). Nên trong hội thoại,
model chỉ gọi được tool khi **dữ liệu nằm ngay trong câu hỏi** — "nhà xe chào
8 triệu, biên 10%, dầu 27.000...". Sinh mẫu kiểu "quý này lãi bao nhiêu" (không
kèm số) là dạy model bịa tham số. Vì vậy mọi trace ở đây đều theo mẫu:
câu hỏi CÓ ĐỦ DỮ KIỆN -> gọi tool -> trả lời từ kết quả tool.

Kèm nhóm trace HỎI LẠI: thiếu dữ kiện bắt buộc thì phải dùng `answer` để hỏi,
KHÔNG được gọi tool với giá trị bịa (AGENT_SYSTEM quy tắc 2).

MỖI TRACE -> HAI MẪU TRAIN
--------------------------
train_v3.py tính loss trên message CUỐI. Một trace 2 bước mà để nguyên thì chỉ
dạy được bước trả lời, còn bước CHỌN TOOL (quan trọng hơn) bị che. Tách làm hai:
  A) [system, user]                          -> quyết định gọi tool
  B) [system, user, quyết_định, kết_quả]     -> quyết định trả lời

CHẠY (cần DEEPSEEK_API_KEY):
  python offline_training/make_agent_traces.py --n 140
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import (
    GENERATED_DIR,
    append_jsonl,
    done_ids,
    get_async_client,
    narration_numbers_ok,
    numbers_in,
)
from src.agents.agentic import render_tools
from src.core.prompts import Prompts

MODEL = "deepseek-chat"
CONCURRENT = 4
EVAL_RATIO = 0.12
ASK_BACK_RATIO = 0.22      # tỷ lệ trace thiếu dữ kiện -> phải hỏi lại

_ROUTES = [
    ("Hữu Nghị", "Hải Phòng"), ("KCN Quế Võ", "Hà Nội"),
    ("cảng Đình Vũ", "Bắc Giang"), ("Nội Bài", "Lạng Sơn"),
    ("KCN Yên Phong", "Đà Nẵng"), ("kho Long Biên", "Nam Định"),
]
_VEHICLES = ["1.5T", "3T", "5T", "dau_keo"]
_CARRIERS = ["Vận tải Minh Long", "Nhà xe Hòa Phát Trans", "Vận tải Sông Hồng",
             "Nhà xe Đại An", "Vận tải Tân Cảng Bắc", "Nhà xe Trường Thịnh"]


# ---------------------------------------------------------------------------
# Dựng tham số tool — TẤT ĐỊNH, hợp lệ theo schema thật
# ---------------------------------------------------------------------------

def _scenario_quote(rng):
    cost = rng.randrange(40, 300) * 50_000
    margin = rng.choice([8, 10, 12, 15])
    baseline = rng.choice([23_000, 25_000, 26_500])
    current = baseline + rng.choice([-1_500, 0, 1_000, 2_000, 3_000])
    origin, dest = rng.choice(_ROUTES)
    args = {
        "carrier_cost": cost,
        "pricing_rule": {"base_margin_pct": margin, "fuel_sensitivity": 0.35,
                         "fuel_baseline_price": baseline},
        "current_fuel_price": current,
    }
    facts = [
        f"nhà xe chào {cost:,} đồng cho chuyến {origin} đi {dest}".replace(",", "."),
        f"biên lợi nhuận {margin}%",
        f"giá dầu hiện tại {current:,} đồng/lít".replace(",", "."),
        f"giá dầu lúc nhà xe chốt bảng giá là {baseline:,} đồng/lít".replace(",", "."),
    ]
    # Giấu giá nhà xe -> không có carrier_cost thì compute_quote không chạy được
    return "quote", args, facts, [0], "giá nhà xe chào"


def _scenario_vat(rng):
    items, total = [], 0.0
    for i in range(rng.randrange(2, 4)):
        price = rng.randrange(2, 40) * 50_000
        qty = rng.randrange(1, 5)
        items.append({"name": f"Mặt hàng {chr(65 + i)}", "price": price, "qty": qty})
        total += price * qty
    stated = round(total * 1.08)
    args = {"items": items, "stated_total": stated, "default_is_reduced": True}
    facts = [
        "hoá đơn gồm " + "; ".join(
            f"{it['name']} {it['qty']} cái giá {it['price']:,} đồng".replace(",", ".")
            for it in items
        ),
        f"tổng ghi trên hoá đơn là {stated:,} đồng".replace(",", "."),
        "thuế suất áp dụng là mức giảm 8%",
    ]
    # Giấu cả danh sách mặt hàng lẫn tổng tiền -> không còn gì để đối chiếu
    return "vat", args, facts, [0, 1], "danh sách mặt hàng và tổng tiền hoá đơn"


def _scenario_carrier(rng):
    origin, dest = rng.choice(_ROUTES)
    vehicle = rng.choice(_VEHICLES)
    names = rng.sample(_CARRIERS, k=3)
    carriers, offers, lines = [], [], []
    for i, name in enumerate(names):
        price = rng.randrange(60, 260) * 50_000
        discount = rng.choice([0.0, 3.0, 5.0, 8.0])
        credit = rng.choice([15, 30, 45])
        carriers.append({"id": f"C{i + 1}", "name": name,
                         "vehicle_types": [vehicle],
                         "discount_pct": discount, "credit_days": credit})
        offers.append({"carrier_id": f"C{i + 1}", "price": price})
        lines.append(
            f"{name} chào {price:,} đồng".replace(",", ".")
            + f", chiết khấu {discount:g}%, công nợ {credit} ngày"
        )
    args = {
        "carriers": carriers, "offers": offers,
        "request": {"origin": origin, "destination": dest, "vehicle_type": vehicle},
    }
    facts = [f"chuyến {origin} đi {dest} bằng xe {vehicle}"] + lines
    # Giấu TOÀN BỘ giá chào — giấu một hãng thì tool vẫn xếp hạng được số còn lại,
    # ca hỏi lại sẽ vô nghĩa.
    return ("carrier_selection", args, facts,
            list(range(1, len(facts))), "giá chào của các nhà xe")


def _scenario_report(rng):
    granularity = rng.choice(["quarter", "half"])
    sales, lines = [], []
    for _ in range(rng.randrange(3, 6)):
        origin, dest = rng.choice(_ROUTES)
        revenue = rng.randrange(20, 90) * 1_000_000
        cogs = int(revenue * rng.uniform(0.70, 0.88))
        month = rng.randrange(1, 13)
        sales.append({"date": f"2026-{month:02d}-15", "revenue": revenue,
                      "cogs": cogs, "product": f"{origin} → {dest}", "quantity": 1})
        lines.append(
            f"tuyến {origin} đi {dest} tháng {month}: thu {revenue:,} đồng, "
            f"trả nhà xe {cogs:,} đồng".replace(",", ".")
        )
    args = {"granularity": granularity, "sales": sales, "expenses": []}
    label = {"quarter": "theo quý", "half": "theo nửa năm"}[granularity]
    facts = [f"cần báo cáo lãi lỗ {label}"] + lines
    # Giấu toàn bộ số liệu tuyến -> chỉ còn yêu cầu suông, không tính được gì
    return ("report", args, facts,
            list(range(1, len(facts))), "số liệu doanh thu và giá vốn từng tuyến")


_BUILDERS = [_scenario_quote, _scenario_vat, _scenario_carrier, _scenario_report]


def make_scenarios(n: int, seed: int) -> list[dict]:
    """
    Mỗi kịch bản: tool + tham số hợp lệ + dữ kiện để teacher viết câu hỏi.

    Ca HỎI LẠI giấu đúng những dữ kiện khiến tool KHÔNG THỂ chạy (do builder
    chỉ định), không phải một dòng bất kỳ — giấu nhầm dòng không bắt buộc thì
    tool vẫn chạy được và mẫu dạy sai.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        tool, args, facts, hide_idx, missing_label = rng.choice(_BUILDERS)(rng)
        ask_back = rng.random() < ASK_BACK_RATIO
        hidden = [facts[j] for j in hide_idx]
        rows.append({
            "_id": f"AG{i:04d}",
            "tool": tool,
            "arguments": args,
            "facts": facts,
            "ask_back": ask_back,
            "visible_facts": [f for j, f in enumerate(facts) if j not in set(hide_idx)]
            if ask_back else facts,
            "hidden_facts": hidden if ask_back else [],
            "missing_label": missing_label if ask_back else None,
        })
    return rows


# ---------------------------------------------------------------------------
# Teacher: viết câu hỏi tự nhiên chứa đúng dữ kiện
# ---------------------------------------------------------------------------

TEACHER_SYSTEM = (
    "Bạn tạo dữ liệu huấn luyện cho trợ lý vận hành doanh nghiệp vận tải Việt "
    "Nam. Viết đúng nội dung được yêu cầu, không giải thích, không ngoặc kép "
    "bao ngoài, không markdown."
)


def build_question_prompt(row: dict) -> str:
    lines = [
        "Viết MỘT tin nhắn của chủ doanh nghiệp gửi trợ lý, nêu tự nhiên các dữ kiện sau:",
        *[f"- {f}" for f in row["visible_facts"]],
        "",
        "Yêu cầu: giữ NGUYÊN VĂN mọi con số. 1-3 câu, dưới 400 ký tự, kết thúc",
        "bằng câu hỏi nhờ trợ lý xử lý.",
    ]
    if row["ask_back"]:
        lines += [
            "",
            f"TUYỆT ĐỐI KHÔNG nhắc tới, kể cả gián tiếp: {row['missing_label']}.",
            "Người viết CHƯA có thông tin đó — tin nhắn phải thiếu nó một cách tự nhiên.",
        ]
    return "\n".join(lines)


def verify_question(question: str, row: dict) -> str | None:
    if not question or len(question) > 600:
        return "câu hỏi rỗng hoặc quá dài"
    if "{" in question:
        return "câu hỏi chứa JSON"

    # Mọi con số >= 4 chữ số trong dữ kiện HIỆN phải xuất hiện nguyên văn
    want = {n for f in row["visible_facts"] for n in numbers_in(f) if len(n) >= 4}
    got = numbers_in(question)
    missing = want - got
    if missing:
        return f"thiếu số nguyên văn: {sorted(missing)[:3]}"

    # Dữ kiện bị giấu KHÔNG được rò vào câu hỏi — nếu rò thì tool gọi được và
    # mẫu không còn dạy được kỹ năng hỏi lại.
    hidden = {n for f in row["hidden_facts"] for n in numbers_in(f) if len(n) >= 4}
    leaked = hidden & got
    if leaked:
        return f"câu hỏi làm lộ dữ kiện lẽ ra phải thiếu: {sorted(leaked)[:3]}"
    return None


def build_answer_prompt(question: str, observation: str) -> str:
    return (
        f"Chủ doanh nghiệp hỏi:\n{question}\n\n"
        f"Công cụ đã tính ra kết quả sau:\n{observation}\n\n"
        "Viết câu trả lời tiếng Việt cho chủ doanh nghiệp, tối đa 4 câu. Mọi con "
        "số phải LẤY NGUYÊN từ kết quả trên — không tự tính, không làm tròn khác "
        "đi. Nếu kết quả có 'warnings' thì nhắc lại bằng lời."
    )


def build_askback_prompt(question: str, row: dict) -> str:
    return (
        f"Chủ doanh nghiệp hỏi:\n{question}\n\n"
        f"Thiếu thông tin bắt buộc: {row['missing_label']}.\n\n"
        "Viết câu HỎI LẠI ngắn (1-2 câu, tiếng Việt) để xin đúng thông tin còn "
        "thiếu. Không đoán giá trị, không nêu con số nào chưa được cung cấp."
    )


# ---------------------------------------------------------------------------
# Dựng mẫu train — khớp từng token với AgenticLoop.run()
# ---------------------------------------------------------------------------

def agent_system() -> str:
    from src.api.routes.tools import get_tool_defs
    return Prompts.AGENT_SYSTEM.format(tools=render_tools(get_tool_defs()))


def to_train_entries(row: dict, question: str, decision1: dict,
                     observation: str | None, final: dict) -> list[dict]:
    system = agent_system()
    base = [{"role": "system", "content": system},
            {"role": "user", "content": question}]

    if observation is None:          # trace hỏi lại: chỉ một bước
        return [{
            "_id": f"{row['_id']}-ask",
            "_source": "agent_askback",
            "messages": base + [{"role": "assistant",
                                 "content": json.dumps(final, ensure_ascii=False)}],
        }]

    # A) dạy CHỌN TOOL + điền tham số
    step_a = {
        "_id": f"{row['_id']}-a",
        "_source": "agent_tool_call",
        "messages": base + [{"role": "assistant",
                             "content": json.dumps(decision1, ensure_ascii=False)}],
    }
    # B) dạy TRẢ LỜI từ kết quả tool — user turn dựng y hệt AgenticLoop
    step_b = {
        "_id": f"{row['_id']}-b",
        "_source": "agent_answer",
        "messages": base + [
            {"role": "assistant", "content": json.dumps(decision1, ensure_ascii=False)},
            {"role": "user",
             "content": f"KẾT QUẢ TOOL {row['tool']}:\n{observation}"},
            {"role": "assistant", "content": json.dumps(final, ensure_ascii=False)},
        ],
    }
    return [step_a, step_b]


# ---------------------------------------------------------------------------
# Chạy
# ---------------------------------------------------------------------------

async def _ask(client, prompt: str, max_tokens: int, temperature: float) -> str:
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": TEACHER_SYSTEM},
                  {"role": "user", "content": prompt}],
        temperature=temperature, max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip().strip('"')


async def process_eval_row(client, semaphore, row: dict, out_path: Path,
                           stats: dict) -> None:
    """
    Ca benchmark: chỉ cần CÂU HỎI + đáp án đúng.

    Đáp án đúng là tất định — không cần teacher viết câu trả lời mẫu:
      - ca thường  : phải chọn đúng `expected_tool`
      - ca hỏi lại : phải dùng `answer` để hỏi, KHÔNG được gọi tool
    """
    async with semaphore:
        for attempt in (1, 2):
            try:
                question = await _ask(client, build_question_prompt(row), 300, 1.0)
            except Exception as exc:
                print(f"  ✗ {row['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return
            reason = verify_question(question, row)
            if reason is None:
                append_jsonl(out_path, {
                    "_id": row["_id"],
                    "question": question,
                    "ask_back": row["ask_back"],
                    # `expected_tool` là thứ MODEL phải làm: ca hỏi lại thì nó
                    # KHÔNG được gọi tool nào, nên để None.
                    "expected_tool": None if row["ask_back"] else row["tool"],
                    # `tool` là ý định THẬT của câu hỏi, giữ nguyên cả ở ca hỏi
                    # lại. Bảng luật tất định phải nhận ra ý định kể cả khi thiếu
                    # dữ kiện — chính vì đã lên kế hoạch mà thiếu tham số nên
                    # model mới hỏi lại được. Thiếu trường này thì `score_planner`
                    # không có đáp án để chấm nhóm hỏi lại (thêm 06/08/2026).
                    "tool": row["tool"],
                })
                stats["ok"] += 1
                return
            if attempt == 2:
                stats["rejected"] += 1


async def process_row(client, semaphore, row: dict, out_path: Path, stats: dict) -> None:
    from src.api.routes.tools import run_tool

    async with semaphore:
        # 1) Câu hỏi tự nhiên chứa đúng dữ kiện
        question, reason = None, None
        for attempt in (1, 2):
            try:
                question = await _ask(client, build_question_prompt(row), 300, 1.0)
            except Exception as exc:
                print(f"  ✗ {row['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return
            reason = verify_question(question, row)
            if reason is None:
                break
            if attempt == 2:
                print(f"  ⚠ {row['_id']} loại (câu hỏi): {reason}")
                stats["rejected"] += 1
                return

        # 2) Thiếu dữ kiện -> phải HỎI LẠI, không gọi tool
        if row["ask_back"]:
            try:
                ask = await _ask(client, build_askback_prompt(question, row), 200, 0.7)
            except Exception as exc:
                print(f"  ✗ {row['_id']} lỗi API: {exc}")
                stats["api_fail"] += 1
                return
            if not ask or len(ask) > 400:
                stats["rejected"] += 1
                return
            final = {"thought": "Thiếu thông tin bắt buộc, phải hỏi lại thay vì đoán.",
                     "answer": ask}
            for entry in to_train_entries(row, question, {}, None, final):
                append_jsonl(out_path, entry)
            stats["ok"] += 1
            return

        # 3) Chạy TOOL THẬT -> observation
        observation = await run_tool(row["tool"], row["arguments"])
        if isinstance(observation, dict) and "error" in observation:
            print(f"  ⚠ {row['_id']} tool lỗi: {observation['error']}")
            stats["rejected"] += 1
            return
        obs_text = json.dumps(observation, ensure_ascii=False, default=str)

        # 4) Câu trả lời cuối — mọi số phải đến từ observation
        try:
            answer = await _ask(client, build_answer_prompt(question, obs_text), 500, 0.6)
        except Exception as exc:
            print(f"  ✗ {row['_id']} lỗi API: {exc}")
            stats["api_fail"] += 1
            return

        ok, bad = narration_numbers_ok(answer, obs_text)
        if not ok:
            print(f"  ⚠ {row['_id']} loại (bịa số {bad})")
            stats["rejected"] += 1
            return

        decision1 = {
            "thought": f"Câu hỏi có đủ dữ kiện, gọi {row['tool']} để tính.",
            "tool": row["tool"],
            "arguments": row["arguments"],
        }
        final = {"thought": "Đã có kết quả từ công cụ, trả lời người dùng.",
                 "answer": answer}
        for entry in to_train_entries(row, question, decision1, obs_text, final):
            append_jsonl(out_path, entry)
        stats["ok"] += 1


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=140)
    parser.add_argument("--seed", type=int, default=20260729)
    args = parser.parse_args()

    rows = make_scenarios(args.n, args.seed)
    n_eval = max(1, int(len(rows) * EVAL_RATIO))
    eval_rows, train_rows = rows[:n_eval], rows[n_eval:]

    client = get_async_client()
    semaphore = asyncio.Semaphore(CONCURRENT)

    # --- eval: chỉ cần CÂU HỎI + đáp án đúng, không cần câu trả lời mẫu ------
    eval_path = GENERATED_DIR / "eval_agent.jsonl"
    eval_todo = [r for r in eval_rows if r["_id"] not in done_ids(eval_path)]
    if eval_todo:
        stats_e = {"ok": 0, "rejected": 0, "api_fail": 0}
        await asyncio.gather(*[
            process_eval_row(client, semaphore, r, eval_path, stats_e) for r in eval_todo
        ])
        print(f"✓ {eval_path} — thêm {stats_e['ok']} ca benchmark "
              f"(loại {stats_e['rejected']}, lỗi API {stats_e['api_fail']})")

    # --- train ---------------------------------------------------------------
    out_path = GENERATED_DIR / "train_agent.jsonl"
    done = {i.rsplit("-", 1)[0] for i in done_ids(out_path)}
    todo = [r for r in train_rows if r["_id"] not in done]
    print(f"[agent] tổng {len(train_rows)} — đã có {len(done)} — cần chạy {len(todo)}")
    if not todo:
        return

    stats = {"ok": 0, "rejected": 0, "api_fail": 0}
    t0 = time.time()
    await asyncio.gather(*[
        process_row(client, semaphore, r, out_path, stats) for r in todo
    ])
    n_ask = sum(1 for r in todo if r["ask_back"])
    print(f"[agent] xong {stats['ok']} trace ({n_ask} ca hỏi lại) — "
          f"loại {stats['rejected']} — lỗi API {stats['api_fail']} — "
          f"{(time.time() - t0) / 60:.1f} phút")


if __name__ == "__main__":
    asyncio.run(main())


__all__ = ["make_scenarios", "verify_question", "to_train_entries", "agent_system"]
