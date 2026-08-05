"""
tests/test_agentic_plan.py — vòng agentic khi TOOL ĐÃ ĐƯỢC CHỌN SẴN.

Điểm cần chứng minh không phải "model chọn đúng hơn" mà là "model KHÔNG CÒN
CHỌN". Ràng buộc nằm ở JSON Schema đưa vào guided decoding, nên các test dưới
đây soi thẳng schema của từng bước — đó mới là thứ có hiệu lực lúc chạy thật,
khác hẳn một dòng dặn dò trong prompt.

Kèm theo là hàng rào thứ hai: dữ liệu đầu vào của tool phải đến từ nguồn tất
định. Chốt chặn neo số liệu chỉ đối chiếu câu trả lời với kết quả tool, nên nếu
model tự nghĩ ra doanh thu rồi đưa VÀO tool thì mọi con số sau đó đều "có
nguồn" và đi lọt hết.
"""

import json

import pytest

from src.agents.agentic import (
    AgenticLoop,
    arguments_schema,
    build_answer_schema,
    build_decision_schema,
)

_TOOLS = [
    {"name": "report", "description": "báo cáo lãi lỗ",
     "input_schema": {"properties": {"sales": {}, "granularity": {}},
                      "required": ["sales"]}},
    {"name": "forecast_reorder", "description": "dự báo đặt hàng lại",
     "input_schema": {"properties": {"items": {}}, "required": ["items"]}},
    {"name": "vat", "description": "tính VAT",
     "input_schema": {"properties": {"items": {}, "stated_total": {}},
                      "required": ["items", "stated_total"]}},
]


