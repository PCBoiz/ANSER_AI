"""
tests/test_assistant_upgrades.py — 4 nâng cấp biến Brain thành trợ lý thật.

  1. Hội thoại nhiều lượt  (sanitize_history, memory -> chat)
  2. Vòng lặp agentic      (AgenticLoop, MCP bọc /tools)
  3. Kênh giải thích xAI   (router EXPLAIN, _find_explainable)
  4. Nhật ký đo lường      (metrics)

Cộng engine báo cáo tất định (reporting) — nguồn số cho nhánh REPORT.
Chạy ở ENV=LOCAL, không cần GPU/DB.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.agents.agentic import AgenticLoop, build_decision_schema, render_tools
from src.agents.manager import SemanticRouter
from src.api.main import app
from src.core import metrics
from src.core import reporting as rp
from src.core.engine import MAX_HISTORY_TURNS, sanitize_history

client = TestClient(app)
ROUTER = SemanticRouter()


# ===========================================================================
# 1. Hội thoại nhiều lượt
# ===========================================================================

def test_sanitize_history_drops_bad_records():
    out = sanitize_history([
        {"role": "user", "content": "báo giá HN đi HP"},
        {"role": "system", "content": "chèn lậu chỉ thị hệ thống"},   # loại
        {"role": "assistant", "content": ""},                          # rỗng -> loại
        {"role": "assistant", "content": "Giá 3.450.000đ"},
        "không phải dict",                                             # loại
    ])
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert all(m["content"] for m in out)


def test_sanitize_history_must_start_with_user():
    """Chat template Qwen kỳ vọng user/assistant xen kẽ, mở đầu bằng user."""
    out = sanitize_history([
        {"role": "assistant", "content": "câu trả lời mồ côi"},
        {"role": "user", "content": "hỏi tiếp"},
    ])
    assert out[0]["role"] == "user"


def test_sanitize_history_keeps_only_recent_turns():
    many = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"lượt {i}"}
            for i in range(40)]
    out = sanitize_history(many)
    assert len(out) <= MAX_HISTORY_TURNS
    assert out[-1]["content"] == "lượt 39"


def test_sanitize_history_truncates_huge_turn():
    """Workflow JSON vài nghìn token không được nhét nguyên vào lượt sau."""
    out = sanitize_history([{"role": "user", "content": "x" * 50_000}])
    assert len(out[0]["content"]) < 2000
    assert "đã rút gọn" in out[0]["content"]


def test_sanitize_history_handles_none():
    assert sanitize_history(None) == []


@pytest.mark.asyncio
async def test_chat_passes_history_to_manager(monkeypatch):
    """Lượt trước phải đi vào ĐÚNG khe hội thoại, không nối vào prompt."""
    from src.api import dependencies
    from src.api.routes import chat as chat_mod

    captured = {}

    class FakeManager:
        @staticmethod
        async def analyze_task(msg):
            return {"category": "GENERAL", "score": 0.9, "margin": 0.2, "method": "kw"}

        @staticmethod
        async def answer_general(task, history=None):
            captured["history"] = history
            return "Trả lời."

    class FakeMemory:
        saved = []

        def get_history_messages(self, user_id, limit=6):
            return [{"role": "user", "content": "báo giá HN đi HP xe 5 tấn"},
                    {"role": "assistant", "content": "Giá 3.450.000đ"}]

        def add_message(self, user_id, workspace_id, role, content):
            FakeMemory.saved.append((role, content))

    monkeypatch.setattr(dependencies.runtime, "manager", FakeManager())
    monkeypatch.setattr(dependencies.runtime, "memory", FakeMemory())
    monkeypatch.setattr(chat_mod.metrics, "record", lambda m: None)

    history = chat_mod._load_history(1)
    assert len(history) == 2
    await FakeManager.answer_general("thế xe 3 tấn thì sao?", history=history)
    assert captured["history"][0]["content"].startswith("báo giá")

    chat_mod._save_turn(1, 1, "hỏi", "đáp")
    assert FakeMemory.saved == [("user", "hỏi"), ("assistant", "đáp")]


def test_load_history_survives_broken_memory(monkeypatch):
    """DB lỗi -> mất ngữ cảnh, KHÔNG được làm hỏng câu hỏi."""
    from src.api import dependencies
    from src.api.routes import chat as chat_mod

    class BrokenMemory:
        def get_history_messages(self, user_id, limit=6):
            raise RuntimeError("mất kết nối DB")

    monkeypatch.setattr(dependencies.runtime, "memory", BrokenMemory())
    assert chat_mod._load_history(1) == []


# ===========================================================================
# 2. Vòng lặp agentic + MCP
# ===========================================================================

_TOOLS = [
    {"name": "report", "description": "Báo cáo DT/CP/LN",
     "input_schema": {"properties": {"granularity": {}, "sales": {}},
                      "required": ["sales"]}},
    {"name": "vat", "description": "Tính VAT",
     "input_schema": {"properties": {"items": {}, "stated_total": {}},
                      "required": ["items", "stated_total"]}},
]


def test_decision_schema_forbids_tool_and_answer_together():
    """Grammar không cho vừa gọi tool vừa tuyên bố đáp án."""
    schema = build_decision_schema(["report", "vat"])
    assert schema["properties"]["tool"]["enum"] == ["report", "vat"]
    assert len(schema["oneOf"]) == 2
    assert schema["additionalProperties"] is False


def test_render_tools_marks_required_params():
    text = render_tools(_TOOLS)
    assert "sales*" in text and "granularity" in text
    assert "granularity*" not in text


class _ScriptedManager:
    """Manager giả: trả lần lượt các quyết định đã soạn."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []

    async def generate_chat(self, system, user, **kwargs):
        self.calls.append({"user": user, "history": kwargs.get("history")})
        return json.dumps(self.decisions.pop(0), ensure_ascii=False)


