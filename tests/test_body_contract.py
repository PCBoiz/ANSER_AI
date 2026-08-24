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
# Công nợ / thuế suất / đối chiếu hai kỳ — ba màn hình mới của Body
# ---------------------------------------------------------------------------

def test_partner_audit_nhan_dung_hinh_dang_body_gui():
    """Payload đúng như `auditPartners()` trong brain.ts dựng ra."""
    resp = client.post("/tools/partner-audit", json={
        "customers": [
            {"code": "KH00001", "name": "CÔNG TY CỔ PHẦN 479 HOÀ BÌNH",
             "balance": 1_129_540_864, "tax_id": "2900325124"},
            {"code": "KH00021", "name": "CÔNG TY TNHH THƯƠNG MẠI VÀ DỊCH VỤ PHƯƠNG",
             "balance": -28_962_041, "tax_id": "0106172584"},
        ],
        "suppliers": [
            {"code": "KH00021", "name": "CÔNG TY TNHH THƯƠNG MẠI VÀ DỊCH VỤ PHƯƠNG",
             "balance": 0, "tax_id": "0106172584"},
        ],
        "cogs_per_day": 35_128_650,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = {f["kind"] for f in body["findings"]}
    assert "negative_receivable" in kinds
    assert "partner_both_roles" in kinds
    assert body["summary"]["tổng_phải_thu"] == 1_129_540_864
    # Body hiển thị dòng này; mất nó là người đọc tưởng đã có phân tích tuổi nợ.
    assert body["summary"]["không_phân_tích_được"]


def test_partner_so_du_null_KHONG_bi_coi_la_0():
    """Cùng nguyên tắc với giá vốn: chưa biết khác không."""
    resp = client.post("/tools/partner-audit", json={
        "customers": [{"code": "KH1", "name": "CÔNG TY A", "tax_id": "0109527605"}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"]["tổng_phải_thu"] == 0
    assert "negative_receivable" not in {f["kind"] for f in resp.json()["findings"]}


def test_vat_catalog_nhan_dung_hinh_dang_body_gui():
    resp = client.post("/tools/vat-catalog-audit", json={
        "products": [
            {"code": "VT00001", "name": "Dầu nhớt động cơ 4 kỳ SJ-40 (0.8Lx24)",
             "vat_flag": "Chưa xác định", "group": "HH", "unit": "Lít"},
            {"code": "KM00025", "name": "Bia 333", "vat_flag": "Chưa xác định"},
        ],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["hiệu_lực_đến"] == "2026-12-31"
    assert "174/2025" in body["summary"]["căn_cứ"]
    kinds = {f["kind"] for f in body["findings"]}
    assert "vat_reduction_missed" in kinds     # dầu nhớt -> 8%
    assert "vat_rate_review" in kinds          # bia -> giữ 10%


def test_period_diff_nhan_dung_hinh_dang_body_gui():
    """Payload đúng như `comparePeriods()` dựng từ hai kết quả import."""
    def ky(out_qty, out_value, closing_qty, closing_value, den):
        return {
            "warehouse": "KHO HÀNG HÓA",
            "period_start": "2026-01-01", "period_end": den,
            "lines": [{
                "code": "VT00059", "name": "Diesel CI4/SL 15W40", "unit": "Lít",
                "opening_qty": 87, "opening_value": 5_016_459,
                "in_qty": 4400, "in_value": 254_755_000,
                "out_qty": out_qty, "out_value": out_value,
                "closing_qty": closing_qty, "closing_value": closing_value,
            }],
        }

    resp = client.post("/tools/period-diff", json={
        "truoc": ky(4508, 260_989_815, -21, -1_218_356, "2026-07-24"),
        "sau": ky(4400, 254_723_980, 87, 5_047_479, "2026-08-11"),
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == []
    assert body["summary"]["có_sửa_hồi_tố"] is True
    assert body["findings"][0]["kind"] == "history_decreased"
    assert body["findings"][0]["money_impact"] == 6_265_835


def test_period_diff_tu_choi_so_thi_bao_bang_warnings_chu_khong_500():
    """Body dựa vào `warnings` khác rỗng để hiện khối 'chưa kiểm được'."""
    mot_ky = {"lines": [{"code": "A"}], "warehouse": "KHO A",
              "period_start": "2026-01-01", "period_end": "2026-06-30"}
    khac_kho = {**mot_ky, "warehouse": "KHO B", "period_end": "2026-08-11"}
    resp = client.post("/tools/period-diff", json={"truoc": mot_ky, "sau": khac_kho})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["findings"] == []
    assert body["warnings"] and body["summary"]["so_sánh_được"] is False


def test_moi_phat_hien_deu_cung_hinh_dang_du_den_tu_tool_nao():
    """
    Body dùng MỘT component `FindingList` cho cả bốn lớp kiểm. Lệch một trường
    ở bất kỳ tool nào là màn hình đó hiện ra ô trống mà không báo lỗi gì.
    """
    truong = {"kind", "severity", "code", "product", "unit", "title",
              "evidence", "money_impact", "suggestion"}

    goi = [
        ("/tools/inventory-audit",
         {"lines": [{"code": "A", "opening_qty": 0, "in_qty": 0, "out_qty": 5,
                     "closing_qty": -5, "closing_value": -100.0,
                     "opening_value": 0.0, "in_value": 0.0, "out_value": 100.0}]}),
        ("/tools/partner-audit",
         {"customers": [{"code": "K", "name": "CÔNG TY A", "balance": -5_000,
                         "tax_id": "0109527604"}]}),
        ("/tools/vat-catalog-audit",
         {"products": [{"code": "P", "name": "Dầu nhớt động cơ",
                        "vat_flag": "Chưa xác định"}]}),
    ]
    for path, payload in goi:
        body = client.post(path, json=payload).json()
        assert body["findings"], f"{path} không trả phát hiện nào để kiểm hình dạng"
        for f in body["findings"]:
            assert set(f) == truong, f"{path} lệch trường: {set(f) ^ truong}"


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
    assert resp.status_code == 200, (
        f"/chat trả {resp.status_code}: {resp.text[:200]}\n"
        "503 ở đây nghĩa là text runtime chưa dựng được — kiểm ENV=LOCAL và "
        "phụ thuộc của ModelEngine, không phải lỗi hợp đồng với Body."
    )
    body = resp.json()
    assert "task_id" in body, "Body dựa vào task_id để biết đường hỏi kết quả"
    assert body["status"] == "processing"
    assert "answer" not in body and "response" not in body


def test_task_chua_ton_tai_tra_404():
    assert client.get("/api/v1/task/khong-co-that").status_code == 404


def test_vong_doi_task_chay_duoc_den_cuoi():
    """
    Đường đi thật của Body: POST /chat -> hỏi lại tới khi xong.

    Gửi `X-User-Id` ở CẢ HAI lượt, đúng như `askBrain()` bên Body làm (nó truyền
    `identity` cho cả POST lẫn GET). Từ 15/08/2026 `/api/v1/task/{id}` chỉ trả
    kết quả cho chủ của task — nội dung nó trả về là câu trả lời đầy đủ của AI,
    tức là tên khách, mã số thuế, số công nợ, nên một token chung không đủ tách
    hai kế toán của cùng một doanh nghiệp.
    """
    dinh_danh = {"X-User-Id": USER_UUID, "X-Store-Id": WAREHOUSE_UUID}
    task_id = client.post("/chat", headers=dinh_danh, json={
        "user_id": USER_UUID, "store_id": WAREHOUSE_UUID, "message": "doanh thu quý này",
    }).json()["task_id"]

    # Ngân sách 15 giây, không phải 2. Lần `/chat` ĐẦU TIÊN trong cả bộ test phải
    # dựng runtime lười (engine + memory + kho tri thức); dưới tải thì 2 giây
    # không đủ, và test đỏ chập chờn theo thứ tự chạy. Một test lúc xanh lúc đỏ
    # còn hại hơn không có test — người ta học được cách chạy lại cho tới khi xanh.
    han = time.monotonic() + 15.0
    state = {"status": "chưa hỏi lần nào"}
    while time.monotonic() < han:
        state = client.get(f"/api/v1/task/{task_id}", headers=dinh_danh).json()
        if state.get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert state.get("status") in ("completed", "failed"), (
        f"task chưa kết thúc sau 15 giây (trạng thái cuối: {state.get('status')!r})"
    )
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


# ---------------------------------------------------------------------------
# DANH SÁCH ĐƯỜNG DẪN — đọc thẳng từ brain.ts, không chép tay
# ---------------------------------------------------------------------------

def _duong_dan_body_goi() -> list[str]:
    """
    Moi mọi chuỗi `"/..."` mà `brain.ts` dùng làm đường dẫn Brain.

    Đọc THẲNG file TypeScript chứ không giữ một bản chép tay ở đây: bản chép
    tay thì chính nó cũng phải nhớ cập nhật, tức là thêm đúng cái chỗ quên mà
    test này sinh ra để chặn.
    """
    import os
    import re
    from pathlib import Path

    mac_dinh = Path(__file__).resolve().parents[2] / "ANSER_Logistics"
    goc = Path(os.getenv("ANSER_BODY_DIR", "").strip() or mac_dinh)
    f = goc / "frontend" / "src" / "server" / "brain.ts"
    if not f.is_file():
        pytest.skip(
            f"Không thấy Body ở {f}. Đặt ANSER_BODY_DIR để test này chạy — "
            "nó là thứ duy nhất canh việc Brain đổi tên đường dẫn mà Body không biết."
        )
    noi_dung = f.read_text(encoding="utf-8")
    # Chỉ lấy chuỗi truyền cho callBrain/uploadToBrain — tránh vớ phải đường dẫn
    # nội bộ của Next.js ("/dashboard/...").
    return sorted(set(re.findall(r'(?:callBrain|uploadToBrain)<[^>]*>\(\s*"([^"]+)"', noi_dung)))


def test_moi_duong_dan_body_goi_deu_ton_tai_o_brain():
    """
    Đây là lớp lỗi đã cắn một lần: `docker-compose.yml` đặt `API_TOKEN` trong
    khi mã đọc `API_AUTH_TOKEN`. Hai artefact, mỗi cái đúng khi đọc riêng, sai
    khi ghép — và không có gì phát ra tín hiệu.

    Đường dẫn cũng vậy. Brain đổi `/tools/partner-audit` thành `/tools/partners`
    thì mọi test của Brain vẫn xanh, mọi test của Body (không có) cũng vậy, và
    triệu chứng duy nhất là khách bấm nút rồi nhận 404.
    """
    from fastapi.routing import APIRoute

    co_that = {r.path for r in app.routes if isinstance(r, APIRoute)}
    body_goi = _duong_dan_body_goi()
    assert body_goi, "không moi được đường dẫn nào từ brain.ts — regex hỏng?"

    thieu = [p for p in body_goi if p not in co_that]
    assert not thieu, (
        f"Body gọi {thieu} nhưng Brain không có route đó.\n"
        f"Brain đang có: {sorted(co_that)}"
    )
