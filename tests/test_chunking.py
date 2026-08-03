"""
tests/test_chunking.py — cắt đoạn phải GIỮ được bảng giá.

Bảng giá cước là tài liệu giá trị nhất trong kho tri thức của khách, và cũng là
thứ dễ hỏng nhất: cắt sai chỗ thì một đoạn giữ tuyến, đoạn kia giữ số tiền, model
trả lời "12.000.000" mà không biết của tuyến nào — nghe vẫn trôi chảy.
"""

from __future__ import annotations

from src.core.chunking import MAX_CHARS, Chunk, chunk_document, looks_tabular

BANG_GIA = """\
BẢNG GIÁ CƯỚC VẬN TẢI 2026
Hiệu lực từ 01/01/2026

Điểm đi\tĐiểm đến\tLoại xe\tĐơn giá
Hà Nội\tĐà Nẵng\txe tải 5 tấn\t12.000.000
Hà Nội\tTP.HCM\tcontainer 20ft\t31.500.000
Hải Phòng\tĐà Nẵng\txe tải 8 tấn\t15.200.000
"""


# ---------------------------------------------------------------------------
# Không được cắt giữa dòng
# ---------------------------------------------------------------------------

def test_khong_bao_gio_cat_giua_mot_dong():
    """Dòng là đơn vị nhỏ nhất. Cắt giữa dòng là tách tuyến khỏi giá của nó."""
    text = "\n".join(f"Tuyến {i}\tXe {i} tấn\t{i}.000.000" for i in range(200))
    chunks = chunk_document(text, max_chars=300)
    assert len(chunks) > 1, "phải cắt thành nhiều đoạn mới kiểm được"

    goc = set(text.split("\n"))
    for c in chunks:
        for line in c.text.split("\n"):
            assert line in goc, f"dòng bị cắt vụn: {line!r}"


def test_mot_dong_gia_luon_con_nguyen_o_it_nhat_mot_doan():
    text = "\n".join(f"Hà Nội\tĐiểm {i}\txe tải\t{i}.500.000" for i in range(100))
    chunks = chunk_document(text, max_chars=250)
    noi_lai = "\n".join(c.text for c in chunks)
    for i in range(100):
        assert f"Hà Nội\tĐiểm {i}\txe tải\t{i}.500.000" in noi_lai


def test_giu_nguyen_ky_tu_xuong_dong():
    """
    Bản cũ `word_tokenize` cả tài liệu rồi nối bằng dấu cách — xoá sạch xuống
    dòng TRƯỚC khi cắt. Đây là bài kiểm tra chống lùi lại đúng lỗi đó.
    """
    chunks = chunk_document(BANG_GIA)
    assert chunks
    assert "\n" in chunks[0].text, "cấu trúc dòng đã bị làm phẳng"
    assert "\t" in chunks[0].text, "ranh giới cột đã bị mất"


def test_moi_dong_gia_van_la_mot_dong_rieng():
    """
    Bản cũ biến cả bảng thành một dải chữ, nên "12.000.000" dính liền với "Hà Nội"
    của dòng KẾ TIẾP — model đọc ra một mức giá gắn nhầm tuyến.
    """
    chunks = chunk_document(BANG_GIA)
    moi_dong = [ln for c in chunks for ln in c.text.split("\n")]
    assert "Hà Nội\tĐà Nẵng\txe tải 5 tấn\t12.000.000" in moi_dong
    assert "Hà Nội\tTP.HCM\tcontainer 20ft\t31.500.000" in moi_dong
    # Không dòng nào được chứa giá của dòng này lẫn tuyến của dòng sau.
    for ln in moi_dong:
        assert not ("12.000.000" in ln and "TP.HCM" in ln)


def test_bang_gia_khong_bi_vo_vun_thanh_tung_dong():
    """
    Mọi dòng bảng đều ngắn và không có dấu câu. Nhận dạng tiêu đề dễ dãi là coi
    từng dòng một là tiêu đề rồi chốt đoạn ở mỗi dòng — bảng nát thành từng mảnh
    một dòng, mất sạch ngữ cảnh cột.
    """
    chunks = chunk_document(BANG_GIA)
    assert len(chunks) == 1, f"bảng ngắn phải nằm gọn một đoạn, nhận {len(chunks)}"


# ---------------------------------------------------------------------------
# Tiêu đề đi theo đoạn
# ---------------------------------------------------------------------------