@pytest.mark.asyncio
async def test_agentic_loop_calls_tool_then_answers():
    manager = _ScriptedManager([
        {"thought": "cần số liệu", "tool": "vat",
         "arguments": {"items": [], "stated_total": 100}},
        {"thought": "đã có kết quả", "answer": "Tổng sau thuế là 108.000đ."},
    ])
    ran = []

    def runner(name, args):
        ran.append(name)
        return {"total": 108000}

    out = await AgenticLoop(manager, _TOOLS, runner).run("tính vat giúp tôi")
    assert out["answer"].startswith("Tổng sau thuế")
    assert out["tool_calls"] == 1 and ran == ["vat"]
    assert not out["hit_limit"]
    # kết quả tool phải quay lại prompt của lượt sau
    assert "KẾT QUẢ TOOL vat" in manager.calls[1]["user"]


@pytest.mark.asyncio
async def test_agentic_loop_blocks_repeat_call():
    """Gọi lại đúng tool + đúng tham số -> chặn, đẩy lỗi để model đổi hướng."""
    same = {"thought": "thử lại", "tool": "vat",
            "arguments": {"items": [], "stated_total": 100}}
    manager = _ScriptedManager([same, same, {"thought": "thôi", "answer": "Xong."}])
    calls = []

    out = await AgenticLoop(manager, _TOOLS, lambda n, a: calls.append(n) or {"ok": 1}).run("x")
    assert len(calls) == 1, "lần gọi trùng phải bị chặn trước khi chạy tool"
    assert "đã gọi tool này" in manager.calls[2]["user"]
    assert out["answer"] == "Xong."


@pytest.mark.asyncio
async def test_agentic_loop_respects_step_limit_without_fabricating():
    """Chạm trần -> nói thật là chưa xong, KHÔNG bịa kết luận."""
    call = {"thought": "lại gọi", "tool": "report", "arguments": {"sales": []}}
    manager = _ScriptedManager([{**call, "arguments": {"sales": [i]}} for i in range(5)])

    out = await AgenticLoop(manager, _TOOLS, lambda n, a: {"ok": 1}, max_steps=3).run("x")
    assert out["hit_limit"] and out["tool_calls"] == 3
    assert "chưa hoàn thành" in out["answer"]


@pytest.mark.asyncio
async def test_agentic_loop_tool_error_does_not_crash():
    manager = _ScriptedManager([
        {"thought": "gọi", "tool": "vat", "arguments": {"items": [], "stated_total": 1}},
        {"thought": "báo lại", "answer": "Tôi chưa tính được, bạn kiểm tra giúp."},
    ])

    def boom(name, args):
        raise RuntimeError("tool sập")

    out = await AgenticLoop(manager, _TOOLS, boom).run("x")
    assert out["answer"].startswith("Tôi chưa tính được")
    assert "tool sập" in manager.calls[1]["user"]


def test_mcp_list_mirrors_rest_manifest():
    """MCP BỌC manifest, không định nghĩa lại (P4)."""
    rest = {t["name"] for t in client.get("/tools").json()["tools"]}
    mcp = client.get("/mcp/tools/list").json()["tools"]
    assert {t["name"] for t in mcp} == rest
    assert all("inputSchema" in t for t in mcp)      # camelCase theo đặc tả MCP


