"""
tests/test_mcp_server.py — lớp tính tiền tất định dưới /ocr và /tools/vat.

VÌ SAO ĐÁNG VIẾT
----------------
Đây là chỗ số tiền trên tờ hoá đơn nhà xe được TÍNH LẠI bằng code thuần rồi đối
chiếu với số VLM đọc ra. Nói cách khác: nó là thứ quyết định "con số này có
đáng tin không". Vậy mà nó chưa có test nào — hàng rào duy nhất chống lại việc
model đọc nhầm một chữ số lại là phần không ai kiểm.

Mọi ca dưới đây tính tay được, cố ý vậy: một phép kiểm mà phải chạy code mới
biết kết quả đúng thì không kiểm được gì.
"""

from src.core.mcp_server import VAT_REDUCED, VAT_STANDARD, MCPServer, _round_vnd

# ---------------------------------------------------------------------------
# Làm tròn
# ---------------------------------------------------------------------------

def test_lam_tron_nua_len_khong_phai_kieu_ngan_hang():
    """
    `round()` của Python làm tròn 0.5 về SỐ CHẴN: round(0.5)=0, round(2.5)=2.
    Sổ sách Việt Nam làm tròn nửa LÊN. Lệch 1 đồng mỗi dòng, nhân vài trăm dòng
    là hoá đơn không khớp mà không ai chỉ ra được vì sao.
    """
    assert _round_vnd(0.5) == 1
    assert _round_vnd(2.5) == 3
    assert _round_vnd(1.4) == 1


# ---------------------------------------------------------------------------
# Thuế suất
# ---------------------------------------------------------------------------

def test_mac_dinh_la_muc_chuan_10_phan_tram():
    """
    Mặc định SAI thành 8% thì mọi hoá đơn không khai rõ diện đều thiếu thuế, và
    sai theo hướng có lợi nên lâu bị phát hiện.
    """
    kq = MCPServer.calculate_vat(1_000_000)
    assert kq["tax_rate"] == VAT_STANDARD == 0.10
    assert kq["tax_amount"] == 100_000
    assert kq["total_price"] == 1_100_000


def test_dien_giam_theo_nd_72():
    kq = MCPServer.calculate_vat(1_000_000, is_reduced=True)
    assert kq["tax_rate"] == VAT_REDUCED == 0.08
    assert kq["total_price"] == 1_080_000


def test_dong_khai_ro_khong_giam_thang_mac_dinh_ca_hoa_don():
    """
    `False` khác `None`. Kiểm bằng "falsy" thay vì `is None` sẽ nuốt mất dòng
    khai rõ là KHÔNG được giảm, rồi âm thầm tính 8% cho nó.
    """
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 1_000_000, "qty": 1, "is_reduced_vat": False}],
        stated_total=1_100_000,
        default_is_reduced=True,
    )
    assert kq["lines"][0]["tax_rate"] == 0.10
    assert kq["is_valid"]


def test_dong_khong_khai_thi_theo_mac_dinh_hoa_don():
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 1_000_000, "qty": 1}],
        stated_total=1_080_000,
        default_is_reduced=True,
    )
    assert kq["lines"][0]["tax_rate"] == 0.08


# ---------------------------------------------------------------------------
# Số lượng
# ---------------------------------------------------------------------------

def test_thieu_so_luong_thi_coi_la_mot():
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 500_000}], stated_total=550_000,
    )
    assert kq["calculated_total"] == 550_000


def test_so_luong_bang_khong_khong_bi_bien_thanh_mot():
    """
    `int(qty or 1)` biến 0 thành 1: một dòng số lượng 0 vẫn bị tính tiền như
    một đơn vị. Hoá đơn nhà xe hay có dòng huỷ để số lượng 0.
    """
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "huỷ", "price": 500_000, "qty": 0}], stated_total=0,
    )
    assert kq["calculated_total"] == 0
    assert kq["is_valid"]


def test_so_luong_le_khong_bi_cat_cut():
    """
    `int(2.5)` = 2. Dầu nhờn bán theo lít nên số lẻ là chuyện thường — cắt cụt
    là tính thiếu tiền, và tính thiếu thì không bên nào kêu.
    """
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "dầu", "price": 100_000, "qty": 2.5}], stated_total=275_000,
    )
    assert kq["calculated_total"] == 275_000
    assert kq["is_valid"]


# ---------------------------------------------------------------------------
# Đối chiếu tổng — việc chính
# ---------------------------------------------------------------------------

def test_bat_duoc_loi_doc_nham_chu_so():
    """OCR đọc 1.100.000 thành 11.000.000 — đúng thứ hàng rào này sinh ra để bắt."""
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 1_000_000, "qty": 1}],
        stated_total=11_000_000,
    )
    assert not kq["is_valid"]
    assert kq["difference"] == 9_900_000


def test_bo_qua_nhieu_lam_tron_tung_dong():
    """Lệch 5 đồng do làm tròn từng dòng không phải lỗi hoá đơn."""
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 1_000_000, "qty": 1}],
        stated_total=1_100_005,
    )
    assert kq["is_valid"]
    assert kq["tolerance"] == 10 or kq["tolerance"] > 10


def test_nguong_tuong_doi_ap_dung_cho_hoa_don_lon():
    """
    Hoá đơn 1 tỷ: 10 đồng tuyệt đối là vô nghĩa, phải nới theo 0.1% giá trị.
    """
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": 1_000_000_000, "qty": 1}],
        stated_total=1_100_000_000,
    )
    assert kq["tolerance"] == 1_100_000        # 0.1% của tổng ghi trên hoá đơn
    assert kq["is_valid"]


def test_hoa_don_khong_co_dong_nao_ma_van_ghi_tong_thi_bao_sai():
    """
    VLM đọc ra rỗng nhưng vẫn thấy con số tổng — phải BÁO SAI, không được lặng
    lẽ coi là khớp. Đây là ca ảnh mờ, hay gặp nhất ở hoá đơn chụp bằng điện thoại.
    """
    kq = MCPServer.validate_invoice_total(items=[], stated_total=5_000_000)
    assert not kq["is_valid"]
    assert kq["calculated_total"] == 0
    assert kq["difference"] == 5_000_000


def test_tra_ve_tung_dong_de_truy_nguoc():
    """Không dẫn được ra từng dòng thì "sai 200 nghìn" là một câu vô dụng."""
    kq = MCPServer.validate_invoice_total(
        items=[
            {"name": "Dầu 18L", "price": 900_000, "qty": 2},
            {"name": "Mỡ bò", "price": 150_000, "qty": 1, "is_reduced_vat": True},
        ],
        stated_total=2_142_000,
    )
    assert [d["name"] for d in kq["lines"]] == ["Dầu 18L", "Mỡ bò"]
    assert kq["lines"][0]["line_total"] == 1_980_000     # 1.800.000 + 10%
    assert kq["lines"][1]["line_total"] == 162_000       # 150.000 + 8%
    assert kq["is_valid"]


def test_thieu_ten_dong_van_chay_duoc():
    """Hoá đơn viết tay nhiều khi không đọc ra tên hàng — không được vì thế mà sập."""
    kq = MCPServer.validate_invoice_total(
        items=[{"price": 100_000, "qty": 1}], stated_total=110_000,
    )
    assert kq["lines"][0]["name"] == "Unknown"
    assert kq["is_valid"]


def test_gia_hoac_tong_de_trong_khong_lam_sap():
    kq = MCPServer.validate_invoice_total(
        items=[{"name": "A", "price": None, "qty": None}], stated_total=None,
    )
    assert kq["calculated_total"] == 0
    assert kq["is_valid"]