class _GhiSchema:
    """Manager giả — giữ lại schema của TỪNG bước để soi."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.schemas = []

    async def generate_chat(self, system, user, **kwargs):
        self.schemas.append(kwargs.get("json_schema"))
        return json.dumps(self.decisions.pop(0), ensure_ascii=False)


def _enum(schema) -> list | None:
    return ((schema.get("properties") or {}).get("tool") or {}).get("enum")


# --------------------------------------------------------------------------
# Ràng buộc ở tầng sampling
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_co_ke_hoach_thi_enum_chi_con_mot_ten():
    manager = _GhiSchema([
        {"thought": "lấy số", "tool": "report", "arguments": {"sales": []}},
        {"thought": "xong", "answer": "Quý này lãi 12 triệu."},
    ])

    await AgenticLoop(
        manager, _TOOLS, lambda n, a: {"net_profit": 12_000_000},
        planner=lambda q, names: ["report"],
    ).run("quý này lãi hay lỗ")

    # Bước 1: chỉ được gọi đúng `report` — không phải "nên gọi", mà là grammar
    # không sinh nổi tên khác.
    assert _enum(manager.schemas[0]) == ["report"]


@pytest.mark.asyncio
async def test_het_ke_hoach_thi_schema_chi_con_answer():
    manager = _GhiSchema([
        {"thought": "lấy số", "tool": "report", "arguments": {"sales": []}},
        {"thought": "xong", "answer": "Quý này lãi 12 triệu."},
    ])

    await AgenticLoop(
        manager, _TOOLS, lambda n, a: {"net_profit": 12_000_000},
        planner=lambda q, names: ["report"],
    ).run("quý này lãi hay lỗ")

    assert manager.schemas[1] == build_answer_schema()
    assert "tool" not in (manager.schemas[1].get("properties") or {})


@pytest.mark.asyncio
async def test_ke_hoach_nhieu_tool_chay_dung_thu_tu():
    manager = _GhiSchema([
        {"thought": "1", "tool": "report", "arguments": {"sales": []}},
        {"thought": "2", "tool": "forecast_reorder", "arguments": {"items": []}},
        {"thought": "3", "answer": "Lãi 12 triệu, nên nhập thêm 40 thùng."},
    ])
    da_chay = []

    out = await AgenticLoop(
        manager, _TOOLS, lambda n, a: da_chay.append(n) or {"ok": 1},
        planner=lambda q, names: ["report", "forecast_reorder"],
    ).run("lãi bao nhiêu, có nên nhập thêm không")

    assert da_chay == ["report", "forecast_reorder"]
    assert _enum(manager.schemas[0]) == ["report"]
    assert _enum(manager.schemas[1]) == ["forecast_reorder"]
    assert out["tool_calls"] == 2


@pytest.mark.asyncio
async def test_khong_co_ke_hoach_thi_giu_nguyen_hanh_vi_cu():
    """Luật không khớp -> model tự chọn trong toàn danh mục, như trước."""
    manager = _GhiSchema([{"thought": "t", "answer": "Chào bạn."}])

    await AgenticLoop(manager, _TOOLS, lambda n, a: {}).run("xin chào")

    assert _enum(manager.schemas[0]) == ["report", "forecast_reorder", "vat"]


@pytest.mark.asyncio
async def test_ke_hoach_rong_cung_giu_hanh_vi_cu():
    """Có `planner` nhưng không luật nào khớp cũng phải rơi về danh mục đầy đủ."""
    manager = _GhiSchema([{"thought": "t", "answer": "Chào bạn."}])

    await AgenticLoop(
        manager, _TOOLS, lambda n, a: {}, planner=lambda q, names: [],
    ).run("xin chào")

    assert _enum(manager.schemas[0]) == ["report", "forecast_reorder", "vat"]


@pytest.mark.asyncio
async def test_van_hoi_lai_duoc_khi_thieu_tham_so():
    """
    Ép enum KHÔNG được ép model phải gọi tool bằng mọi giá. Thiếu tham số bắt
    buộc thì nó vẫn phải hỏi lại, nếu không nó sẽ điền bừa.
    """
    manager = _GhiSchema([
        {"thought": "thiếu số tiền", "answer": "Đơn hàng tổng bao nhiêu tiền ạ?"},
    ])

    out = await AgenticLoop(
        manager, _TOOLS, lambda n, a: {}, planner=lambda q, names: ["vat"],
    ).run("tính thuế giúp tôi")

    assert out["answer"].startswith("Đơn hàng tổng")
    assert out["tool_calls"] == 0
    assert "answer" in (manager.schemas[0].get("properties") or {})


# --------------------------------------------------------------------------
# Ràng buộc `arguments` — chống bịa dữ liệu RỒI CHẾT VÌ NÓ
# --------------------------------------------------------------------------

def test_bo_truong_he_thong_cap_khoi_schema():
    """
    Để `arguments` tự do thì model viết ra nguyên mảng `sales` cho `report` —
    thứ `data_provider` vứt đi ngay sau đó. Mảng dài làm JSON chạm trần token,
    cắt cụt, `_parse` trả None, vòng lặp gãy. Bắt model bịa, rồi vứt, rồi hỏng
    vì chính việc bịa đó.
    """
    tool = {"name": "report", "input_schema": {
        "type": "object",
        "properties": {"granularity": {"type": "string"}, "sales": {"type": "array"},
                       "expenses": {"type": "array"}},
        "required": ["sales"],
    }}
    s = arguments_schema(tool, ("sales", "expenses"))
    assert list(s["properties"]) == ["granularity"]
    # `sales` là bắt buộc trong schema gốc — bỏ trường thì phải bỏ cả ràng buộc,
    # nếu không grammar đòi một trường không còn tồn tại và không sinh nổi gì.
    assert "required" not in s


def test_giu_nguyen_tham_so_model_duoc_phep_dien():
    """`vat` suy được từ lời người dùng — không được cắt bớt gì."""
    tool = {"name": "vat", "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array"}, "stated_total": {"type": "number"}},
        "required": ["items", "stated_total"],
    }}
    s = arguments_schema(tool, ())
    assert set(s["properties"]) == {"items", "stated_total"}
    assert set(s["required"]) == {"items", "stated_total"}


def test_defs_duoc_nang_len_goc_tai_lieu():
    """
    `$ref: "#/$defs/X"` là con trỏ tính từ gốc TÀI LIỆU, không từ object chứa nó.
    Để `$defs` nằm trong `arguments` thì grammar đi tìm ở gốc, không thấy, và gãy
    lúc DỰNG — tức là ở phút 20 của phiên Colab, không phải lúc test.
    """
    tool = {"name": "report", "input_schema": {
        "type": "object",
        "properties": {"sales": {"items": {"$ref": "#/$defs/SaleLineIn"}}},
        "$defs": {"SaleLineIn": {"type": "object"}},
    }}
    s = build_decision_schema(["report"], arguments_schema(tool, ()))
    assert "SaleLineIn" in s["$defs"]
    assert "$defs" not in s["properties"]["arguments"]


def test_moi_tool_that_deu_dung_schema_hop_le():
    """
    Chạy trên manifest THẬT. Một `$ref` treo ở đây là vòng agentic chết hẳn trên
    GPU trong khi mọi test khác vẫn xanh.
    """
    jsonschema = pytest.importorskip("jsonschema")
    from src.api.routes.tools import get_tool_defs
    from src.core.tool_planner import system_data_fields

    for t in get_tool_defs():
        s = build_decision_schema(
            [t["name"]], arguments_schema(t, system_data_fields(t["name"]))
        )
        jsonschema.Draft202012Validator.check_schema(s)

        refs = set()
        def quet(o):
            if isinstance(o, dict):
                if "$ref" in o:
                    refs.add(o["$ref"])
                for v in o.values():
                    quet(v)
            elif isinstance(o, list):
                for v in o:
                    quet(v)
        quet(s)
        co = set(s.get("$defs") or {})
        treo = [r for r in refs
                if not r.startswith("#/$defs/") or r.split("/")[-1] not in co]
        assert not treo, f"{t['name']}: $ref treo {treo}"


@pytest.mark.asyncio
async def test_vong_lap_dung_schema_da_chan_cho_tool_can_du_lieu():
    """Nối từ đầu đến cuối: kế hoạch -> schema thu hẹp -> model không thấy `sales`."""
    manager = _GhiSchema([
        {"thought": "1", "tool": "report", "arguments": {"granularity": "quarter"}},
        {"thought": "2", "answer": "Xong."},
    ])
    tools = [{"name": "report", "description": "báo cáo", "input_schema": {
        "type": "object",
        "properties": {"granularity": {"type": "string"}, "sales": {"type": "array"}},
        "required": ["sales"],
    }}]

    await AgenticLoop(
        manager, tools, lambda n, a: {"ok": 1},
        planner=lambda q, names: ["report"],
        data_provider=lambda n, a: ({**a, "sales": [{"revenue": 1}]}, None),
    ).run("quý này lãi hay lỗ")

    arg_props = manager.schemas[0]["properties"]["arguments"]["properties"]
    assert "sales" not in arg_props, "model vẫn bị hỏi mảng dữ liệu sẽ bị vứt đi"
    assert "granularity" in arg_props


# --------------------------------------------------------------------------
# Nguồn dữ liệu tất định
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_du_lieu_he_thong_ghi_de_so_model_tu_dien():
    """
    Model điền `sales` bằng số nó tự nghĩ ra. Nguồn thật phải GHI ĐÈ, không hợp
    nhất — số bịa không được sống sót cạnh số thật.
    """
    manager = _GhiSchema([
        {"thought": "1", "tool": "report",
         "arguments": {"sales": [{"date": "2026-01-01", "revenue": 999}],
                       "granularity": "quarter"}},
        {"thought": "2", "answer": "Xong."},
    ])
    nhan_duoc = {}

    def provider(ten, args):
        return {**args, "sales": [{"date": "2026-07-01", "revenue": 5_000_000}]}, None

    def runner(ten, args):
        nhan_duoc.update(args)
        return {"revenue": 5_000_000}

    await AgenticLoop(
        manager, _TOOLS, runner,
        planner=lambda q, names: ["report"], data_provider=provider,
    ).run("quý này lãi hay lỗ")

    assert nhan_duoc["sales"] == [{"date": "2026-07-01", "revenue": 5_000_000}]
    # tham số Ý ĐỊNH của model thì giữ — nó là việc model được phép làm
    assert nhan_duoc["granularity"] == "quarter"


@pytest.mark.asyncio
async def test_thieu_nguon_du_lieu_thi_dung_han_khong_chay_tool():
    manager = _GhiSchema([
        {"thought": "1", "tool": "report", "arguments": {"sales": []}},
    ])
    da_chay = []

    out = await AgenticLoop(
        manager, _TOOLS, lambda n, a: da_chay.append(n) or {"ok": 1},
        planner=lambda q, names: ["report"],
        data_provider=lambda ten, args: (args, "Tôi chưa nối được dữ liệu bán hàng."),
    ).run("quý này lãi hay lỗ")

    assert da_chay == [], "tool KHÔNG được chạy khi chưa có dữ liệu thật"
    assert out["answer"] == "Tôi chưa nối được dữ liệu bán hàng."
    assert out["data_missing"] is True
    assert not out["hit_limit"]


@pytest.mark.asyncio
async def test_provider_va_runner_deu_chay_duoc_kieu_async():
    """`run_tool` bên routes/tools.py là async; test cũ dùng lambda đồng bộ."""
    manager = _GhiSchema([
        {"thought": "1", "tool": "vat",
         "arguments": {"items": [], "stated_total": 100}},
        {"thought": "2", "answer": "Tổng 108.000đ."},
    ])

    async def provider(ten, args):
        return args, None

    async def runner(ten, args):
        return {"total": 108_000}

    out = await AgenticLoop(
        manager, _TOOLS, runner,
        planner=lambda q, names: ["vat"], data_provider=provider,
    ).run("thuế 8% cho đơn 100 nghìn")

    assert out["tool_calls"] == 1
    assert out["observations"] == [{"tool": "vat", "result": {"total": 108_000}}]


@pytest.mark.asyncio
async def test_quan_sat_duoc_tra_ra_de_lam_du_lieu_neo():
    """
    `observations` là thứ chốt chặn neo số liệu đối chiếu. Không trả ra thì
    nhánh agentic ở /chat không có gì để kiểm, và mọi con số đi thẳng ra ngoài.
    """
    manager = _GhiSchema([
        {"thought": "1", "tool": "report", "arguments": {"sales": []}},
        {"thought": "2", "answer": "Lãi ròng 12.000.000đ."},
    ])

    out = await AgenticLoop(
        manager, _TOOLS, lambda n, a: {"net_profit": 12_000_000},
        planner=lambda q, names: ["report"],
    ).run("quý này lãi hay lỗ")

    neo = json.dumps(out["observations"], ensure_ascii=False)
    assert "12000000" in neo.replace(".", "").replace(",", "")