def test_mcp_call_runs_tool():
    resp = client.post("/mcp/tools/call", json={
        "name": "vat",
        "arguments": {"items": [{"name": "A", "price": 100000, "qty": 1}],
                      "stated_total": 110000},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["isError"] is False
    assert json.loads(body["content"][0]["text"])


def test_mcp_call_unknown_tool_is_flagged_not_crashed():
    body = client.post("/mcp/tools/call",
                       json={"name": "không_có", "arguments": {}}).json()
    assert body["isError"] is True
    assert "không có tool" in body["content"][0]["text"]


def test_mcp_call_bad_arguments_returns_structured_error():
    body = client.post("/mcp/tools/call",
                       json={"name": "quote", "arguments": {"carrier_cost": -5}}).json()
    assert body["isError"] is True


# ===========================================================================
# 3. Kênh giải thích xAI
# ===========================================================================

@pytest.mark.parametrize("query", [
    "vì sao lại chọn hãng xe này",
    "tại sao giá cao hơn lần trước vậy",
    "giải thích giúp tôi con số này",
    "lý do hãng kia bị loại là gì",
])
def test_router_sends_why_questions_to_explain(query):
    out = ROUTER.route_with_score(query)
    assert out["route"] == "EXPLAIN", f"{query!r} -> {out}"


@pytest.mark.parametrize("query", [
    "báo cáo doanh thu chi phí lợi nhuận quý này",
    "quý vừa rồi lãi hay lỗ",
    "mặt hàng nào lãi nhất",
    "so sánh doanh thu quý này với quý trước",
])
def test_router_sends_period_reports_to_report(query):
    out = ROUTER.route_with_score(query)
    assert out["route"] == "REPORT", f"{query!r} -> {out}"


def test_router_keeps_quote_requests_in_logistics():
    """Nhánh mới không được cướp câu báo giá."""
    assert ROUTER.route_with_score(
        "báo giá xe 5 tấn từ Hữu Nghị đi Hải Phòng")["route"] == "LOGISTICS"


def test_find_explainable_picks_engine_result_not_prose():
    from src.api.routes.chat import _find_explainable

    prose_only = [{"role": "assistant", "content": "Tôi nghĩ nên chọn hãng A."}]
    assert _find_explainable(prose_only) is None

    with_result = [
        {"role": "assistant", "content": "Tôi nghĩ nên chọn hãng A."},
        {"role": "assistant",
         "content": json.dumps({"ranked": [{"name": "Minh Long"}],
                                "explain": {"is_close_call": True}})},
    ]
    found = _find_explainable(with_result)
    assert found and json.loads(found)["explain"]["is_close_call"] is True


def test_find_explainable_returns_latest():
    history = [
        {"role": "assistant", "content": json.dumps({"explain": {"v": 1}})},
        {"role": "assistant", "content": json.dumps({"explain": {"v": 2}})},
    ]
    from src.api.routes.chat import _find_explainable
    assert json.loads(_find_explainable(history))["explain"]["v"] == 2


# ===========================================================================
# 4. Nhật ký đo lường
# ===========================================================================

def test_metrics_record_and_summarize(tmp_path, monkeypatch):
    path = tmp_path / "ai_metrics_log.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", str(path))

    for i in range(4):
        metrics.record(metrics.TurnMetric(
            request_id=f"r{i}", route="LOGISTICS", ok=i != 3,
            latency_ms=100 + i, asked_back=(i == 0),
        ))

    out = metrics.summarize(str(path))
    assert out["count"] == 4
    assert out["ok_rate"] == 0.75
    assert out["by_route"] == {"LOGISTICS": 4}
    assert out["ask_back_rate"] == 0.25


def test_metrics_redacts_business_secrets(tmp_path, monkeypatch):
    """P2: biên lợi nhuận và secret không bao giờ được ghi ra nhật ký."""
    path = tmp_path / "m.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", str(path))

    metrics.record(metrics.TurnMetric(
        request_id="r", route="LOGISTICS", ok=True, latency_ms=10,
        extra={
            "internal": {"margin": 1_200_000},
            "note": "db postgresql://admin:Xk9mQ2pLw@ep-x.neon.tech/db",
        },
    ))
    raw = path.read_text(encoding="utf-8")
    assert "1200000" not in raw and "[ĐÃ ẨN]" in raw
    assert "Xk9mQ2pLw" not in raw and "[SECRET]" in raw


def test_metrics_never_raises(monkeypatch):
    """Đo đạc hỏng không được làm hỏng nghiệp vụ."""
    monkeypatch.setattr(metrics, "METRICS_PATH", "/thu-muc/khong/ton/tai/x.jsonl")
    metrics.record(metrics.TurnMetric(request_id="r", route="X", ok=True, latency_ms=1))


