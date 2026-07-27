"""
build_dataset_v3.py — BƯỚC 5 pipeline v3: gộp mọi nguồn thành train/eval cuối.

NGUỒN
-----
  generated/train_extraction.jsonl   (bước 2 — trích xuất logistics)
  generated/train_narration.jsonl    (bước 3 — diễn giải XAI)
  generated/train_n8n.jsonl          (bước 4 — sinh workflow)
  v2_sources/*.jsonl                 (5 file khôi phục từ Drive — copy vào đây)
  src/data/{distilled_reasoning_deepseek,distilled_reasoning_charts,
            final_finetune_dataset}.jsonl   (phần v2 còn sót trong repo)

KHÔNG BAO GIỜ nạp src/data/training_dataset.jsonl — đó là data Make.com,
nguồn gốc vụ loạn format (ARCHITECTURE §11.1).

LỌC (theo quyết định 27/07/2026: dataset v3 KHÔNG có <think>)
  - strip <think>...</think>, giữ phần trả lời
  - loại mẫu Make.com / action query_db (hợp đồng cũ đã bỏ)
  - mẫu workflow cũ chỉ giữ nếu qua validate_workflow() hiện hành
  - đổi system prompt cũ ("Project A...") về Prompts.GENERAL_SYSTEM (P4);
    câu trả lời dài quá chuẩn "tối đa 5-6 câu" -> đẩy sang compress_queue
  - QUÉT SECRET toàn bộ input — dính là DỪNG, không ghi file (AGENTS R2b)

CHẠY:  python offline_training/build_dataset_v3.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import GENERATED_DIR, load_jsonl
from offline_training.make_n8n_pairs import _stage_catalog_dir, wrap_as_answer
from src.core.prompts import Prompts
from src.core.workflow_schema import validate_workflow

V2_SOURCES_DIR = Path(__file__).parent / "v2_sources"
REPO_V2_FILES = [
    ROOT / "src" / "data" / "distilled_reasoning_deepseek.jsonl",
    ROOT / "src" / "data" / "distilled_reasoning_charts.jsonl",
    ROOT / "src" / "data" / "final_finetune_dataset.jsonl",
]
FORBIDDEN_INPUTS = {"training_dataset.jsonl"}     # Make.com — cấm nạp

MAX_CONSULT_CHARS = 1_400   # dài hơn là lệch hẳn chuẩn "tối đa 5-6 câu" của runtime
MAX_REPORT_CHARS = 12_000   # trần nhánh REPORT; dài hơn nữa là bài viết, không phải báo cáo
V2_MAX_SHARE = 0.55         # data cũ không được lấn át tín hiệu logistics mới

SECRET_PATTERNS = [
    re.compile(r"postgres(?:ql)?://[^\s\"'\\]+"),
    re.compile(r"npg_[A-Za-z0-9]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
]

# Mật khẩu/username hiển nhiên là ví dụ giảng dạy — URL chứa chúng KHÔNG phải
# secret (train_final.jsonl có mẫu dạy disaster-recovery với
# postgres://read_replica_user:pass@... — chặn nó là chặn oan cả file).
# Mọi thứ KHÔNG nằm trong danh sách này vẫn bị coi là secret thật.
_PLACEHOLDER_TOKENS = {
    "pass", "password", "secret", "xxx", "xxxx", "your_password",
    "user", "username", "example", "changeme", "123456", "***",
}


def _is_placeholder_pg_url(url: str) -> bool:
    m = re.match(r"postgres(?:ql)?://([^:/@]+)(?::([^@]*))?@(.*)", url)
    if not m:
        return False        # không parse được -> coi là secret cho chắc
    user, password, host = m.group(1), m.group(2) or "", m.group(3)
    if password.lower() in _PLACEHOLDER_TOKENS or not password:
        return True
    if user.lower() in _PLACEHOLDER_TOKENS:
        return True
    return host.startswith(("...", "host", "<", "example."))


def scan_secrets(text: str) -> list[str]:
    hits = []
    for pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(0)
            if value.startswith("postgres") and _is_placeholder_pg_url(value):
                continue
            hits.append(value[:24] + "…")
    return hits


def strip_think(text: str) -> str:
    """Bỏ khối <think> (dùng thẻ đóng CUỐI CÙNG — model hay lồng thẻ)."""
    last = text.rfind("</think>")
    if last == -1:
        return text.replace("<think>", "").strip()
    return text[last + len("</think>"):].strip()


def _coder_system() -> str:
    """System prompt sinh workflow ĐÚNG như coder.py dựng lúc runtime (P4)."""
    from src.core.workflow_schema import render_examples, render_node_catalog
    return Prompts.CODER_SYSTEM.format(
        tools=render_node_catalog(), example=render_examples()
    )


def extract_json(text: str):
    """
    Bóc object JSON đầu tiên cân ngoặc trong text.

    Cách cũ (bóc fence bằng regex) chết trên 151/190 mẫu module_c: đáp án thật
    có markdown fence, có chữ dẫn trước/sau, có ngoặc trong chuỗi. Ghép ngoặc
    chịu được cả ba. Không dùng để phát hiện "có JSON hay không" — chỉ để lấy.
    """
    depth, start = 0, -1
    for i, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    start = -1
    return None


def convert_v2_entry(obj: dict):
    """
    Chuyển một mẫu v2 về chuẩn v3. Trả (entry | None, lý_do).

    lý_do thuộc: ok / make_com / sql_action / workflow_invalid / workflow_ok /
    too_long / malformed
    """
    msgs = obj.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        return None, "malformed"

    blob = json.dumps(msgs, ensure_ascii=False)
    if "Make.com" in blob or '"__IMTCONN__"' in blob:
        return None, "make_com"

    user = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
    assistant = next(
        (m.get("content", "") for m in reversed(msgs) if m.get("role") == "assistant"), ""
    )
    if not user or not assistant:
        return None, "malformed"

    answer = strip_think(assistant)

    # Phân loại theo NỘI DUNG bóc được, không theo chuỗi con trong text.
    # (Bản trước bắt '"nodes"' xuất hiện ở đâu đó -> bài tư vấn kiến trúc có
    #  nhắc chữ nodes bị đẩy nhầm vào nhánh JSON rồi loại là "malformed".)
    payload = extract_json(answer) if "{" in answer else None

    if isinstance(payload, dict) and payload.get("action") == "query_db":
        return None, "sql_action"          # hợp đồng Text-to-SQL cũ đã bỏ

    # Hai hình dạng workflow gặp trong tập v2:
    #   a) envelope {action, name, payload}                   — hợp đồng chat.py
    #   b) export gốc n8n {name, nodes, connections, settings} — module_c
    # (b) là 170/190 mẫu module_c. Bản trước chỉ nhận (a) nên vứt sạch — đó là
    # data n8n ĐÚNG ĐỊNH DẠNG duy nhất còn lại của v2, không được mất.
    candidate = None
    if isinstance(payload, dict):
        if payload.get("action") == "create_workflow":
            candidate = payload
        elif isinstance(payload.get("nodes"), list):
            candidate, _why = wrap_as_answer(payload, "Quy trình")
            if candidate is None:
                return None, "workflow_invalid"

    if candidate is not None:
        ok, _why = validate_workflow(candidate)
        if not ok:
            return None, "workflow_invalid"
        # System prompt phải là bản CODER runtime — mẫu v2 dùng prompt cũ, giữ
        # nguyên là dạy model gắn hành vi vào một prompt không còn tồn tại.
        return {
            "_source": "v2_n8n",
            "messages": [
                {"role": "system", "content": _coder_system()},
                {"role": "user", "content": user},
                {"role": "assistant",
                 "content": json.dumps(candidate, ensure_ascii=False)},
            ],
        }, "workflow_ok"

    # Có JSON nhưng không phải workflow/SQL (ví dụ mẫu trả về object khác) —
    # không thuộc hợp đồng nào hiện hành.
    if isinstance(payload, dict) and answer.strip().startswith(("{", "```")):
        return None, "malformed"

    # Bài dài -> nhánh REPORT (văn dài), KHÔNG vứt.
    #
    # 436/1000 mẫu v2 dài trung bình ~5.800 ký tự vì distill từ R1. Chúng lệch
    # hợp đồng GENERAL ("tối đa 5 câu") nhưng ĐÚNG hợp đồng REPORT — nhánh sinh
    # ra chính vì chat ngắn và báo cáo dài là hai nhu cầu trái ngược không thể
    # dùng chung một cap độ dài (quyết định 27/07/2026).
    if len(answer) > MAX_CONSULT_CHARS:
        if len(answer) > MAX_REPORT_CHARS:
            return None, "too_long"        # dài quá cả nhánh báo cáo
        return {
            "_source": "v2_report",
            "messages": [
                # REPORT_SYSTEM có {context}: mẫu v2 là tư vấn từ kiến thức
                # chung, không có số liệu engine -> ghi rõ là không có, để
                # model không học thói quen bịa số khi context trống.
                {"role": "system", "content": Prompts.REPORT_SYSTEM.format(
                    context="(câu hỏi kiến thức chung — không có số liệu nội bộ)"
                )},
                {"role": "user", "content": user},
                {"role": "assistant", "content": answer},
            ],
        }, "report_ok"

    # Tư vấn thuần -> system prompt runtime hiện hành (P4)
    return {
        "_source": "v2_consult",
        "messages": [
            {"role": "system", "content": Prompts.GENERAL_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ],
    }, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval-ratio", type=float, default=0.08)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    reasons: Counter = Counter()
    merged: list[dict] = []
    secret_hits: list[tuple[str, str]] = []

    # Catalog node phải là catalog THẬT (Body + logistics) trước khi validate
    # workflow v2 — catalog dự phòng thiếu splitOut/... nên loại oan mẫu tốt.
    _stage_catalog_dir()
    from src.core.workflow_schema import reload_catalog
    reload_catalog()

    # ---- 1. Nguồn v3 (đã đúng format, chỉ quét secret + gom) ---------------
    for name in ["train_extraction.jsonl", "train_narration.jsonl", "train_n8n.jsonl"]:
        path = GENERATED_DIR / name
        rows = load_jsonl(path)
        if not rows:
            print(f"  ⚠ Thiếu {path} — chạy các bước sinh dữ liệu trước")
            continue
        for row in rows:
            hits = scan_secrets(json.dumps(row, ensure_ascii=False))
            if hits:
                secret_hits.extend((name, h) for h in hits)
            merged.append({"_source": row.get("_source", name), "messages": row["messages"]})
        print(f"  ✓ {name:28s} {len(rows):5d}")

    # ---- 2. Nguồn v2 (convert + lọc) ---------------------------------------
    drive_files = sorted(V2_SOURCES_DIR.glob("*.jsonl")) if V2_SOURCES_DIR.is_dir() else []
    if not drive_files:
        print(f"  ⚠ Chưa có {V2_SOURCES_DIR}/*.jsonl — copy 5 file từ Drive vào đây rồi chạy lại")
    v2_files = drive_files + [p for p in REPO_V2_FILES if p.exists()]

    for path in v2_files:
        if path.name in FORBIDDEN_INPUTS:
            raise SystemExit(f"{path.name} là data Make.com — cấm nạp (ARCHITECTURE §11.1)")
        n_ok = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            hits = scan_secrets(line)
            if hits:
                secret_hits.extend((path.name, h) for h in hits)
                continue
            try:
                obj = json.loads(line)
            except Exception:
                reasons["v2: dòng JSON lỗi"] += 1
                continue
            entry, reason = convert_v2_entry(obj)
            reasons[f"v2: {reason}"] += 1
            if entry is not None:
                merged.append(entry)
                n_ok += 1
        print(f"  ✓ {path.name:28s} {n_ok:5d} giữ lại")

    # ---- 3. Secret = dừng cứng (R2b) ---------------------------------------
    if secret_hits:
        print("\n❌ PHÁT HIỆN SECRET TRONG DỮ LIỆU — KHÔNG GHI FILE:")
        for fname, hit in secret_hits[:20]:
            print(f"   {fname}: {hit}")
        raise SystemExit("Gỡ secret khỏi nguồn rồi chạy lại.")

    # ---- 4. Dedup ----------------------------------------------------------
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in merged:
        user = next(m["content"] for m in entry["messages"] if m["role"] == "user")
        answer = entry["messages"][-1]["content"]
        digest = hashlib.md5((user.strip() + "||" + answer[:160]).encode()).hexdigest()
        if digest in seen:
            reasons["trùng lặp"] += 1
            continue
        seen.add(digest)
        unique.append(entry)

    # ---- 5. Data cũ không được lấn át tín hiệu mới -------------------------
    v2_entries = [e for e in unique if e["_source"].startswith("v2_")]
    v3_entries = [e for e in unique if not e["_source"].startswith("v2_")]
    max_v2 = int(V2_MAX_SHARE / (1 - V2_MAX_SHARE) * max(len(v3_entries), 1))
    if len(v2_entries) > max_v2:
        rng.shuffle(v2_entries)
        reasons["v2: downsample giữ tỷ lệ"] += len(v2_entries) - max_v2
        v2_entries = v2_entries[:max_v2]
    final = v3_entries + v2_entries
    rng.shuffle(final)

    # ---- 6. Tách eval phân tầng theo nguồn ---------------------------------
    train, eval_ = [], []
    by_source: dict[str, list[dict]] = {}
    for entry in final:
        by_source.setdefault(entry["_source"], []).append(entry)
    for source, rows in sorted(by_source.items()):
        n_eval = max(1, int(len(rows) * args.eval_ratio))
        eval_.extend(rows[:n_eval])
        train.extend(rows[n_eval:])
    rng.shuffle(train)

    # ---- 7. Ghi ------------------------------------------------------------
    for name, rows in [("train_v3.jsonl", train), ("eval_v3.jsonl", eval_)]:
        path = GENERATED_DIR / name
        with open(path, "w", encoding="utf-8") as f:
            for entry in rows:
                f.write(json.dumps({"messages": entry["messages"]}, ensure_ascii=False) + "\n")
        print(f"\n✅ {path} — {len(rows)} mẫu")

    print("\nPhân bố nguồn (train + eval):")
    for source, count in Counter(e["_source"] for e in final).most_common():
        print(f"  {source:20s} {count:5d}")
    if reasons:
        print("\nLý do loại/ghi chú:")
        for reason, count in reasons.most_common():
            print(f"  {count:5d}  {reason}")
    print("\nBước tiếp: python offline_training/train_v3.py  (Colab, GPU)")


if __name__ == "__main__":
    main()
