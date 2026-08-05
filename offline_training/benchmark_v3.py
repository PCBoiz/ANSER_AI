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
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# TẮT TENSORFLOW — PHẢI đặt trước mọi import chạm tới transformers
# ---------------------------------------------------------------------------
# Cài vLLM kéo protobuf xuống 4.25.9 (cả cây phụ thuộc của nó cần bản đó), trong
# khi TensorFlow 2.20 có sẵn của Colab đòi >= 5.28. `transformers` thấy TF tồn
# tại là import ở mức module, và chuỗi gãy ngay:
#
#     import vllm -> vllm.config -> transformers.image_processing_auto
#       -> transformers/image_transforms.py:47   import tensorflow as tf
#         -> ImportError: cannot import name 'runtime_version' from 'google.protobuf'
#
# Ta KHÔNG dùng TensorFlow một dòng nào. `USE_TORCH=1` khiến transformers bỏ qua
# nó hẳn (nó tự ghi log "Disabling Tensorflow because USE_TORCH is set").
#
# VÌ SAO ĐẶT Ở ĐÂY chứ không chỉ trong notebook (03/08/2026): notebook phải
# import tay vào Colab, còn file này thì cell 1.2 `git clone` tự kéo về. Bản vá
# đầu tiên chỉ nằm trong notebook, nên nó không bao giờ tới được máy người dùng
# — họ chạy lại và gặp đúng lỗi cũ, không có gì cho thấy vì sao.
#
# `setdefault` chứ không gán đè: ai cố tình đặt USE_TF=1 thì tôn trọng.
os.environ.setdefault("USE_TORCH", "1")
os.environ.setdefault("USE_TF", "0")

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


def parse_outputs(outputs: list[str], nhan: str) -> tuple[list[dict], dict]:
    """
    Đọc JSON model sinh ra, ĐẾM RIÊNG số lần không đọc được.

    Trước đây mỗi chỗ chấm điểm tự làm `try: json.loads / except: {}`, nên đầu ra
    HỎNG và đầu ra SAI GIÁ TRỊ trông y hệt nhau trong báo cáo: cả hai đều ra dict
    rỗng rồi thành `miss` ở mọi trường. Số cuối cùng vì thế không phân biệt được
    "model kém" với "khung đo hỏng" — mà đó là ranh giới giữa việc đi train thêm
    và việc đi sửa code (04/08/2026).

    Trả về (danh sách dict, thống kê) — thống kê có mẫu đầu ra thô để nhìn tận mắt.
    """
    parsed: list[dict] = []
    fail = 0
    mau: list[str] = []
    for raw in outputs:
        try:
            obj = json.loads(raw)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            parsed.append(obj)
        else:
            parsed.append({})
            fail += 1
            if len(mau) < 2:
                mau.append((raw or "")[:300])
    return parsed, {"nhan": nhan, "n": len(outputs), "parse_fail": fail, "mau": mau}


def in_thong_ke_parse(tk: dict) -> None:
    """In cảnh báo khi có đầu ra không đọc được. Im lặng khi mọi thứ ổn."""
    if not tk["parse_fail"]:
        return
    ty_le = tk["parse_fail"] / max(tk["n"], 1) * 100
    print(f"  ⚠ {tk['parse_fail']}/{tk['n']} ({ty_le:.0f}%) đầu ra KHÔNG đọc được thành JSON.")
    if ty_le >= 50:
        print("    Tỷ lệ này nghĩa là KHUNG ĐO đang hỏng, không phải model kém —")
        print("    mọi trường sẽ bị tính là 'miss' và điểm gần như bằng 0.")
    for i, m in enumerate(tk["mau"], 1):
        print(f"    mẫu {i}: {m!r}")



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

    preds, tk_parse = parse_outputs(outputs, "extraction")
    for row, pred in zip(rows, preds):
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
        "parse": tk_parse,
    }


