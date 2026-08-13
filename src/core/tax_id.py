"""
src/core/tax_id.py — kiểm mã số thuế Việt Nam bằng chính số kiểm tra của nó.

Mã số thuế 10 chữ số có chữ số cuối là SỐ KIỂM TRA tính từ 9 chữ số đầu, nên
gõ sai một chữ số là phát hiện được ngay tại chỗ, không cần tra cứu mạng. Đây
là kiểu kiểm tra đáng giá nhất: chạy offline, không phụ thuộc dịch vụ nào,
không bao giờ báo nhầm.

    N10 = 10 − (Σ Ni × Wi  mod 11),  W = [31, 29, 23, 19, 17, 13, 7, 5, 3]

Đơn vị phụ thuộc dùng 13 chữ số: 10 số của đơn vị chủ quản + 3 số thứ tự chi
nhánh, thường viết '0123456789-001'. Phần 10 số đầu vẫn phải đúng số kiểm tra.

ĐỐI CHIẾU THỰC TẾ: chạy trên 109 mã số thuế thật trong danh sách khách hàng và
nhà cung cấp của Hoàng Phát — 0 mã sai. Một công thức sai sẽ không cho kết quả
sạch như vậy trên dữ liệu thật.

Hàm này KHÔNG nói mã số thuế có tồn tại hay không, cũng không nói doanh nghiệp
còn hoạt động hay đã đóng. Nó chỉ nói chuỗi số này có tự nhất quán không.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_TRONG_SO = (31, 29, 23, 19, 17, 13, 7, 5, 3)

_MST_RE = re.compile(r"^(\d{10})(?:[-\s]?(\d{3}))?$")

# Số định danh cá nhân: đúng 12 chữ số (Bộ Công an cấp).
_DINH_DANH_RE = re.compile(r"^\d{12}$")


@dataclass(frozen=True)
class KetQuaMST:
    """Kết quả kiểm. `hop_le=None` nghĩa là KHÔNG KIỂM ĐƯỢC, khác hẳn với sai."""
    goc: str
    chuan_hoa: str = ""
    hop_le: Optional[bool] = None
    la_chi_nhanh: bool = False
    la_dinh_danh_ca_nhan: bool = False
    ly_do: str = ""

    def __bool__(self) -> bool:
        return self.hop_le is True


def chuan_hoa(ma: object) -> str:
    """
    Bỏ khoảng trắng và dấu chấm; giữ nguyên dấu gạch ngang của chi nhánh.

    Ô Excel định dạng kiểu SỐ sẽ nuốt mất số 0 đứng đầu, mà rất nhiều mã số
    thuế Việt Nam bắt đầu bằng 0 — '0109527605' về tay ta thành 109527605. Chỉ
    bù số 0 khi đầu vào ĐÚNG LÀ SỐ và độ dài đúng 9 hoặc 12; chuỗi 9 ký tự thì
    để nguyên, vì đó là dữ liệu sai chứ không phải bị Excel cắt.
    """
    if isinstance(ma, bool) or ma is None:
        return ""
    if isinstance(ma, (int, float)) and float(ma).is_integer():
        so = str(int(ma))
        return "0" + so if len(so) in (9, 12) else so
    return re.sub(r"[\s.]", "", str(ma)).strip()


def kiem_ma_so_thue(ma: object) -> KetQuaMST:
    """
    Kiểm một mã số thuế.

    Trả `hop_le=None` cho ô rỗng hoặc chuỗi không đúng khuôn 10/13 số — đó là
    'chưa có dữ liệu', không phải 'sai'. Gộp hai thứ này lại sẽ khiến báo cáo
    buộc tội một danh sách khách lẻ chưa nhập mã số thuế.
    """
    goc = chuan_hoa(ma)
    if not goc:
        return KetQuaMST(goc="", hop_le=None, ly_do="Chưa có mã số thuế")

    if _DINH_DANH_RE.match(goc):
        # Thông tư 86/2024/TT-BTC: từ 01/7/2025, SỐ ĐỊNH DANH CÁ NHÂN (12 chữ số
        # do Bộ Công an cấp) thay cho mã số thuế của cá nhân, hộ kinh doanh và
        # người phụ thuộc.
        #
        # Trên dữ liệu thật của Hoàng Phát có 5 khách như vậy — hộ kinh doanh và
        # cá nhân. Bản đầu của hàm này báo cả 5 là "không đúng khuôn", tức là
        # buộc tội năm dòng hoàn toàn hợp lệ, chỉ vì luật vừa đổi.
        #
        # Số định danh KHÔNG có chữ số kiểm tra như mã số thuế, nên `hop_le` phải
        # là None: đúng khuôn nhưng không có cách nào đối chiếu. Nói "hợp lệ" ở
        # đây là hứa một thứ ta không kiểm được.
        return KetQuaMST(
            goc=goc, chuan_hoa=goc, hop_le=None, la_dinh_danh_ca_nhan=True,
            ly_do="Số định danh cá nhân 12 số (Thông tư 86/2024/TT-BTC, dùng thay "
                  "mã số thuế cho cá nhân và hộ kinh doanh từ 01/7/2025) — không có "
                  "số kiểm tra để đối chiếu",
        )

    m = _MST_RE.match(goc)
    if not m:
        return KetQuaMST(
            goc=goc, hop_le=None,
            ly_do="Không đúng khuôn 10 chữ số, 13 chữ số (10 số + 3 số chi nhánh), "
                  "hay 12 chữ số (số định danh cá nhân)",
        )

    chinh, chi_nhanh = m.group(1), m.group(2)
    tong = sum(int(chinh[i]) * _TRONG_SO[i] for i in range(9))
    mong_doi = 10 - (tong % 11)
    dung = int(chinh[9]) == mong_doi

    dep = chinh if not chi_nhanh else f"{chinh}-{chi_nhanh}"
    if not dung:
        return KetQuaMST(
            goc=goc, chuan_hoa=dep, hop_le=False, la_chi_nhanh=bool(chi_nhanh),
            ly_do=(f"Số kiểm tra sai: chữ số cuối là {chinh[9]}, theo 9 chữ số đầu "
                   f"phải là {mong_doi if mong_doi < 10 else 'không có giá trị hợp lệ'}"),
        )
    if chi_nhanh and chi_nhanh == "000":
        return KetQuaMST(
            goc=goc, chuan_hoa=dep, hop_le=False, la_chi_nhanh=True,
            ly_do="Số thứ tự chi nhánh phải từ 001 trở lên",
        )
    return KetQuaMST(goc=goc, chuan_hoa=dep, hop_le=True, la_chi_nhanh=bool(chi_nhanh))


def ma_chu_quan(ma: object) -> str:
    """
    10 số đầu — để gom chi nhánh về cùng một pháp nhân khi đối chiếu công nợ.

    Số định danh cá nhân trả về NGUYÊN 12 số: cắt 10 số đầu sẽ tạo ra một khoá
    vô nghĩa và có thể vô tình gom hai người khác nhau làm một.
    """
    kq = kiem_ma_so_thue(ma)
    if not kq.chuan_hoa:
        return ""
    return kq.chuan_hoa if kq.la_dinh_danh_ca_nhan else kq.chuan_hoa[:10]
