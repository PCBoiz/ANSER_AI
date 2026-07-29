"""
benchmark_v3.py — BƯỚC 8 pipeline v3: cổng chặn chất lượng (thay benchmark cũ).

benchmark_integration.py cũ đo hợp đồng đã bỏ ("action": "query_db"...) và cần
server + ngrok. Bản này chạy vLLM offline NGAY TRONG Colab, đo đúng 3 việc
model làm trong kiến trúc mới:

  1. extraction — eval_extraction.jsonl (nhãn tất định từ reverse-generation):
     độ chính xác từng trường + kỷ luật null (đoán bừa trường thiếu = lỗi nặng)
  2. n8n       — eval_n8n.jsonl (5 template thật giữ lại):
     tỷ lệ workflow sinh ra qua validate_workflow()
  3. narration — eval_narration.jsonl:
     không bịa số (mọi số >=4 chữ số phải có trong context) + không lộ biên

DÙNG ĐỂ:
  - đo BASELINE model gốc trước khi tốn tiền distill:
      python offline_training/benchmark_v3.py --model Qwen/Qwen3-8B --no-gate
  - làm cổng chặn sau fine-tune (dưới ngưỡng là exit 1):
      python offline_training/benchmark_v3.py --model <AWQ_DIR>

Ngưỡng chỉnh qua env: EXTRACT_FIELD_MIN, EXTRACT_READY_MIN, N8N_VALID_MIN, NARR_MIN
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import (
    GENERATED_DIR,
    customer_leak,
    load_jsonl,
    narration_numbers_ok,
    strip_diacritics,
)
from offline_training.make_n8n_pairs import _stage_catalog_dir

REQUIRED_FIELDS = ("origin", "destination", "vehicle_type")


# ---------------------------------------------------------------------------
# Chấm điểm (thuần, test được không cần GPU)
# ---------------------------------------------------------------------------

def _norm(value) -> str | None:
    if value in (None, ""):
        return None
    return strip_diacritics(str(value)).lower().strip()


def score_extraction(rows: list[dict], outputs: list[str]) -> dict:
    """
    rows: eval_extraction.jsonl. outputs: JSON model sinh (cùng thứ tự).
    Đếm theo trường: correct / wrong / miss (có mà nói null) /
    false_fill (null mà đoán bừa — lỗi tệ nhất: phá nhánh hỏi-lại).

    Tách riêng điểm câu MỘT LƯỢT và câu NỐI TIẾP: câu nối tiếp đo đúng khả năng
    kế thừa ngữ cảnh — điểm thấp ở đây nghĩa là hội thoại nhiều lượt chưa dùng
    được, dù điểm chung có đẹp.
    """
    from src.core.schemas import QuoteExtraction

    fields = list(QuoteExtraction.model_fields)
    counts = {f: Counter() for f in fields}
    n_ready = 0
    by_kind: dict[str, list[bool]] = {"single": [], "followup": []}

    for row, raw in zip(rows, outputs):
        try:
            pred = json.loads(raw)
        except Exception:
            pred = {}
        gt = row["ground_truth"]
        ready = True
        for field in fields:
            gt_v, pred_v = _norm(gt.get(field)), _norm(pred.get(field))
            if gt_v == pred_v:
                counts[field]["correct"] += 1
            elif gt_v is None:
                counts[field]["false_fill"] += 1
            elif pred_v is None:
                counts[field]["miss"] += 1
            else:
                counts[field]["wrong"] += 1
            if field in REQUIRED_FIELDS and gt_v != pred_v:
                ready = False
        n_ready += ready
        by_kind.setdefault(row.get("kind", "single"), []).append(ready)

    n = max(len(rows), 1)
    per_field = {f: counts[f]["correct"] / n for f in fields}
    return {
        "n": len(rows),
        "per_field": per_field,
        "field_avg": sum(per_field.values()) / len(fields),
        "ready_rate": n_ready / n,
        "ready_by_kind": {
            kind: round(sum(v) / len(v), 4) for kind, v in by_kind.items() if v
        },
        "counts": {f: dict(c) for f, c in counts.items()},
    }


def score_narration(rows: list[dict], outputs: list[str]) -> dict:
    n_pass, failures = 0, []
    for row, answer in zip(rows, outputs):
        ok, bad = narration_numbers_ok(answer, row["context"])
        if not ok:
            failures.append((row["_id"], f"bịa số {bad}"))
            continue
        if row["kind"] == "customer" and (leaks := customer_leak(answer)):
            failures.append((row["_id"], f"lộ nội bộ: {leaks}"))
            continue
        n_pass += 1
    return {"n": len(rows), "pass_rate": n_pass / max(len(rows), 1), "failures": failures}


# ---------------------------------------------------------------------------
# Sinh bằng vLLM offline
# ---------------------------------------------------------------------------

def build_llm(model_path: str):
    from vllm import LLM

    quantization = "awq" if "awq" in model_path.lower() else None
    return LLM(
        model=model_path,
        quantization=quantization,
        dtype="auto",
        max_model_len=8192,
        gpu_memory_utilization=float(os.getenv("BENCH_GPU_UTIL", "0.85")),
        enforce_eager=os.getenv("BENCH_ENFORCE_EAGER", "1") == "1",
        trust_remote_code=True,
    )


def build_extraction_chat(row: dict, prompts) -> list[dict]:
    """
    Dựng hội thoại cho một ca eval — kèm lịch sử nếu là câu nối tiếp.

    Dùng ĐÚNG hai hàm mà chat.py gọi lúc serve (`format_extraction_history` +
    `format_extraction_user`), nên benchmark đo trên cùng đường đi production
    chứ không phải một biến thể gần giống (P4).
    """
    from datetime import date as _date

    today = _date.fromisoformat(row["today"])
    return [
        {"role": "system", "content": prompts.LOGISTICS_EXTRACT_SYSTEM},
        *prompts.format_extraction_history(row.get("history"), today),
        {"role": "user", "content": prompts.format_extraction_user(row["message"], today)},
    ]


def generate(llm, chats: list[list[dict]], json_schema: dict | None,
             max_tokens: int, temperature: float) -> list[str]:
    from vllm import SamplingParams

    kwargs = dict(temperature=temperature, max_tokens=max_tokens)
    if json_schema is not None:
        try:
            from vllm.sampling_params import GuidedDecodingParams
            kwargs["guided_decoding"] = GuidedDecodingParams(json=json_schema)
        except ImportError:
            print("  ⚠ vLLM không có GuidedDecodingParams — chạy KHÔNG ràng buộc "
                  "(số liệu sẽ kém hơn lúc serve thật)")
    params = SamplingParams(**kwargs)

    tokenizer = llm.get_tokenizer()
    prompts = [
        tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        for chat in chats
    ]
    outputs = llm.generate(prompts, params)
    return [o.outputs[0].text.strip() for o in outputs]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-samples", type=int, default=0, help="0 = tất cả")
    parser.add_argument("--no-gate", action="store_true",
                        help="chỉ đo, không exit 1 (dùng cho baseline)")
    parser.add_argument("--skip", nargs="*", default=[],
                        choices=["extraction", "n8n", "narration"])
    args = parser.parse_args()

    _stage_catalog_dir()          # catalog node cho validate_workflow
    from src.core.prompts import Prompts
    from src.core.schemas import QuoteExtraction
    from src.core.workflow_schema import (
        build_workflow_schema,
        reload_catalog,
        render_examples,
        render_node_catalog,
        validate_workflow,
    )
    reload_catalog()

    def cap(rows):
        return rows[:args.max_samples] if args.max_samples else rows

    llm = build_llm(args.model)
    print(f"\n{'=' * 60}\n  BENCHMARK V3 — {args.model}\n{'=' * 60}")
    gate_fail = []

    # ---- 1. extraction -----------------------------------------------------
    if "extraction" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_extraction.jsonl"))
        if rows:
            chats = [build_extraction_chat(r, Prompts) for r in rows]
            outputs = generate(llm, chats, QuoteExtraction.model_json_schema(),
                               max_tokens=256, temperature=0.0)
            result = score_extraction(rows, outputs)
            print(f"\n[extraction] n={result['n']}")
            for field, acc in result["per_field"].items():
                extra = {k: v for k, v in result["counts"][field].items() if k != "correct"}
                print(f"  {field:15s} {acc * 100:5.1f}%  {extra if extra else ''}")
            print(f"  {'TB các trường':15s} {result['field_avg'] * 100:5.1f}%")
            print(f"  {'sẵn sàng báo giá':15s} {result['ready_rate'] * 100:5.1f}%"
                  " (3 trường bắt buộc đều đúng)")
            for kind, rate in result["ready_by_kind"].items():
                label = "câu nối tiếp" if kind == "followup" else "câu một lượt"
                print(f"    {label:14s} {rate * 100:5.1f}%")

            field_min = float(os.getenv("EXTRACT_FIELD_MIN", "0.85"))
            ready_min = float(os.getenv("EXTRACT_READY_MIN", "0.80"))
            followup_min = float(os.getenv("EXTRACT_FOLLOWUP_MIN", "0.70"))
            followup_rate = result["ready_by_kind"].get("followup")
            if followup_rate is not None and followup_rate < followup_min:
                gate_fail.append(
                    f"extraction followup {followup_rate:.2f} < {followup_min} "
                    "(hội thoại nhiều lượt chưa dùng được)"
                )
            if result["field_avg"] < field_min:
                gate_fail.append(f"extraction field_avg {result['field_avg']:.2f} < {field_min}")
            if result["ready_rate"] < ready_min:
                gate_fail.append(f"extraction ready_rate {result['ready_rate']:.2f} < {ready_min}")
        else:
            print("\n[extraction] ⚠ thiếu eval_extraction.jsonl — bỏ qua")

    # ---- 2. n8n ------------------------------------------------------------
    if "n8n" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_n8n.jsonl"))
        if rows:
            system = Prompts.CODER_SYSTEM.format(
                tools=render_node_catalog(), example=render_examples()
            )
            chats = [
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"YÊU CẦU: {r['task']}\nKẾ HOẠCH: {r['plan']}"}]
                for r in rows
            ]
            outputs = generate(llm, chats, build_workflow_schema(),
                               max_tokens=2048, temperature=0.0)
            n_valid = 0
            for row, raw in zip(rows, outputs):
                try:
                    ok, why = validate_workflow(json.loads(raw))
                except Exception as exc:
                    ok, why = False, f"JSON lỗi: {exc}"
                n_valid += ok
                if not ok:
                    print(f"  ✗ {row['_id']}: {why}")
            rate = n_valid / len(rows)
            print(f"\n[n8n] hợp lệ {n_valid}/{len(rows)} ({rate * 100:.0f}%)")
            n8n_min = float(os.getenv("N8N_VALID_MIN", "0.90"))
            if rate < n8n_min:
                gate_fail.append(f"n8n valid_rate {rate:.2f} < {n8n_min}")
        else:
            print("\n[n8n] ⚠ thiếu eval_n8n.jsonl — bỏ qua")

    # ---- 3. narration ------------------------------------------------------
    if "narration" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_narration.jsonl"))
        if rows:
            chats = [
                [{"role": "system",
                  "content": Prompts.DATA_SYSTEM.format(context=r["context"])},
                 {"role": "user", "content": r["question"]}]
                for r in rows
            ]
            outputs = generate(llm, chats, None, max_tokens=400, temperature=0.2)
            result = score_narration(rows, outputs)
            print(f"\n[narration] đạt {result['pass_rate'] * 100:.0f}% (n={result['n']})")
            for _id, reason in result["failures"][:10]:
                print(f"  ✗ {_id}: {reason}")
            narr_min = float(os.getenv("NARR_MIN", "0.90"))
            if result["pass_rate"] < narr_min:
                gate_fail.append(f"narration pass_rate {result['pass_rate']:.2f} < {narr_min}")
        else:
            print("\n[narration] ⚠ thiếu eval_narration.jsonl — bỏ qua")

    # ---- Cổng chặn ---------------------------------------------------------
    print(f"\n{'=' * 60}")
    if gate_fail and not args.no_gate:
        print("❌ DƯỚI NGƯỠNG:")
        for reason in gate_fail:
            print(f"   {reason}")
        sys.exit(1)
    if gate_fail:
        print("⚠ Dưới ngưỡng (--no-gate nên không chặn):")
        for reason in gate_fail:
            print(f"   {reason}")
    else:
        print("✅ Qua mọi ngưỡng")


if __name__ == "__main__":
    main()
