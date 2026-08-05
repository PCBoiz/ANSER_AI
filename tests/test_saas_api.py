"""
tests/test_saas_api.py — lớp đọc dữ liệu nghiệp vụ từ DB của Body.

VÌ SAO ĐÁNG VIẾT
----------------
151 dòng nằm THẲNG trong luồng phục vụ (nhánh DATA_INTERNAL của /chat) mà chưa
có test nào. Nó cũng là nơi duy nhất trong Brain nối vào DB thật, nên mọi lỗi ở
đây đều mang hình dạng "câu trả lời trôi chảy nhưng số sai" — thứ không có
triệu chứng.

`mcp_server` cũng đã tưởng là ổn cho tới khi viết test và lòi ra hai lỗi tính
sai tiền.

Test dùng SQLite trong bộ nhớ với ĐÚNG tên bảng/cột mà SCHEMA MAP khai báo. Nhờ
vậy, đổi tên cột trong khối hằng số mà quên đổi bên Body sẽ làm test đỏ.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from src.core.saas_api import (
    P_NAME,
    P_PRICE,
    P_STOCK,
    P_WORKSPACE,
    PRODUCTS_TABLE,
    S_AMOUNT,
    S_DATE,
    S_WORKSPACE,
    SALES_TABLE,
    SUPPORTED_PERIODS,
    SaasAPI,
    _period_filter,
    parse_period,
)

# ---------------------------------------------------------------------------
# Đọc kỳ từ câu hỏi — cái bẫy "đúng số, sai câu hỏi"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cau,mong_doi", [
    ("doanh thu hôm nay là bao nhiêu", "today"),
    ("tuần này bán được mấy đơn", "week"),
    ("tháng này doanh số thế nào", "month"),
    # Không nhắc kỳ nào -> hôm nay, và đó là mặc định hợp lý cho câu tra cứu.
    ("còn bao nhiêu thùng nước ngọt", "today"),
])
def test_doc_dung_ky_truy_van_duoc(cau, mong_doi):
    ky = parse_period(cau)
    assert ky.ho_tro and ky.period == mong_doi


@pytest.mark.parametrize("cau,nhan", [
    ("tháng trước bán được bao nhiêu", "tháng trước"),
    ("doanh thu tháng vừa rồi", "tháng trước"),
    ("hôm qua thu được bao nhiêu", "hôm qua"),
    ("tuần rồi bán thế nào", "tuần trước"),
    ("quý này lãi hay lỗ", "quý"),
    ("cả năm nay doanh thu bao nhiêu", "năm"),
])
def test_ky_chua_truy_van_duoc_thi_noi_ro(cau, nhan):
    """
    Đây là chỗ đắt nhất. Trước đây mọi câu này đều nhận số HÔM NAY, và chốt chặn
    neo số liệu không bắt được vì con số ấy CÓ THẬT trong ngữ cảnh.
    """
    ky = parse_period(cau)
    assert not ky.ho_tro
    assert ky.nhan == nhan
    assert ky.period == "", "chưa hỗ trợ thì không được trả về kỳ nào để truy vấn"


def test_thang_truoc_khong_bi_doc_thanh_thang_nay():
    """Hai câu khác nhau một từ, ra hai con số hoàn toàn khác."""
    assert parse_period("doanh thu tháng này").period == "month"
    assert not parse_period("doanh thu tháng trước").ho_tro


def test_moi_ky_doc_duoc_deu_truy_van_duoc():
    """
    Danh sách kỳ ĐỌC được và kỳ TRUY VẤN được phải khớp. Lệch nhau thì câu hỏi
    được nhận nhưng trả về số của kỳ mặc định.
    """
    for cau in ["hôm nay", "tuần này", "tháng này"]:
        ky = parse_period(f"doanh thu {cau}")
        assert ky.period in SUPPORTED_PERIODS


def test_moi_ky_ho_tro_sinh_dieu_kien_where_khac_nhau():
    """Hai kỳ khác nhau mà ra cùng một câu WHERE là lỗi câm."""
    dk = {p: _period_filter(p) for p in SUPPORTED_PERIODS}
    assert len(set(dk.values())) == len(SUPPORTED_PERIODS), dk


def test_ky_la_thi_lui_ve_hom_nay():
    """Giá trị lạ không được sinh SQL rỗng — WHERE rỗng là quét cả bảng."""
    for xau in ["", None, "thap_ky", "quarter"]:
        assert _period_filter(xau) == _period_filter("today")


# ---------------------------------------------------------------------------
# Truy vấn thật trên SQLite
# ---------------------------------------------------------------------------

@pytest.fixture
def saas(monkeypatch):
    """SaasAPI trỏ vào SQLite trong bộ nhớ, dựng theo đúng SCHEMA MAP."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE TABLE {PRODUCTS_TABLE} ("
            f"id INTEGER PRIMARY KEY, {P_NAME} TEXT, {P_PRICE} REAL, "
            f"{P_STOCK} INTEGER, {P_WORKSPACE} INTEGER)"
        ))
        conn.execute(text(
            f"CREATE TABLE {SALES_TABLE} ("
            f"id INTEGER PRIMARY KEY, {S_AMOUNT} REAL, {S_DATE} TEXT, "
            f"{S_WORKSPACE} INTEGER)"
        ))
        for i, (ten, gia, ton, ws) in enumerate([
            ("Dầu động cơ CF-4 15W40", 4_300_000, 15, 1),
            ("Dầu thuỷ lực AW46", 3_350_000, 40, 1),
            ("Mỡ bò EP2", 1_020_000, 17, 1),
            ("Dầu động cơ CF-4 15W40", 9_999_999, 5, 2),   # khách KHÁC
        ], start=1):
            conn.execute(
                text(f"INSERT INTO {PRODUCTS_TABLE} "
                     f"(id, {P_NAME}, {P_PRICE}, {P_STOCK}, {P_WORKSPACE}) "
                     f"VALUES (:i, :n, :g, :t, :w)"),
                {"i": i, "n": ten, "g": gia, "t": ton, "w": ws},
            )
        conn.execute(text(
            f"INSERT INTO {SALES_TABLE} (id, {S_AMOUNT}, {S_DATE}, {S_WORKSPACE}) "
            f"VALUES (1, 12000000, date('now'), 1), "
            f"       (2,  8000000, date('now'), 1), "
            f"       (3, 99000000, date('now'), 2)"
        ))

    api = SaasAPI.__new__(SaasAPI)
    api.engine = engine
    return api


