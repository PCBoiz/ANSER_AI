"""
tests/test_ocr_freight_route.py — POST /ocr/freight (hoá đơn cước vận tải).

Đường RIÊNG, không thay `/ocr`. Công ty vừa phân phối dầu nhớt (nhập hàng ->
hoá đơn bán lẻ) vừa làm vận tải (thuê nhà xe -> hoá đơn cước), nên cả hai lược
đồ đều cần và không được nhét chung.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.freight_invoice import FreightInvoice

client = TestClient(app)

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "hoa_don.png", "image/png")


def _post(path: str, payload=None):
    data, name, mime = payload or PNG
    return client.post(path, files={"file": (name, BytesIO(data), mime)})


@pytest.fixture
def gia_lap_vision(monkeypatch):
    """Thay VisionAgent bằng đồ giả — test đường HTTP + lớp kiểm, không test model."""
    from src.api import dependencies as deps

    class FakeVision:
        result: dict = {}

        async def extract_freight_invoice(self, path):
            return dict(self.result)

    fake = FakeVision()

    async def _ensure():
        deps.runtime.vision = fake

    monkeypatch.setattr(deps.runtime, "ensure_vision_runtime", _ensure)
    monkeypatch.setattr(deps.runtime, "vision", fake, raising=False)
    return fake


HOA_DON_DUNG = {
    "carrier_name": "Nhà xe Minh Thành",
    "invoice_date": "2026-03-14",
    "origin": "Hà Nội", "destination": "Đà Nẵng",
    "vehicle_type": "xe tải 5 tấn", "plate_number": "29H-123.45",
    "charges": [
        {"kind": "cước", "quantity": 2, "unit_price": 12_000_000},
        {"kind": "bốc xếp", "quantity": 1, "unit_price": 500_000},
    ],
    "vat_rate": 8.0, "subtotal": 24_500_000,
    "vat_amount": 1_960_000, "total": 26_460_000,
}


# ---------------------------------------------------------------------------
# Đường đi thuận
# ---------------------------------------------------------------------------

def test_hoa_don_dung_thi_khong_can_nguoi_xem_lai(gia_lap_vision):
    gia_lap_vision.result = HOA_DON_DUNG
    body = _post("/ocr/freight").json()
    assert body["success"] is True, body
    assert body["needs_manual_review"] is False
    assert body["validation"]["ok"] is True
    assert body["invoice"]["plate_number"] == "29H-123.45"


def test_giu_duoc_thong_tin_van_tai_ma_hoa_don_ban_le_khong_cho_duoc(gia_lap_vision):
    gia_lap_vision.result = HOA_DON_DUNG
    inv = _post("/ocr/freight").json()["invoice"]
    assert inv["origin"] == "Hà Nội" and inv["destination"] == "Đà Nẵng"
    assert [c["kind"] for c in inv["charges"]] == ["cước", "bốc xếp"]


# ---------------------------------------------------------------------------
# Đọc SAI phải bị bắt — lý do lớp kiểm tồn tại
# ---------------------------------------------------------------------------

def test_doc_nham_chu_so_bi_bat_va_doi_nguoi_xem_lai(gia_lap_vision):
    gia_lap_vision.result = {**HOA_DON_DUNG, "total": 2_646_000}
    body = _post("/ocr/freight").json()
    assert body["success"] is True, "đọc được nhưng số sai — không phải lỗi hệ thống"
    assert body["needs_manual_review"] is True
    assert any("Tổng cộng lệch" in i for i in body["validation"]["issues"])


def test_anh_mo_doc_ra_rong_KHONG_duoc_coi_la_hoa_don_sach(gia_lap_vision):
    """
    Đây là chỗ dễ sai nhất: đọc ra rỗng thì không phép kiểm nào thất bại, nên
    một lớp kiểm ngây thơ sẽ báo "đạt". Tờ hoá đơn khi đó đi thẳng vào sổ.
    """
    gia_lap_vision.result = {}
    body = _post("/ocr/freight").json()
    assert body["needs_manual_review"] is True
    assert body["validation"]["ok"] is False
    assert body["validation"]["checks_performed"] == []


def test_thieu_truong_bat_buoc_duoc_liet_ke(gia_lap_vision):
    gia_lap_vision.result = {**HOA_DON_DUNG, "carrier_name": None}
    body = _post("/ocr/freight").json()
    assert "carrier_name" in body["validation"]["missing_required"]


# ---------------------------------------------------------------------------
# Hỏng thì báo, không bịa
# ---------------------------------------------------------------------------

def test_vlm_bao_loi_thi_khong_tra_hoa_don(gia_lap_vision):
    gia_lap_vision.result = {"error": "Error analyzing image: OOM"}
    body = _post("/ocr/freight").json()
    assert body["success"] is False
    assert "invoice" not in body


def test_json_sai_lugc_do_bao_ro_chu_khong_no(gia_lap_vision):
    gia_lap_vision.result = {"total": "hai mươi sáu triệu"}
    body = _post("/ocr/freight").json()
    assert body["success"] is False
    assert body["error"].startswith("schema_invalid")
    assert body["raw_json"] == {"total": "hai mươi sáu triệu"}


def test_file_rong_tra_400(gia_lap_vision):
    gia_lap_vision.result = HOA_DON_DUNG
    resp = _post("/ocr/freight", (b"", "rong.png", "image/png"))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# KHÔNG được thay đường bán lẻ
# ---------------------------------------------------------------------------

def test_duong_ocr_ban_le_van_con(gia_lap_vision):
    """Công ty vẫn nhập hàng — tính năng đọc hoá đơn bán lẻ vẫn cần."""
    routes = {r.path for r in app.routes}
    assert "/ocr" in routes
    assert "/ocr/freight" in routes


def test_hai_duong_dung_hai_luoc_do_khac_nhau():
    from src.core.schemas import InvoicePayload

    ban_le = set(InvoicePayload.model_fields)
    van_tai = set(FreightInvoice.model_fields)
    assert "items" in ban_le and "items" not in van_tai
    assert {"origin", "destination", "plate_number", "charges"} <= van_tai