def test_doan_mang_theo_tieu_de_cua_no():
    chunks = chunk_document(BANG_GIA)
    assert chunks[0].heading, "đoạn phải biết mình thuộc phần nào"
    assert "GIÁ CƯỚC" in chunks[0].heading.upper()


def test_tieu_de_giua_chung_thuoc_ve_doan_SAU():
    text = ("PHẦN 1\n" + "x" * 400 + "\n" + "y" * 400 + "\n"
            "PHẦN 2\n" + "z" * 400 + "\n" + "w" * 400 + "\n")
    chunks = chunk_document(text, max_chars=500)
    assert len(chunks) >= 2
    dau = [c for c in chunks if "x" * 50 in c.text][0]
    sau = [c for c in chunks if "z" * 50 in c.text][0]
    assert dau.heading == "PHẦN 1"
    assert sau.heading == "PHẦN 2", "tiêu đề mới phải thuộc đoạn sau nó"


# ---------------------------------------------------------------------------
# Chồng lấn theo dòng
# ---------------------------------------------------------------------------

def test_chong_lan_tinh_bang_dong_khong_phai_tu():
    text = "\n".join(f"dòng số {i}" for i in range(60))
    chunks = chunk_document(text, max_chars=120, overlap_lines=2)
    assert len(chunks) > 2
    for a, b in zip(chunks, chunks[1:]):
        cuoi_a = a.text.split("\n")[-2:]
        dau_b = b.text.split("\n")[:2]
        assert set(cuoi_a) & set(dau_b), "hai đoạn liền nhau không chồng lấn dòng nào"


def test_tat_chong_lan_thi_khong_lap_dong():
    text = "\n".join(f"dòng {i}" for i in range(40))
    chunks = chunk_document(text, max_chars=100, overlap_lines=0)
    tat_ca = [ln for c in chunks for ln in c.text.split("\n")]
    assert len(tat_ca) == len(set(tat_ca)), "tắt chồng lấn mà vẫn lặp dòng"


# ---------------------------------------------------------------------------
# Biên
# ---------------------------------------------------------------------------

def test_tai_lieu_rong_tra_rong():
    assert chunk_document("") == []
    assert chunk_document("   \n\n  \n") == []


def test_tai_lieu_ngan_ra_dung_mot_doan():
    chunks = chunk_document("Chỉ có một dòng ngắn.")
    assert len(chunks) == 1
    assert chunks[0].index == 0


def test_mot_dong_dai_hon_han_muc_van_ra_nguyen_ven():
    """Thà một đoạn quá cỡ còn hơn một dòng bị chặt đôi."""
    dai = "A" * (MAX_CHARS * 2)
    chunks = chunk_document(dai)
    assert len(chunks) == 1
    assert chunks[0].text == dai


def test_index_tang_lien_tuc_tu_0():
    chunks = chunk_document("\n".join(f"dòng {i}" for i in range(100)), max_chars=100)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_xuong_dong_kieu_windows_khong_tao_dong_rac():
    chunks = chunk_document("dòng một\r\ndòng hai\r\ndòng ba")
    assert "\r" not in chunks[0].text


def test_chunk_la_dataclass_co_du_truong_de_dan_nguon():
    c = chunk_document("Tiêu đề\nnội dung")[0]
    assert isinstance(c, Chunk)
    assert hasattr(c, "text") and hasattr(c, "index") and hasattr(c, "heading")


# ---------------------------------------------------------------------------
# Nhận dạng bảng — để cảnh báo lúc nạp
# ---------------------------------------------------------------------------

def test_nhan_ra_bang_gia():
    assert looks_tabular(BANG_GIA)


def test_van_ban_thuong_khong_bi_nham_la_bang():
    van_xuoi = (
        "Hợp đồng vận chuyển hàng hoá được ký giữa hai bên.\n"
        "Bên A có trách nhiệm giao hàng đúng thời hạn đã thoả thuận.\n"
        "Bên B thanh toán trong vòng ba mươi ngày kể từ ngày nhận hàng.\n"
        "Mọi tranh chấp được giải quyết theo pháp luật Việt Nam.\n"
    )
    assert not looks_tabular(van_xuoi)


def test_vai_dong_thi_chua_ket_luan_la_bang():
    assert not looks_tabular("a\tb\nc\td")