def test_tim_duoc_san_pham_theo_ten(saas):
    import json
    kq = json.loads(saas.lookup_product("thuỷ lực", workspace_id=1))
    assert len(kq) == 1 and "AW46" in kq[0]["name"]


def test_khong_thay_thi_noi_ro_bang_tieng_viet(saas):
    """Trả chuỗi rỗng hay '[]' thì model diễn giải thành 'kho trống'."""
    kq = saas.lookup_product("lốp xe tải", workspace_id=1)
    assert "Không tìm thấy" in kq and "lốp xe tải" in kq


def test_khong_lot_san_pham_cua_khach_khac(saas):
    """
    Hàng rào P2. Cùng tên hàng, khác `workspace_id` — lọt là lộ giá của khách
    này cho khách kia, và đó là loại lỗi không sửa được sau khi đã xảy ra.
    """
    import json
    kq = json.loads(saas.lookup_product("CF-4", workspace_id=1))
    assert len(kq) == 1
    assert "9.999.999" not in json.dumps(kq, ensure_ascii=False)


def test_doanh_so_chi_tinh_cua_dung_khach(saas):
    kq = saas.get_sales_report(workspace_id=1, period="today")
    assert kq["orders"] == 2
    assert "20,000,000" in kq["revenue"] or "20.000.000" in kq["revenue"]


def test_doanh_so_tra_ve_ky_da_dung_de_tinh(saas):
    """
    Không nói rõ kỳ thì con số thành vô nghĩa — người đọc không biết nó của
    ngày, tuần hay tháng.
    """
    assert saas.get_sales_report(workspace_id=1, period="today")["period"] == "today"


def test_gia_None_khong_lam_sap(saas):
    """Sản phẩm chưa đặt giá là chuyện thường; không được ném ngoại lệ."""
    import json
    with saas.engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {PRODUCTS_TABLE} "
            f"(id, {P_NAME}, {P_PRICE}, {P_STOCK}, {P_WORKSPACE}) "
            f"VALUES (99, 'Hàng mới chưa định giá', NULL, NULL, 1)"
        ))
    kq = json.loads(saas.lookup_product("chưa định giá", workspace_id=1))
    assert kq[0]["price"] == "N/A" and kq[0]["stock"] == "N/A"


def test_loi_sql_khong_lam_sap_ca_cau_tra_loi(saas):
    """
    Bảng biến mất / đổi tên -> trả câu tiếng Việt, KHÔNG ném ra ngoài. Nhánh
    /chat bắt Exception rồi đưa "(không lấy được dữ liệu)" vào ngữ cảnh; ném ra
    đây thì cả lượt hỏng thay vì suy giảm mềm.
    """
    with saas.engine.begin() as conn:
        conn.execute(text(f"DROP TABLE {SALES_TABLE}"))
    kq = saas.get_sales_report(workspace_id=1, period="today")
    assert kq["revenue"] == "Lỗi" and kq["orders"] == 0


def test_chua_noi_duoc_db_thi_bao_ro(monkeypatch):
    api = SaasAPI.__new__(SaasAPI)
    api.engine = None
    with pytest.raises(RuntimeError, match="CSDL"):
        api.lookup_product("dầu", workspace_id=1)


def test_khong_noi_chuoi_nguoi_dung_vao_sql(saas):
    """
    `lookup_product` nhận NGUYÊN VĂN tin nhắn người dùng. Nối chuỗi vào SQL ở
    đây là lỗ tiêm SQL đi thẳng từ khung chat.
    """
    doc = "'; DROP TABLE products; --"
    kq = saas.lookup_product(doc, workspace_id=1)
    assert "Không tìm thấy" in kq
    with saas.engine.connect() as conn:      # bảng phải còn nguyên
        assert conn.execute(text(f"SELECT COUNT(*) FROM {PRODUCTS_TABLE}")).scalar() >= 3