def score_planner(rows: list[dict]) -> dict:
    """
    Chấm BẢNG LUẬT chọn tool — KHÔNG cần GPU, chạy được ngay trên máy thường.

    Từ 05/08/2026 tool do `core/tool_planner.py` chọn chứ không phải model, nên
    đây mới là chỗ "chọn đúng tool" được quyết định. Đo tách hẳn ra vì nó là mã
    tất định: sai thì sửa được bằng một dòng regex, không phải huấn luyện lại.

    GROUND TRUTH — chỗ này đã sai một lần, đọc kỹ.

    `eval_agent.jsonl` chỉ ghi `_id / question / ask_back / expected_tool`, KHÔNG
    có trường `tool`. Bản đầu của hàm này đọc `row["tool"]` nên mọi dòng đều ra
    None, trượt sạch, `tool_rate` = 0.0, và cổng chặn đánh trượt cả buổi đo —
    trong khi bảng luật không hề sai (bắt được 06/08/2026, trước khi kịp chạy).

    Ca HỎI LẠI có `expected_tool = None` (model không được gọi tool), nhưng bảng
    luật VẪN phải nhận ra ý định: chính vì đã lên kế hoạch mà thiếu tham số nên
    model mới hỏi lại được. Bản `eval_agent.jsonl` sinh từ 06/08 có thêm `tool`
    để chấm được cả nhóm này; file cũ trên Drive thì không, và những dòng đó bị
    BỎ QUA chứ không tính là trượt — đánh trượt vì thiếu dữ liệu chấm là đổ lỗi
    cho bảng luật vì một chuyện của bộ sinh dữ liệu.
    """
    from src.api.routes.tools import get_tool_defs
    from src.core.tool_planner import plan_tools

    names = [t["name"] for t in get_tool_defs()]
    n_ok = n_co_ke_hoach = n_cham = 0
    failures = []

    for row in rows:
        plan = plan_tools(row.get("question", ""), names)
        if plan:
            n_co_ke_hoach += 1

        mong_doi = row.get("expected_tool") or row.get("tool")
        if not mong_doi:
            continue                      # không có đáp án -> không chấm dòng này
        n_cham += 1

        if not plan:
            # Không luật nào khớp -> câu đi tiếp vào nhánh router cũ. Vẫn trả lời
            # được, nhưng không dùng tool tất định — nên tính là trượt.
            failures.append((row["_id"], f"không luật nào khớp (cần {mong_doi!r})"))
        elif mong_doi in plan:
            n_ok += 1
        else:
            failures.append((row["_id"], f"kế hoạch {plan}, đúng phải có {mong_doi!r}"))

    n = len(rows)
    return {
        "n": n,
        "n_cham": n_cham,
        "tool_rate": n_ok / n_cham if n_cham else None,
        "coverage": n_co_ke_hoach / n if n else None,
        "failures": failures,
    }


def _kiem_tham_so(ten_tool: str, args: dict) -> str | None:
    """Tham số có qua được pydantic của chính endpoint không. None = hợp lệ."""
    from src.api.routes.tools import get_tool_request_model

    model_cls = get_tool_request_model(ten_tool)
    if model_cls is None:
        return f"không có tool {ten_tool!r}"
    try:
        model_cls(**(args or {}))
        return None
    except Exception as exc:
        return str(exc).splitlines()[0][:110]


def score_agent(rows: list[dict], outputs: list[str]) -> dict:
    """
    Đo hai việc CÒN LẠI của model sau khi bảng luật đã chọn tool:

      1. biết HỎI LẠI khi thiếu dữ kiện, thay vì gọi tool với giá trị bịa
      2. điền tham số ĐÚNG KIỂU cho tool mà nó được phép điền

    Không còn đo "chọn đúng tool": enum trong grammar chỉ có một tên, model
    không sinh nổi tên khác. Giữ lại chỉ tiêu đó là tự chấm điểm cho một ràng
    buộc cú pháp, và điểm 100% ấy không nói gì về model.

    Tham số của `report`/`inventory_audit`... KHÔNG chấm: production lấy dữ liệu
    từ nguồn tất định và ghi đè, nên chấm ở đây là chấm thứ bị vứt đi.
    """
    from src.core.tool_planner import needs_system_data

    n_ask = n_ask_ok = n_goi = n_goi_ok = n_arg = n_arg_ok = 0
    failures = []
    n_cuu = 0

    decisions, tk_parse = parse_outputs(outputs, "agentic")
    for row, decision, raw in zip(rows, decisions, outputs):
        chose = decision.get("tool")
        answered = bool(decision.get("answer"))

        # JSON cắt cụt -> dict rỗng -> "chọn None". Nhưng `tool` nằm trước
        # `arguments` nên tên tool đã sinh xong; moi lại để đo ĐÚNG cái đang đo.
        if chose is None and not answered:
            cuu = tach_tool_tu_json_cut(raw)
            if cuu:
                chose = cuu
                n_cuu += 1

        if row.get("ask_back"):
            n_ask += 1
            if answered and not chose:
                n_ask_ok += 1
            else:
                failures.append((row["_id"], f"thiếu dữ kiện mà vẫn gọi tool {chose!r}"))
            continue

        n_goi += 1
        if not chose:
            failures.append((row["_id"], "không gọi tool nào dù đủ dữ kiện"))
            continue
        n_goi_ok += 1

        if needs_system_data(chose):
            continue
        n_arg += 1
        loi = _kiem_tham_so(chose, decision.get("arguments") or {})
        if loi is None:
            n_arg_ok += 1
        else:
            failures.append((row["_id"], f"tham số {chose} không hợp lệ: {loi}"))

    return {
        "n": len(rows),
        "call_rate": n_goi_ok / n_goi if n_goi else None,
        "ask_back_rate": n_ask_ok / n_ask if n_ask else None,
        "arg_fill_rate": n_arg_ok / n_arg if n_arg else None,
        "n_arg": n_arg,
        "failures": failures,
        "parse": tk_parse,
        "cuu_tu_json_cut": n_cuu,
    }


