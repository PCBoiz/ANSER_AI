"""
tests/test_vat_truong_la.py — BR-01, SRS chu kỳ 01.

`/tools/vat` từng khai `items: list[dict]`, nên một trường gõ sai bị đọc thành
0 và tool phát ra lời buộc tội sổ sách sai tới từng đồng. Đo ngày 24/10/2026:

| Gửi vào                       | calculated_total | Kết luận cũ                  |
|-------------------------------|------------------|------------------------------|
| price + qty                   | 5.400.000        | hợp lệ, lệch 0               |
| unit_price thay cho price     | 0                | lệch 5.400.000đ, không hợp lệ |
| tên trường tiếng Việt         | 0                | lệch 5.400.000đ, không cảnh báo |

Ba ca đầu là đúng ba dòng của bảng đó. Ca thứ hai và ba PHẢI ra 422, và tuyệt
đối không được ra 200 kèm `difference` 5,4 triệu.
"""

import pytest
from fastapi.testclient import TestClient

from src.agents.agentic import arguments_schema
from src.api.main import app
from src.api.routes.tools import get_tool_defs

client = TestClient(app)

STATED = 5_400_000  # 500.000 x 10 + 8%


def _post(items, **extra):
    return client.post("/tools/vat", json={"items": items, "stated_total": STATED, **extra})


def _truong_bi_tu_choi(resp) -> set[str]:
    """Tên các trường FastAPI nêu trong thân 422."""
    return {str(e["loc"][-1]) for e in resp.json()["detail"]}


# --- ba dòng của bảng đo 24/10 --------------------------------------------

def test_dung_truong_ra_200_lech_0():
    resp = _post([{"name": "X", "price": 500_000, "qty": 10, "is_reduced_vat": True}])
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is True
    assert body["calculated_total"] == STATED
    assert body["difference"] == 0


def test_unit_price_ra_422_khong_ra_lech_5_4_trieu():
    resp = _post([{"name": "X", "unit_price": 500_000, "qty": 10}])
    assert resp.status_code == 422, (
        f"trả {resp.status_code}: trường lạ lại bị đọc thành 0 -> lời buộc tội "
        f"lệch 5.400.000đ quay lại. Thân: {resp.text[:300]}"
    )
    assert "unit_price" in _truong_bi_tu_choi(resp)
    assert "calculated_total" not in resp.text


def test_ten_truong_tieng_viet_ra_422():
    resp = _post([{"ten": "X", "don_gia": 500_000, "so_luong": 10}])
    assert resp.status_code == 422
    bi_tu_choi = _truong_bi_tu_choi(resp)
    # Báo cả trường lạ lẫn trường bắt buộc đang thiếu: người gọi sửa một lần là xong.
    assert {"don_gia", "so_luong"} <= bi_tu_choi
    assert {"price", "qty"} <= bi_tu_choi


# --- bắt buộc, không mặc định 0 --------------------------------------------

@pytest.mark.parametrize("thieu", ["price", "qty"])
def test_thieu_truong_bat_buoc_ra_422(thieu):
    item = {"name": "X", "price": 500_000, "qty": 10}
    del item[thieu]
    resp = _post([item])
    assert resp.status_code == 422
    assert thieu in _truong_bi_tu_choi(resp)


def test_qty_le_van_hop_le():
    """Dầu nhờn bán theo lít. `int(2.5) = 2` từng tính thiếu tiền — đừng để quay lại."""
    resp = _post([{"name": "Dầu", "price": 100_000, "qty": 2.5}], stated_total=275_000)
    assert resp.status_code == 200
    assert resp.json()["calculated_total"] == 275_000


def test_bo_trong_is_reduced_vat_dung_default():
    resp = client.post("/tools/vat", json={
        "items": [{"name": "X", "price": 500_000, "qty": 10}],
        "stated_total": STATED,
        "default_is_reduced": True,
    })
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True


# --- lược đồ đi tới vòng agentic --------------------------------------------

def _vat_def():
    return next(t for t in get_tool_defs() if t["name"] == "vat")


def test_get_tools_khai_dong_hang_dong_va_bat_buoc():
    """Yêu cầu 4: lược đồ mới PHẢI hiện ở GET /tools."""
    tools = client.get("/tools").json()["tools"]
    schema = next(t for t in tools if t["name"] == "vat")["input_schema"]
    item = schema["$defs"]["VatItem"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"price", "qty"}
    assert schema["properties"]["items"]["items"] == {"$ref": "#/$defs/VatItem"}


def test_grammar_agentic_dong_luon_dong_hang():
    """`arguments_schema` mang `$defs` theo, nên grammar không sinh nổi `unit_price`."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = arguments_schema(_vat_def())
    hop_le = {"items": [{"name": "X", "price": 1, "qty": 1}], "stated_total": 1.1}
    sai = {"items": [{"name": "X", "unit_price": 1, "qty": 1}], "stated_total": 1.1}
    jsonschema.validate(hop_le, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(sai, schema)


def test_vong_agentic_va_mcp_cung_bi_chan():
    """`run_tool` validate bằng đúng model của endpoint: đường model-tự-điền cũng được vá."""
    import asyncio

    from src.api.routes.tools import run_tool

    out = asyncio.run(run_tool("vat", {
        "items": [{"name": "X", "unit_price": 500_000, "qty": 10}],
        "stated_total": STATED,
    }))
    assert out.get("error") == "tham số không hợp lệ"
    assert "unit_price" in out["detail"]
    assert "calculated_total" not in out


# --- Các ca QA tái hiện ngày 26/10 -------------------------------------------

def test_tang_ngoai_go_sai_cung_ra_422_khong_bia_lech():
    """`default_is_reduce` (thiếu chữ d) từng bị bỏ qua -> tính 10% -> "lệch 100.000đ"."""
    resp = _post([{"price": 500_000, "qty": 10}], default_is_reduce=True)
    assert resp.status_code == 422
    assert "default_is_reduce" in _truong_bi_tu_choi(resp)


@pytest.mark.parametrize("item,truong", [
    ({"price": True, "qty": 10}, "price"),            # từng ra 200, lệch 5.399.989đ
    ({"price": "500000", "qty": 10}, "price"),
    ({"price": 500_000, "qty": 10, "is_reduced_vat": "yes"}, "is_reduced_vat"),
    ({"price": 500_000, "qty": 10, "is_reduced_vat": 0}, "is_reduced_vat"),
], ids=["bool-lam-gia", "chuoi-lam-gia", "yes-lam-bool", "0-lam-bool"])
def test_khong_ep_kieu_long(item, truong):
    resp = _post([item])
    assert resp.status_code == 422, resp.text[:300]
    assert truong in _truong_bi_tu_choi(resp)


@pytest.mark.parametrize("than", [
    '{"items":[{"price":NaN,"qty":10}],"stated_total":5400000}',
    '{"items":[{"price":Infinity,"qty":10}],"stated_total":5400000}',
    '{"items":[{"price":1e308,"qty":10}],"stated_total":5400000}',
    '{"items":[{"price":500000,"qty":10}],"stated_total":Infinity}',
], ids=["nan", "inf", "tran-so", "stated-inf"])
def test_so_khong_huu_han_ra_422_khong_ra_500(than):
    resp = client.post("/tools/vat", content=than,
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 422, f"{resp.status_code}: {resp.text[:200]}"
