"""
tests/test_body_contract.py — khoá hợp đồng API giữa Brain và Body logistics.

Body (ANSER_Logistics, Next.js) gọi Brain qua `src/server/brain.ts`. Các test
dưới đây dùng ĐÚNG hình dạng payload mà file TypeScript đó sinh ra. Đổi một
trong hai bên mà quên bên kia thì test này đỏ — thay vì phát hiện lúc chạy thật
bằng một câu trả lời cụt hoặc một con số sai.

Vì sao cần: Body dùng **UUID** cho `users.id` và `warehouses.id`, còn Brain
trước đây ép `user_id: int` trong `ChatRequest` — Body mới bị chặn thẳng ở cửa
với lỗi 422 mà không ai đoán được vì sao (30/07/2026).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import ChatRequest, resolve_identity
from src.api.main import app

client = TestClient(app)

# UUID thật do Drizzle sinh (uuid().defaultRandom()).
USER_UUID = "3f2b1c4d-5e6a-4b7c-8d9e-0a1b2c3d4e5f"
WAREHOUSE_UUID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"


# ---------------------------------------------------------------------------
# Danh tính — chỗ hai bên suýt không gặp được nhau
# ---------------------------------------------------------------------------

def test_chat_nhan_UUID_lam_dinh_danh():
    """Body logistics gửi UUID; ép int là chặn thẳng Body mới."""
    req = ChatRequest(user_id=USER_UUID, store_id=WAREHOUSE_UUID, message="xin chào")
    assert req.user_id == USER_UUID
    assert req.store_id == WAREHOUSE_UUID


def test_chat_van_nhan_so_nguyen_cua_body_ban_le():
    """Body bán lẻ (Flask) đang gửi int — không được làm gãy nó."""
    req = ChatRequest(user_id=7, store_id=1, message="xin chào")
    assert req.user_id == 7 and req.store_id == 1


def test_header_UUID_khong_con_bi_tra_400():
    req = ChatRequest(user_id=0, store_id=0, message="hi")
    assert resolve_identity(req, USER_UUID, WAREHOUSE_UUID) == (USER_UUID, WAREHOUSE_UUID)


def test_header_so_nguyen_giu_nguyen_kieu_so():
    """
    Cố ý KHÔNG ép hết về chuỗi: số 1 và chuỗi "1" là hai khoá khác nhau trong
    bảng lịch sử, ép kiểu sẽ làm mồ côi hội thoại cũ của Body bán lẻ.
    """
    req = ChatRequest(user_id=0, store_id=0, message="hi")
    assert resolve_identity(req, "7", "1") == (7, 1)


def test_thieu_mot_header_thi_lui_ve_than_request():
    req = ChatRequest(user_id=USER_UUID, store_id=WAREHOUSE_UUID, message="hi")
    assert resolve_identity(req, USER_UUID, None) == (USER_UUID, WAREHOUSE_UUID)


# ---------------------------------------------------------------------------
# /tools/report — đúng payload `collectSaleLines()` sinh ra
# ---------------------------------------------------------------------------

def _sale(date: str, revenue: int, product: str, qty: int, cogs: int | None):
    """Khớp `BrainSaleLine` trong brain.ts."""
    return {"date": date, "revenue": revenue, "product": product,
            "quantity": qty, "cogs": cogs}


def test_report_nhan_dung_hinh_dang_body_gui():
    resp = client.post("/tools/report", json={
        "granularity": "quarter",
        "periods_back": 4,
        "top_n": 10,
        "sales": [
            _sale("2026-01-15", 12_000_000, "Dầu nhớt CF-4 18L", 20, 9_000_000),
            _sale("2026-04-20", 8_000_000, "Mỡ bôi trơn L3", 10, 6_000_000),
        ],
        "expenses": [],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["explain"]["cogs_coverage_pct"] == 100.0
    assert body["explain"]["confidence"] == "cao"


def test_cogs_null_KHONG_bi_coi_la_0():
    """
    Đây là điểm quan trọng nhất của cả hợp đồng. Body trả `cogs: null` cho dòng
    chưa biết giá vốn. Nếu Brain coi null là 0 thì lãi gộp thành 100% doanh thu
    — con số sai mà nghe rất xuôi tai.
    """
    resp = client.post("/tools/report", json={
        "granularity": "quarter",
        "sales": [
            _sale("2026-01-15", 10_000_000, "Hàng có giá vốn", 10, 7_000_000),
            _sale("2026-01-20", 10_000_000, "Hàng chưa có giá vốn", 10, None),
        ],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["explain"]["cogs_coverage_pct"] == 50.0
    assert body["explain"]["confidence"] == "thấp"
    assert any("giá vốn" in w for w in body["warnings"])

    period = body["periods"][0]
    assert period["revenue"] == 20_000_000        # doanh thu tính đủ
    assert period["gross_profit"] == 3_000_000    # lãi CHỈ trên phần có giá vốn


def test_khong_co_dong_ban_nao_thi_khong_no():
    resp = client.post("/tools/report", json={"granularity": "quarter", "sales": []})
    assert resp.status_code == 200
    assert resp.json()["periods"] == []


@pytest.mark.parametrize("granularity", ["month", "quarter", "half", "year"])
def test_moi_muc_ky_body_cho_phep_deu_chay(granularity):
    resp = client.post("/tools/report", json={
        "granularity": granularity,
        "sales": [_sale("2026-03-01", 1_000_000, "X", 1, 700_000)],
    })
    assert resp.status_code == 200, resp.text


def test_granularity_sai_tra_422_chu_khong_500():
    resp = client.post("/tools/report", json={
        "granularity": "thap-ky",
        "sales": [_sale("2026-03-01", 1_000_000, "X", 1, None)],
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /tools/inventory-audit — đúng payload `BrainInventoryLine` trong brain.ts
# ---------------------------------------------------------------------------

def test_inventory_audit_nhan_dung_hinh_dang_body_gui():
    resp = client.post("/tools/inventory-audit", json={
        "warehouse": "KHO HÀNG HÓA",
        "period_start": "2026-01-01",
        "period_end": "2026-07-24",
        "lines": [{
            "code": "VT00059", "name": "Diesel CI4/SL 15W40", "unit": "Lít",
            "opening_qty": 87, "opening_value": 5_016_459,
            "in_qty": 4400, "in_value": 254_755_000,
            "out_qty": 4508, "out_value": 260_989_815,
            "closing_qty": -21, "closing_value": -1_218_356,
        }],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"]["days"] == 204
    assert "negative_stock" in {f["kind"] for f in body["findings"]}


def test_inventory_gia_tri_null_van_doc_duoc():
    """Body có thể chưa nhập giá — số lượng vẫn kiểm được, giá trị thì bỏ qua."""
    resp = client.post("/tools/inventory-audit", json={
        "lines": [{"code": "P1", "opening_qty": 10, "in_qty": 5, "out_qty": 3,
                   "closing_qty": 12}],
    })
    assert resp.status_code == 200, resp.text
    assert any("thiếu cột giá trị" in w for w in resp.json()["warnings"])


# ---------------------------------------------------------------------------
# /chat — BẤT ĐỒNG BỘ. Đây là chỗ Body suýt hỏng im lặng.
# ---------------------------------------------------------------------------

def test_chat_tra_task_id_chu_KHONG_tra_cau_tra_loi():
    """
    `/chat` trả ngay {task_id, status} rồi chạy nền; kết quả lấy ở
    /api/v1/task/{id}. Bản đầu của `askBrain()` bên Body đọc thẳng
    `response`/`answer` từ phản hồi này — hai trường đó KHÔNG TỒN TẠI, nên nó
    trả về chuỗi rỗng mà không lỗi gì và UI hiện một bong bóng chat trống.

    Test này khoá hình dạng lại: đổi `/chat` sang trả lời trực tiếp thì phải
    sửa `askBrain()` cùng lúc.
    """
    resp = client.post("/chat", json={
        "user_id": USER_UUID, "store_id": WAREHOUSE_UUID, "message": "xin chào",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "task_id" in body, "Body dựa vào task_id để biết đường hỏi kết quả"
    assert body["status"] == "processing"
    assert "answer" not in body and "response" not in body


def test_task_chua_ton_tai_tra_404():
    assert client.get("/api/v1/task/khong-co-that").status_code == 404


def test_vong_doi_task_chay_duoc_den_cuoi():
    """Đường đi thật của Body: POST /chat -> hỏi lại tới khi xong."""
    task_id = client.post("/chat", json={
        "user_id": USER_UUID, "store_id": WAREHOUSE_UUID, "message": "doanh thu quý này",
    }).json()["task_id"]

    for _ in range(40):
        state = client.get(f"/api/v1/task/{task_id}").json()
        if state["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert state["status"] in ("completed", "failed"), "task treo mãi không kết thúc"
    if state["status"] == "completed":
        # Body đọc result.answer — thiếu trường này là bong bóng chat trống.
        assert "answer" in (state.get("result") or {})


# ---------------------------------------------------------------------------
# /health — Body đọc `load` để hiện trạng thái hàng đợi
# ---------------------------------------------------------------------------

def test_health_co_du_truong_body_doc():
    body = client.get("/health").json()
    for key in ("status", "degraded", "engine_ready", "vision_ready", "load"):
        assert key in body, f"brain.ts đọc trường '{key}' nhưng /health không trả"
