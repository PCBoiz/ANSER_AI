"""
tests/test_agent_and_narration_data.py — 3 nhánh dữ liệu bổ sung trước khi train.

  1. agent traces  — vòng agentic (trước đây trống hoàn toàn)
  2. EXPLAIN       — xAI, trước đây trống
  3. REPORT        — báo cáo từ SỐ ENGINE THẬT, trước đây chỉ có kiến thức chung

Trọng tâm: tham số sinh ra phải chạy được với tool THẬT, và mẫu train phải khớp
từng token với đường đi lúc serve (P4).
"""

import asyncio
import json

import pytest

from offline_training import make_agent_traces as ag
from offline_training.make_narration_pairs import (
    _SYSTEM_BY_KIND,
    make_scenarios,
    to_train_entry,
    verify_answer,
)
from src.core.prompts import Prompts

# ===========================================================================
# 1. Agent traces
# ===========================================================================


def test_every_scenario_runs_against_real_tool():
    """
    Tham số sinh ra phải hợp lệ với tool THẬT. Sai ở đây nghĩa là trên Colab
    sẽ trả tiền API rồi mới phát hiện toàn bộ trace bị loại.
    """
    from src.api.routes.tools import run_tool

    async def run_all():
        import random
        rng = random.Random(1)
        out = []
        for build in ag._BUILDERS:
            tool, args, facts, _hide_idx, _label = build(rng)
            obs = await run_tool(tool, args)
            out.append((tool, obs, facts))
        return out

    for tool, obs, facts in asyncio.run(run_all()):
        assert isinstance(obs, dict), tool
        assert "error" not in obs, f"{tool}: {obs.get('error')}"
        assert facts, f"{tool}: không có dữ kiện cho teacher"


def test_scenarios_cover_all_tools_and_askback():
    rows = ag.make_scenarios(140, seed=20260729)
    tools = {r["tool"] for r in rows}
    assert tools == {"quote", "vat", "carrier_selection", "report"}
    ask = [r for r in rows if r["ask_back"]]
    assert 10 <= len(ask) <= 50, f"tỷ lệ hỏi lại bất thường: {len(ask)}/140"
    assert all(r["missing_label"] and r["hidden_facts"] for r in ask)


def test_hidden_facts_are_the_ones_that_break_the_tool():
    """
    Ca hỏi lại phải giấu THAM SỐ BẮT BUỘC. Giấu nhầm dòng không bắt buộc thì
    tool vẫn chạy được và mẫu dạy sai — mọi dữ kiện bị giấu đều phải chứa số
    lớn (giá / doanh thu), tức là số liệu thật chứ không phải câu dẫn.
    """
    from offline_training.dgen_common import numbers_in

    rows = ag.make_scenarios(200, seed=20260729)
    for row in [r for r in rows if r["ask_back"]]:
        big = {n for f in row["hidden_facts"] for n in numbers_in(f) if len(n) >= 4}
        assert big, f"{row['_id']} ({row['tool']}): dữ kiện giấu không có số liệu nào"
        assert row["visible_facts"], f"{row['_id']}: giấu sạch, không còn gì để hỏi"


def test_question_prompt_hides_missing_fact_for_askback():
    rows = ag.make_scenarios(140, seed=20260729)
    row = next(r for r in rows if r["ask_back"])
    prompt = ag.build_question_prompt(row)
    assert "TUYỆT ĐỐI KHÔNG nhắc tới" in prompt
    # dữ kiện bị giấu KHÔNG được liệt kê trong phần "phải nêu"
    for hidden in row["hidden_facts"]:
        assert f"- {hidden}" not in prompt


def test_verify_question_requires_numbers_verbatim():
    rows = ag.make_scenarios(140, seed=20260729)
    row = next(r for r in rows if not r["ask_back"] and r["tool"] == "quote")
    assert ag.verify_question("Anh ơi tính giúp em cái này với", row)
    good = " ".join(row["facts"])
    assert ag.verify_question(good + " tính giúp tôi?", row) is None


def test_verify_question_rejects_leaked_fact_on_askback():
    rows = ag.make_scenarios(140, seed=20260729)
    row = next(r for r in rows if r["ask_back"])

    ok = " ".join(row["visible_facts"]) + " tính giúp tôi?"
    assert ag.verify_question(ok, row) is None

    leaked = " ".join(row["facts"])          # có cả dòng lẽ ra phải giấu
    reason = ag.verify_question(leaked, row)
    assert reason and "lộ dữ kiện" in reason


def test_trace_splits_into_two_samples_matching_agentic_loop():
    """
    train_v3 tính loss trên message CUỐI -> phải tách 2 mẫu, nếu không bước
    CHỌN TOOL (quan trọng nhất) bị che hoàn toàn.
    """
    rows = ag.make_scenarios(140, seed=20260729)
    row = next(r for r in rows if not r["ask_back"])
    decision = {"thought": "gọi tool", "tool": row["tool"], "arguments": row["arguments"]}
    final = {"thought": "trả lời", "answer": "Giá chốt là 1.000.000đ."}
    entries = ag.to_train_entries(row, "câu hỏi", decision, '{"ok":1}', final)

    assert len(entries) == 2
    a, b = entries
    assert a["_source"] == "agent_tool_call"
    assert [m["role"] for m in a["messages"]] == ["system", "user", "assistant"]
    assert json.loads(a["messages"][-1]["content"])["tool"] == row["tool"]

    assert b["_source"] == "agent_answer"
    assert [m["role"] for m in b["messages"]] == [
        "system", "user", "assistant", "user", "assistant"]
    # user turn thứ hai phải dựng y hệt AgenticLoop.run()
    assert b["messages"][3]["content"].startswith(f"KẾT QUẢ TOOL {row['tool']}:")
    assert "answer" in json.loads(b["messages"][-1]["content"])


