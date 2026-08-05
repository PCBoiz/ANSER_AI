"""
tests/test_retrieval_policy.py — được phép lấy câu trả lời từ đâu.

Luật ở đây quyết định một chuyện rất cụ thể: có được lấy một trang bất kỳ trên
mạng và trình bày như thể đó là quy định của công ty khách hay không. Sai theo
hướng "chặn nhầm" thì mất một câu trả lời; sai theo hướng "cho qua nhầm" thì
chủ doanh nghiệp ra quyết định dựa trên thông tin của công ty khác.
"""

from src.core.retrieval_policy import (
    KHONG_CO_TAI_LIEU,
    decide_web_fallback,
    is_internal_question,
    is_public_knowledge_question,
)

# --------------------------------------------------------------------------
# Câu hỏi nội bộ — TUYỆT ĐỐI không lấy nguồn ngoài
# --------------------------------------------------------------------------

def test_hoi_ve_tai_lieu_cua_minh_khong_tra_web():
    for cau in [
        "chính sách công nợ bên mình thế nào",
        "quy định giao nhận của công ty là gì",
        "hợp đồng với Minh Long có điều khoản phạt không",
        "bảng giá cước áp dụng cho khách sỉ ra sao",
        "quy trình nội bộ khi hàng về trễ",
    ]:
        assert not decide_web_fallback(cau).allow, cau
        assert is_internal_question(cau), cau


def test_dau_hieu_noi_bo_thang_dau_hieu_luat():
    """
    "Bên mình đang áp thuế suất mấy phần trăm" khớp CẢ HAI mẫu. Câu trả lời đúng
    là "chưa có trong tài liệu", không phải một bài viết về thuế suất.
    """
    cau = "bên mình đang áp thuế suất mấy phần trăm"
    assert is_internal_question(cau) and is_public_knowledge_question(cau)
    quyet = decide_web_fallback(cau)
    assert not quyet.allow
    assert "nội bộ" in quyet.reason


# --------------------------------------------------------------------------
# Kiến thức công khai — tra web là đúng việc
# --------------------------------------------------------------------------

def test_hoi_luat_thue_duoc_tra_web():
    for cau in [
        "nghị định 72 quy định thuế suất bao nhiêu",
        "thủ tục đăng ký hộ kinh doanh gồm những gì",
        "hoá đơn điện tử bắt buộc từ khi nào",
        "mức đóng bảo hiểm xã hội năm nay là bao nhiêu",
    ]:
        assert decide_web_fallback(cau).allow, cau


def test_cua_nha_nuoc_khong_bi_nham_la_noi_bo():
    """
    "Luật thuế của nhà nước" từng khớp phải mẫu sở hữu ở cụm "của nhà" — đúng
    câu mà tra web là việc nên làm.
    """
    cau = "quy định của nhà nước về thuế khoán hộ kinh doanh"
    assert not is_internal_question(cau)
    assert decide_web_fallback(cau).allow


# --------------------------------------------------------------------------
# Không thuộc loại nào -> không tra web
# --------------------------------------------------------------------------

def test_cau_khong_phai_kien_thuc_cong_khai_thi_khong_tra_web():
    for cau in ["hôm nay thời tiết thế nào", "bạn làm được những gì", ""]:
        assert not decide_web_fallback(cau).allow, cau


def test_moi_quyet_dinh_deu_co_ly_do():
    """Lý do đi vào log — không có nó thì không soi lại được vì sao chặn."""
    for cau in ["", "bên mình thu bao nhiêu", "nghị định 72 nói gì", "xin chào"]:
        assert decide_web_fallback(cau).reason


def test_cau_thu_nhan_khong_biet_la_hang_so():
    """
    Đây là lúc hệ thống nói mình không biết. Nhờ model diễn đạt lại thì câu đó
    có cơ hội biến thành một câu nghe như đang biết.
    """
    assert "chưa tìm thấy" in KHONG_CO_TAI_LIEU
    assert "Tài liệu" in KHONG_CO_TAI_LIEU      # chỉ đúng chỗ cần tải lên