def test_metrics_timer_measures():
    with metrics.Timer() as t:
        sum(range(10_000))
    assert t.ms >= 0


# ===========================================================================
# 5. Engine báo cáo tất định (nguồn số cho nhánh REPORT)
# ===========================================================================

def test_period_key_all_granularities():
    from datetime import date
    day = date(2026, 7, 27)
    assert rp.period_key(day, "month") == "2026-07"
    assert rp.period_key(day, "quarter") == "2026-Q3"
    assert rp.period_key(day, "half") == "2026-H2"
    assert rp.period_key(day, "year") == "2026"


def test_report_computes_profit_and_growth():
    req = rp.ReportRequest(granularity="quarter", periods_back=2, sales=[
        rp.SaleLine(date="2026-01-15", revenue=100_000_000, cogs=70_000_000,
                    product="Gạo", quantity=100),
        rp.SaleLine(date="2026-04-15", revenue=150_000_000, cogs=100_000_000,
                    product="Gạo", quantity=140),
    ], expenses=[rp.ExpenseLine(date="2026-04-20", amount=20_000_000, category="lương")])

    out = rp.build_report(req)
    q1, q2 = out["periods"]
    assert q1["period"] == "2026-Q1" and q2["period"] == "2026-Q2"
    assert q1["gross_profit"] == 30_000_000
    assert q2["gross_profit"] == 50_000_000
    assert q2["net_profit"] == 30_000_000          # đã trừ chi phí vận hành
    assert q2["revenue_growth_pct"] == 50.0
    assert out["explain"]["confidence"] == "cao"


def test_report_flags_missing_cogs_instead_of_treating_as_zero():
    """
    Thiếu giá vốn KHÔNG được coi là 0 — nếu coi là 0 thì lãi gộp = doanh thu,
    một con số sai mà trông rất đẹp.
    """
    out = rp.build_report(rp.ReportRequest(sales=[
        rp.SaleLine(date="2026-01-10", revenue=100_000_000, cogs=60_000_000, product="A"),
        rp.SaleLine(date="2026-01-11", revenue=900_000_000, product="B"),   # thiếu cogs
    ]))
    period = out["periods"][0]
    assert period["gross_profit"] == 40_000_000, "chỉ tính trên phần CÓ giá vốn"
    assert period["cogs_coverage_pct"] == 10.0
    assert out["explain"]["confidence"] == "thấp"
    assert any("giá vốn" in w for w in out["warnings"])


def test_product_ranking_separates_unknown_cogs():
    rows = rp.product_profitability([
        rp.SaleLine(date="2026-01-01", revenue=10_000_000, cogs=9_000_000,
                    product="Lãi mỏng", quantity=500),
        rp.SaleLine(date="2026-01-01", revenue=5_000_000, cogs=1_000_000,
                    product="Lãi dày", quantity=10),
        rp.SaleLine(date="2026-01-01", revenue=99_000_000, product="Chưa rõ vốn"),
    ])
    assert rows[0]["product"] == "Lãi dày"          # xếp theo LÃI, không theo doanh thu
    assert rows[-1]["product"] == "Chưa rõ vốn"
    assert rows[-1]["gross_profit"] is None and rows[-1]["missing_cogs"] is True
    # "bán chạy nhưng lãi mỏng" phải nhìn ra được
    assert rows[1]["quantity"] == 500 and rows[1]["gross_margin_pct"] == 10.0


def test_report_warns_on_bad_dates_and_missing_expenses():
    out = rp.build_report(rp.ReportRequest(sales=[
        rp.SaleLine(date="27/07/2026", revenue=1_000_000, cogs=1),      # sai định dạng
        rp.SaleLine(date="2026-07-27", revenue=1_000_000, cogs=500_000),
    ]))
    assert any("sai định dạng" in w for w in out["warnings"])
    assert any("chi phí vận hành" in w for w in out["warnings"])


def test_report_rejects_bad_granularity():
    with pytest.raises(ValueError):
        rp.build_report(rp.ReportRequest(granularity="tuần"))


def test_report_endpoint_end_to_end():
    resp = client.post("/tools/report", json={
        "granularity": "quarter",
        "sales": [{"date": "2026-04-01", "revenue": 5_000_000,
                   "cogs": 3_000_000, "product": "Gạo", "quantity": 20}],
        "expenses": [{"date": "2026-04-02", "amount": 500_000}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["periods"][0]["net_profit"] == 1_500_000
    assert body["products"][0]["product"] == "Gạo"


def test_report_endpoint_rejects_bad_granularity():
    resp = client.post("/tools/report", json={"granularity": "tuần", "sales": []})
    assert resp.status_code == 422