def score_narration(rows: list[dict], outputs: list[str],
                    finishes: list[str] | None = None) -> dict:
    """
    Không bịa số + không lộ biên. Tách điểm theo nhánh (quote/explain/report...).

    TÁCH RIÊNG ca bị CẮT CỤT (05/08/2026). Câu văn đứt giữa chừng thường đứt
    ngay giữa một con số, và bộ chấm thấy một chuỗi số không có trong ngữ cảnh
    thì kết luận "bịa số". Buổi đo cho ra `[carrier] bịa số 0006` — đó không
    phải một con số bịa, đó là mảnh vụn của một con số bị chặt đôi.

    Cắt cụt VẪN là lỗi (model chưa nói hết câu), nhưng là lỗi KHÁC: nó sửa bằng
    cách nới trần token, còn bịa số thì phải sửa dữ liệu huấn luyện. Gộp hai
    thứ vào một tỷ lệ là chỉ đường sai cho người đi sửa.
    """
    n_pass, failures = 0, []
    by_kind: dict[str, list[bool]] = {}
    n_cut = 0
    finishes = finishes or [""] * len(outputs)

    for row, answer, finish in zip(rows, outputs, finishes):
        kind = row.get("kind", "quote")
        bi_cut = finish == "length"
        ok, bad = narration_numbers_ok(answer, row["context"])
        passed = True
        if bi_cut:
            n_cut += 1
            failures.append((row["_id"], f"[{kind}] CẮT CỤT giữa chừng (chạm trần token)"))
            passed = False
        elif not ok:
            failures.append((row["_id"], f"[{kind}] bịa số {bad}"))
            passed = False
        elif kind == "customer" and (leaks := customer_leak(answer)):
            failures.append((row["_id"], f"[{kind}] lộ nội bộ: {leaks}"))
            passed = False
        n_pass += passed
        by_kind.setdefault(kind, []).append(passed)

    n = max(len(rows), 1)
    return {
        "n": len(rows),
        "pass_rate": n_pass / n,
        # Tỷ lệ trên phần ĐO ĐƯỢC: bỏ ca cắt cụt ra khỏi mẫu số. Đây mới là con
        # số nói về kỷ luật số liệu của model.
        "pass_rate_do_duoc": (n_pass / (n - n_cut)) if n - n_cut > 0 else None,
        "n_cat_cut": n_cut,
        "by_kind": {k: sum(v) / len(v) for k, v in by_kind.items()},
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Sinh bằng vLLM offline
# ---------------------------------------------------------------------------

def build_llm(model_path: str):
    """
    Dựng vLLM offline.

    ÉP `quantization="awq"` LÀ SAI — sửa 03/08/2026 sau khi benchmark chết ngay
    lúc khởi tạo:

        ValueError: torch.bfloat16 is not supported for quantization method awq.
                    Supported dtypes: [torch.float16]

    Hai cái sai chồng nhau. Thứ nhất, nhận dạng bằng cách dò chữ "awq" trong
    ĐƯỜNG DẪN: một thư mục tên bất kỳ có chứa "awq" là bị ép nhầm, còn model AWQ
    để ở thư mục tên khác thì không nhận ra. Thứ hai, ép tay ghi đè lựa chọn của
    vLLM — chính nó đã báo trong log:

        Detected that the model can run with awq_marlin, however you specified
        quantization=awq explicitly, so forcing awq

    `awq_marlin` vừa nhanh hơn vừa chạy được bfloat16; nhân `awq` cũ thì không,
    nên `dtype="auto"` (ra bfloat16 theo config Qwen3) đâm thẳng vào ràng buộc
    float16 rồi nổ.

    Cách đúng: ĐỂ YÊN cho vLLM đọc `quantization_config` trong config.json và tự
    chọn nhân. Nó có đủ thông tin hơn ta — biết cả compute capability của GPU
    đang chạy (awq_marlin cần Ampere trở lên, T4 thì không có).

    `BENCH_QUANT` để ép tay khi cần; ép thì phải hạ dtype xuống float16 vì nhân
    awq cũ chỉ nhận đúng kiểu đó.
    """
    from vllm import LLM

    forced = os.getenv("BENCH_QUANT", "").strip() or None
    dtype = os.getenv("BENCH_DTYPE", "").strip() or ("float16" if forced == "awq" else "auto")
    if forced:
        print(f"  ép quantization={forced}, dtype={dtype} (BENCH_QUANT)")

    return LLM(
        model=model_path,
        quantization=forced,
        dtype=dtype,
        max_model_len=8192,
        gpu_memory_utilization=float(os.getenv("BENCH_GPU_UTIL", "0.85")),
        enforce_eager=os.getenv("BENCH_ENFORCE_EAGER", "1") == "1",
        trust_remote_code=True,
    )



def smoke_test_guided(llm) -> None:
    """
    Kiem RANG BUOC GIAI MA chay duoc, TRUOC khi dot 40 phut do.

    Neu guided decoding im lang khong ap dung, moi nhanh can JSON deu ra dau ra
    khong doc duoc, moi truong thanh `miss`, va bao cao hien diem gan 0 - trong
    y het mot model do. Buoi do 04/08/2026 dung nhu the: narration (van xuoi,
    khong can JSON) dat 89%, con extraction va agentic gan nhu bang 0.

    Ba giay o day doi lay viec khong phai doan sau bon muoi phut.
    """
    schema = {
        "type": "object",
        "properties": {"ten": {"type": "string"}, "so": {"type": "integer"}},
        "required": ["ten", "so"],
    }
    raw = generate(
        llm,
        [[{"role": "user", "content": "Tra ve JSON: ten='xe tai', so=5"}]],
        schema, max_tokens=64, temperature=0.0,
    )[0][0]
    try:
        obj = json.loads(raw)
        ok = isinstance(obj, dict) and "ten" in obj and "so" in obj
    except Exception:
        ok = False

    trang_thai = "✓ CHẠY" if ok else "✗ KHÔNG CHẠY"
    print(f"\n[chốt chặn] ràng buộc JSON: {trang_thai}")
    if not ok:
        print(f"    đầu ra thô: {raw[:200]!r}")
        raise SystemExit(
            "Ràng buộc giải mã JSON KHÔNG hoạt động — đo tiếp là vô nghĩa: mọi "
            "nhánh cần JSON sẽ ra 0 và trông y hệt một model dở.\n\n"
            "Kiểm theo thứ tự:\n"
            "  1. vLLM có GuidedDecodingParams không (bản 0.8.5 thì có)\n"
            "  2. backend structured output — thử lùi về engine V0: VLLM_USE_V1=0\n"
            "  3. lược đồ có kiểu mà xgrammar chưa đỡ được không\n\n"
            "Bỏ qua chốt này: BENCH_SKIP_GUIDED_CHECK=1 (KHÔNG khuyến nghị)"
        )

    # ---- lược đồ THẬT của vòng agentic --------------------------------------
    # Lược đồ đồ chơi ở trên chỉ chứng minh guided decoding có chạy. Lược đồ
    # thật thì lồng `oneOf`, `$defs` + `$ref`, và `enum` một phần tử — xgrammar
    # đỡ những thứ đó ở mức khác hẳn. Dựng hỏng thì nó nổ lúc DỰNG grammar, tức
    # là ở phút 20 của phiên Colab chứ không phải bây giờ.
    from src.agents.agentic import arguments_schema, build_decision_schema
    from src.api.routes.tools import get_tool_defs
    from src.core.tool_planner import system_data_fields

    for t in get_tool_defs():
        ten = t["name"]
        s = build_decision_schema([ten], arguments_schema(t, system_data_fields(ten)))
        try:
            raw = generate(
                llm,
                [[{"role": "user", "content": f"Gọi tool {ten} với tham số bất kỳ."}]],
                s, max_tokens=200, temperature=0.0,
            )[0][0]
            json.loads(raw)
        except Exception as exc:
            print(f"    lược đồ {ten} HỎNG: {exc}")
            print(f"    lược đồ: {json.dumps(s, ensure_ascii=False)[:400]}")
            raise SystemExit(
                f"Lược đồ quyết định của tool {ten!r} không dựng được grammar.\n"
                "Gần như chắc chắn là `$ref` treo: `arguments_schema()` bỏ trường "
                "nhưng `$defs` phải được NÂNG LÊN GỐC của lược đồ quyết định — "
                "`#/$defs/X` là con trỏ tính từ gốc tài liệu, không từ object "
                "chứa nó.\n"
                "Chạy `pytest tests/test_agentic_plan.py -k schema` để khoanh vùng."
            ) from exc
    print(f"[chốt chặn] lược đồ agentic ({len(get_tool_defs())} tool): ✓ dựng được")



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

    # CẮT CỤT vì chạm trần token là chuyện KHÁC HẲN với sinh ra rác, nhưng cả
    # hai đều làm `json.loads` hỏng rồi thành dict rỗng. vLLM có sẵn
    # `finish_reason`, trước đây ta vứt đi — nên trả kèm để tầng chấm điểm phân
    # biệt được "model làm sai" với "model chưa nói hết câu".
    n_trunc = sum(1 for o in outputs if o.outputs[0].finish_reason == "length")
    if n_trunc:
        print(f"  ⚠ {n_trunc}/{len(outputs)} đầu ra bị CẮT CỤT vì chạm trần "
              f"{max_tokens} token.")

    return (
        [o.outputs[0].text.strip() for o in outputs],
        [o.outputs[0].finish_reason for o in outputs],
    )


def tach_tool_tu_json_cut(raw: str) -> str | None:
    """
    Moi tên tool ra khỏi JSON bị cắt cụt.

    Quyết định agentic có hình dạng {"thought": ..., "tool": ..., "arguments": …}
    — `tool` nằm TRƯỚC `arguments`, mà `arguments` mới là chỗ phình to và bị cắt.
    Nên gần như lúc nào tên tool cũng đã được sinh ra trọn vẹn trước khi chạm trần.

    Trước đây một quyết định cắt cụt bị tính thành "model chọn None", kéo tỷ lệ
    chọn tool xuống thảm. Nhưng model ĐÃ chọn — nó chỉ chưa viết xong phần tham
    số. Hai chuyện đó phải đo riêng: nới trần token từ 700 lên 2048 không đổi
    được gì (vẫn 9/19 cắt cụt) vì `arguments` nhét cả mảng dòng bán vào, dài
    không có giới hạn tự nhiên (05/08/2026).
    """
    m = re.search(r'"tool"\s*:\s*"([^"]+)"', raw or "")
    return m.group(1) if m else None


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
                        choices=["extraction", "n8n", "narration", "agent"])
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
    if os.getenv("BENCH_SKIP_GUIDED_CHECK", "") != "1":
        smoke_test_guided(llm)
    gate_fail = []

    # ---- 1. extraction -----------------------------------------------------
    if "extraction" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_extraction.jsonl"))
        if rows:
            chats = [build_extraction_chat(r, Prompts) for r in rows]
            outputs, _finish = generate(llm, chats, QuoteExtraction.model_json_schema(),
                                        max_tokens=256, temperature=0.0)
            result = score_extraction(rows, outputs)
            print(f"\n[extraction] n={result['n']}")
            in_thong_ke_parse(result["parse"])
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
                    f"extraction followup {followup_rate:.4f} < {followup_min} "
                    "(hội thoại nhiều lượt chưa dùng được)"
                )
            if result["field_avg"] < field_min:
                gate_fail.append(f"extraction field_avg {result['field_avg']:.4f} < {field_min}")
            if result["ready_rate"] < ready_min:
                gate_fail.append(f"extraction ready_rate {result['ready_rate']:.4f} < {ready_min}")
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
            outputs, _finish = generate(llm, chats, build_workflow_schema(),
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
                gate_fail.append(f"n8n valid_rate {rate:.4f} < {n8n_min}")
        else:
            print("\n[n8n] ⚠ thiếu eval_n8n.jsonl — bỏ qua")

    # ---- 3. narration ------------------------------------------------------
    if "narration" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_narration.jsonl"))
        if rows:
            # Mỗi nhánh dùng system prompt riêng — lấy từ CÙNG bảng ánh xạ mà
            # bộ sinh dữ liệu dùng (P4), không viết lại ở đây.
            from offline_training.make_narration_pairs import _SYSTEM_BY_KIND
            chats = []
            for r in rows:
                name = _SYSTEM_BY_KIND.get(r.get("kind", "quote"), "DATA_SYSTEM")
                chats.append([
                    {"role": "system",
                     "content": getattr(Prompts, name).format(context=r["context"])},
                    {"role": "user", "content": r["question"]},
                ])
            # 1100 -> 2048: ban fine-tune viet dai hon han, 7/27 cau bi cat cut
            # giua chung. Cau dut giua mot con so bi cham diem thanh "bia so"
            # (05/08/2026: "bia so 0006" thuc ra la manh vun).
            outputs, finishes = generate(
                llm, chats, None,
                max_tokens=int(os.getenv("BENCH_NARR_MAX_TOKENS", "2048")),
                temperature=0.2)
            result = score_narration(rows, outputs, finishes)
            print(f"\n[narration] đạt {result['pass_rate'] * 100:.0f}% (n={result['n']})")
            if result["n_cat_cut"]:
                print(f"    trong đó {result['n_cat_cut']} ca CẮT CỤT (chạm trần token)"
                      f" — sửa bằng nới trần, không phải bằng train lại")
                if result["pass_rate_do_duoc"] is not None:
                    print(f"    trên phần đo được: "
                          f"{result['pass_rate_do_duoc'] * 100:.0f}%")
            for kind, rate in sorted(result["by_kind"].items()):
                print(f"    {kind:10s} {rate * 100:5.1f}%")
            for _id, reason in result["failures"][:10]:
                print(f"  ✗ {_id}: {reason}")
            narr_min = float(os.getenv("NARR_MIN", "0.90"))
            if result["pass_rate"] < narr_min:
                gate_fail.append(f"narration pass_rate {result['pass_rate']:.4f} < {narr_min}")
        else:
            print("\n[narration] ⚠ thiếu eval_narration.jsonl — bỏ qua")

    # ---- 4. agentic --------------------------------------------------------
    if "agent" not in args.skip:
        rows = cap(load_jsonl(GENERATED_DIR / "eval_agent.jsonl"))
        if rows:
            from src.agents.agentic import (
                arguments_schema,
                build_decision_schema,
                render_tools,
            )
            from src.api.routes.tools import get_tool_defs
            from src.core.tool_planner import plan_tools, system_data_fields

            tool_defs = get_tool_defs()
            theo_ten = {t["name"]: t for t in tool_defs}
            names = [t["name"] for t in tool_defs]

            # ---- 4a. BẢNG LUẬT (tất định, không tốn GPU) -------------------
            kh = score_planner(rows)
            print(f"\n[bảng luật chọn tool] n={kh['n']}   — mã tất định, không có model")
            if kh["tool_rate"] is None:
                print("  ⚠ không dòng nào có đáp án để chấm — `eval_agent.jsonl` "
                      "thiếu cả `expected_tool` lẫn `tool`?")
            else:
                bo_qua = kh["n"] - kh["n_cham"]
                print(f"  chọn đúng tool  {kh['tool_rate'] * 100:5.1f}%"
                      f"   (chấm {kh['n_cham']}/{kh['n']} dòng"
                      + (f", bỏ qua {bo_qua} ca hỏi lại của bản dữ liệu cũ)"
                         if bo_qua else ")"))
            print(f"  có kế hoạch     {kh['coverage'] * 100:5.1f}%"
                  "  (không khớp luật nào -> rơi về nhánh router cũ)")
            for _id, reason in kh["failures"][:10]:
                print(f"  ✗ {_id}: {reason}")

            plan_min = float(os.getenv("PLANNER_TOOL_MIN", "0.90"))
            if kh["tool_rate"] is not None and kh["tool_rate"] < plan_min:
                gate_fail.append(
                    f"bang luat tool_rate {kh['tool_rate']:.4f} < {plan_min} "
                    "(sua regex trong tool_planner.py, khong phai huan luyen lai)")

            # ---- 4b. MODEL, chạy ĐÚNG schema như lúc serve ------------------
            # Mỗi câu một schema riêng: enum thu về đúng tool bảng luật đã chọn,
            # và `arguments` bỏ những trường production tự bơm vào. Dựng khác đi
            # là đo một đường mà khách sẽ không bao giờ đi qua.
            system = Prompts.AGENT_SYSTEM.format(tools=render_tools(tool_defs))

            # GOM THEO SCHEMA rồi mới sinh. Mỗi câu một lời gọi `generate` là bỏ
            # hết batching của vLLM — 27 câu thành 27 lượt tuần tự, đủ để một
            # phiên Colab đắt gấp mấy lần mà không đo thêm được gì.
            nhom: dict[str, list[int]] = {}
            for i, row in enumerate(rows):
                plan = plan_tools(row.get("question", ""), names)
                khoa = plan[0] if plan and plan[0] in theo_ten else ""
                nhom.setdefault(khoa, []).append(i)

            outputs: list[str] = [""] * len(rows)
            finishes: list[str] = [""] * len(rows)
            for ten, idxs in nhom.items():
                if ten:
                    schema = build_decision_schema(
                        [ten], arguments_schema(theo_ten[ten], system_data_fields(ten))
                    )
                else:
                    schema = build_decision_schema(names)
                o, f = generate(
                    llm,
                    [[{"role": "system", "content": system},
                      {"role": "user", "content": rows[i]["question"]}] for i in idxs],
                    schema,
                    max_tokens=int(os.getenv("BENCH_AGENT_MAX_TOKENS", "1024")),
                    temperature=0.0,
                )
                for vi_tri, i in enumerate(idxs):
                    outputs[i] = o[vi_tri]
                    finishes[i] = f[vi_tri]

            n_cut = sum(1 for f in finishes if f == "length")
            result = score_agent(rows, outputs)
            print(f"\n[agentic — phần của model] n={result['n']}")
            in_thong_ke_parse(result["parse"])
            if n_cut:
                print(f"  ⚠ {n_cut}/{len(finishes)} đầu ra vẫn CẮT CỤT")
            if result["cuu_tu_json_cut"]:
                print(f"    (moi lại tên tool từ {result['cuu_tu_json_cut']} JSON cắt cụt)")
            if result["ask_back_rate"] is not None:
                print(f"  biết hỏi lại    {result['ask_back_rate'] * 100:5.1f}%"
                      "  (thiếu dữ kiện thì KHÔNG được gọi tool)")
            if result["call_rate"] is not None:
                print(f"  chịu gọi tool   {result['call_rate'] * 100:5.1f}%"
                      "  (đủ dữ kiện thì phải gọi, không được trả lời chay)")
            if result["arg_fill_rate"] is not None:
                print(f"  điền tham số    {result['arg_fill_rate'] * 100:5.1f}%"
                      f"  (n={result['n_arg']}, chấm bằng pydantic của endpoint)")
            for _id, reason in result["failures"][:10]:
                print(f"  ✗ {_id}: {reason}")

            ask_min = float(os.getenv("AGENT_ASKBACK_MIN", "0.75"))
            arg_min = float(os.getenv("AGENT_ARG_MIN", "0.80"))
            if result["ask_back_rate"] is not None and result["ask_back_rate"] < ask_min:
                gate_fail.append(
                    f"agentic ask_back {result['ask_back_rate']:.4f} < {ask_min} "
                    "(goi tool voi tham so bia)")
            if result["arg_fill_rate"] is not None and result["arg_fill_rate"] < arg_min:
                gate_fail.append(
                    f"agentic arg_fill {result['arg_fill_rate']:.4f} < {arg_min}")
        else:
            print("\n[agentic] ⚠ thiếu eval_agent.jsonl — bỏ qua")

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