def test_askback_trace_has_no_tool_call():
    """Thiếu dữ kiện -> phải trả lời hỏi lại, TUYỆT ĐỐI không gọi tool."""
    rows = ag.make_scenarios(140, seed=20260729)
    row = next(r for r in rows if r["ask_back"])
    final = {"thought": "thiếu thông tin", "answer": "Anh cho em xin giá nhà xe chào ạ."}
    entries = ag.to_train_entries(row, "câu hỏi thiếu", {}, None, final)

    assert len(entries) == 1
    decision = json.loads(entries[0]["messages"][-1]["content"])
    assert "tool" not in decision and decision["answer"]
    assert entries[0]["_source"] == "agent_askback"


def test_preflight_recognises_every_branch_prompt():
    """
    Preflight từng có danh sách prompt viết tay RIÊNG và quên AGENT_SYSTEM ->
    143 mẫu agentic hợp lệ bị báo "prompt không tồn tại". Test này chặn việc
    thêm prompt mới mà quên khai báo.
    """
    from offline_training.preflight_check import (
        _BRANCH_PROMPTS,
        _UNKNOWN_BRANCH,
        _guess_branch,
    )

    for name in _BRANCH_PROMPTS:
        prompt = getattr(Prompts, name)
        # prompt có {context}/{tools} -> format như lúc dựng dữ liệu thật
        if "{tools}" in prompt:
            rendered = ag.agent_system() if name == "AGENT_SYSTEM" else prompt
        elif "{context}" in prompt:
            rendered = prompt.format(context="{}")
        else:
            rendered = prompt
        got = _guess_branch([{"role": "system", "content": rendered}])
        assert got != _UNKNOWN_BRANCH, f"{name} không được nhận ra"

    assert _guess_branch(
        [{"role": "system", "content": "You are Project A, a Retail Consultant."}]
    ) == _UNKNOWN_BRANCH


def test_agent_system_prompt_matches_runtime():
    """System prompt trong data phải là bản AgenticLoop dựng lúc chạy (P4)."""
    from src.agents.agentic import render_tools
    from src.api.routes.tools import get_tool_defs

    assert ag.agent_system() == Prompts.AGENT_SYSTEM.format(
        tools=render_tools(get_tool_defs())
    )
    assert "report" in ag.agent_system()      # tool mới phải có trong danh mục


# ===========================================================================
# 2 + 3. EXPLAIN và REPORT
# ===========================================================================


def test_narration_covers_explain_and_report():
    rows = make_scenarios(200, seed=20260727)
    kinds = {r["kind"] for r in rows}
    assert {"explain", "report"} <= kinds, f"thiếu nhánh: {kinds}"


def test_each_kind_uses_its_runtime_system_prompt():
    """
    Nhánh EXPLAIN phải dùng EXPLAIN_SYSTEM, REPORT dùng REPORT_SYSTEM — không
    phải DATA_SYSTEM. Dùng sai prompt = dạy hành vi gắn vào nhánh không tồn tại.
    """
    rows = make_scenarios(200, seed=20260727)
    for kind, prompt_name in _SYSTEM_BY_KIND.items():
        row = next(r for r in rows if r["kind"] == kind)
        entry = to_train_entry(row, "Câu trả lời mẫu.")
        expected = getattr(Prompts, prompt_name).format(context=row["context"])
        assert entry["messages"][0]["content"] == expected, kind
        assert entry["_source"] == f"narration_{kind}"


def test_report_context_is_real_engine_output():
    """
    Bối cảnh nhánh REPORT phải là output THẬT của reporting.build_report —
    không phải văn bản kiến thức chung (đó là lỗi của v2_report).
    """
    rows = make_scenarios(200, seed=20260727)
    row = next(r for r in rows if r["kind"] == "report")
    ctx = json.loads(row["context"])
    assert set(ctx) >= {"granularity", "periods", "products", "explain", "warnings"}
    assert ctx["periods"], "báo cáo không có kỳ nào"
    assert ctx["explain"]["confidence"] in ("cao", "trung bình", "thấp")


def test_explain_context_carries_engine_explain_block():
    rows = make_scenarios(200, seed=20260727)
    for row in [r for r in rows if r["kind"] == "explain"][:5]:
        ctx = json.loads(row["context"])
        assert "explain" in ctx or "internal" in ctx, list(ctx)


def test_report_answer_must_repeat_warnings():
    """Giấu cảnh báo của engine = biến số chưa chắc thành số chắc."""
    rows = make_scenarios(400, seed=20260727)
    row = next(
        r for r in rows
        if r["kind"] == "report" and json.loads(r["context"])["warnings"]
    )
    assert verify_answer("Kỳ này lãi tốt, tăng trưởng đều.", row)
    assert verify_answer(
        "Kỳ này có lãi. Lưu ý: một phần doanh thu chưa có giá vốn nên con số "
        "còn thay đổi.", row
    ) is None


@pytest.mark.parametrize("kind,limit_ok,limit_bad", [
    ("report", 2500, 3500),      # báo cáo được viết dài
    ("quote", 1000, 1500),       # nhánh chat vẫn phải ngắn
])
def test_length_contract_per_kind(kind, limit_ok, limit_bad):
    rows = make_scenarios(200, seed=20260727)
    row = next(r for r in rows if r["kind"] == kind)
    # dùng chữ không phải chữ số để không đụng chốt chặn "bịa số"
    assert verify_answer("a" * limit_ok, row) is None
    assert verify_answer("a" * limit_bad, row)
