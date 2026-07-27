"""
make_n8n_pairs.py — BƯỚC 4 pipeline v3: data sinh workflow n8n từ template THẬT.

NGUỒN: 32 workflow của Body (data/n8n_templates/) + 4 workflow logistics viết
tay (workflows/logistics/). Đáp án là workflow ĐANG CHẠY THẬT — không phải
teacher bịa (khác hẳn module_c cũ vốn để DeepSeek tự sáng tác n8n JSON).

Mỗi cặp: user = "YÊU CẦU: ...\nKẾ HOẠCH: ..." (đúng format coder.py dựng lúc
runtime — P4), assistant = workflow đã lọc qua validate_workflow(). Node bị
chặn (code/executeCommand/ssh) thay bằng noOp giữ nguyên luồng — model chỉ
được học node được phép sinh.

CHẠY (không cần GPU/API):
  python offline_training/make_n8n_pairs.py
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import GENERATED_DIR, load_jsonl  # noqa: F401

TEMPLATE_DIRS = [ROOT / "data" / "n8n_templates", ROOT / "workflows" / "logistics"]
N_EVAL = 5           # số template giữ lại làm benchmark, không vào tập train
MAX_NODES = 12       # khớp maxItems của build_workflow_schema()
MAX_ANSWER_CHARS = 7_000   # vượt là vượt ngân sách sequence khi train


def _stage_catalog_dir() -> Path:
    """
    Gộp mọi template vào MỘT thư mục rồi trỏ N8N_TEMPLATES_DIR vào đó.

    validate_workflow() đọc catalog qua env var (một nguồn duy nhất) — muốn
    validate được workflow logistics (có node gmail/respondToWebhook không nằm
    trong 32 template Body) thì catalog phải quét được cả hai thư mục.
    """
    staging = GENERATED_DIR / "_catalog"
    staging.mkdir(parents=True, exist_ok=True)
    for src_dir in TEMPLATE_DIRS:
        if not src_dir.is_dir():
            continue
        for f in src_dir.glob("*.json"):
            shutil.copy2(f, staging / f"{src_dir.name}__{f.name}")
    os.environ["N8N_TEMPLATES_DIR"] = str(staging)
    return staging


def build_pair_from_template(path: Path, data: dict):
    """Trả (pair | None, lý_do_bỏ_qua). Import src SAU khi env đã set."""
    from src.core.workflow_schema import (
        BLOCKED_NODE_TYPES,
        _sanitize_example_node,
        validate_workflow,
    )

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None, "không có nodes"
    if len(nodes) > MAX_NODES:
        return None, f"{len(nodes)} node > {MAX_NODES} (maxItems của schema sinh)"

    cleaned = []
    for raw in nodes:
        node = _sanitize_example_node(raw)
        if node["type"] in BLOCKED_NODE_TYPES:
            node["type"] = "n8n-nodes-base.noOp"
            node["typeVersion"] = 1
            node["parameters"] = {}
        cleaned.append(node)

    answer = {
        "action": "create_workflow",
        "name": data.get("name") or path.stem,
        "payload": {"nodes": cleaned, "connections": data.get("connections", {})},
    }

    ok, why = validate_workflow(answer)
    if not ok:
        return None, f"validate_workflow: {why}"

    answer_json = json.dumps(answer, ensure_ascii=False)
    if len(answer_json) > MAX_ANSWER_CHARS:
        return None, f"đáp án {len(answer_json)} ký tự > {MAX_ANSWER_CHARS}"

    # Task + plan tất định từ chính workflow — đúng phân phối planner -> coder
    node_names = [n["name"] for n in cleaned]
    task = f"Dựng workflow n8n \"{answer['name']}\" gồm các bước: {', '.join(node_names)}."
    plan = "[PLAN]\n" + "\n".join(f"{i + 1}. {name}" for i, name in enumerate(node_names))

    return {"_id": path.stem, "task": task, "plan": plan, "answer": answer}, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()

    _stage_catalog_dir()
    from src.core.workflow_schema import (
        reload_catalog,
        render_examples,
        render_node_catalog,
    )
    reload_catalog()
    from src.core.prompts import Prompts

    # System prompt dựng đúng như coder.py lúc runtime (P4)
    system = Prompts.CODER_SYSTEM.format(
        tools=render_node_catalog(), example=render_examples()
    )

    pairs, skipped = [], []
    for src_dir in TEMPLATE_DIRS:
        if not src_dir.is_dir():
            continue
        for path in sorted(src_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                skipped.append((path.stem, f"JSON lỗi: {exc}"))
                continue
            pair, reason = build_pair_from_template(path, data)
            if pair is None:
                skipped.append((path.stem, reason))
            else:
                pairs.append(pair)

    rng = random.Random(args.seed)
    rng.shuffle(pairs)
    eval_pairs, train_pairs = pairs[:N_EVAL], pairs[N_EVAL:]

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    train_path = GENERATED_DIR / "train_n8n.jsonl"
    with open(train_path, "w", encoding="utf-8") as f:
        for p in train_pairs:
            entry = {
                "_id": p["_id"],
                "_source": "n8n",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"YÊU CẦU: {p['task']}\nKẾ HOẠCH: {p['plan']}"},
                    {"role": "assistant",
                     "content": json.dumps(p["answer"], ensure_ascii=False)},
                ],
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    eval_path = GENERATED_DIR / "eval_n8n.jsonl"
    with open(eval_path, "w", encoding="utf-8") as f:
        for p in eval_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"✓ {train_path} — {len(train_pairs)} cặp train")
    print(f"✓ {eval_path} — {len(eval_pairs)} template giữ làm benchmark")
    if skipped:
        print(f"\nBỏ qua {len(skipped)} template:")
        for stem, reason in skipped:
            print(f"  - {stem}: {reason}")


if __name__ == "__main__":
    main()
