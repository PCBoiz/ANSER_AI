"""
offline_training/stats.py — hai phép thống kê cho việc đọc kết quả benchmark.

VÌ SAO CẦN
----------
Báo cáo benchmark đang in ra những con số như "trích xuất 84.8%" trên bộ eval
27–100 câu, không kèm khoảng tin cậy nào. Với n nhỏ, con số đó chính xác giả:
84.8% trên n=27 có khoảng tin cậy 95% cỡ [67%, 94%] — rộng 27 điểm. Hai lần
chạy lệch nhau 5 điểm gần như chắc chắn là nhiễu lấy mẫu, không phải model đổi.

Nguy hiểm ở chỗ nó dẫn tới hai quyết định sai ngược nhau:
  - cổng chặn trượt vì nhiễu  -> đi sửa một model không có vấn đề gì
  - cổng chặn qua vì nhiễu    -> ship một bản thật sự kém hơn

Và baseline với bản tinh chỉnh chạy trên CÙNG một bộ câu hỏi, nên so theo cặp
mạnh hơn hẳn so hai số trung bình — đồng thời trả lời được câu mà số trung bình
giấu đi: *fine-tune đã làm hỏng câu nào trước đó vốn đúng?*

Không dùng scipy: môi trường Colab đã đủ nặng, và hai hàm này viết tay được
chính xác bằng `math`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# z cho mức tin cậy 95%. Đủ dùng; không mở tham số để khỏi có hai chỗ báo cáo
# dùng hai mức khác nhau rồi so với nhau.
_Z95 = 1.959963984540054


@dataclass(frozen=True)
class Khoang:
    """Tỷ lệ kèm khoảng tin cậy 95%."""

    k: int          # số ca đúng
    n: int          # tổng số ca
    ty_le: float
    thap: float
    cao: float

    @property
    def do_rong(self) -> float:
        return self.cao - self.thap

    def __str__(self) -> str:
        return f"{self.ty_le * 100:5.1f}%  [{self.thap * 100:.1f}–{self.cao * 100:.1f}]"


def wilson(k: int, n: int) -> Khoang:
    """
    Khoảng tin cậy Wilson cho tỷ lệ k/n.

    Dùng Wilson chứ không dùng công thức chuẩn (Wald) vì Wald sai hẳn ở đúng
    vùng ta hay gặp: n nhỏ, hoặc tỷ lệ gần 0 hay gần 1. Với k=n (đúng hết),
    Wald cho khoảng rộng bằng 0 — tức là khẳng định "chắc chắn 100%" từ 27 mẫu.
    Wilson cho [0.87, 1.0], đúng với những gì 27 mẫu nói được.
    """
    if n <= 0:
        return Khoang(0, 0, 0.0, 0.0, 1.0)
    k = max(0, min(k, n))
    p = k / n
    z2_n = _Z95 * _Z95 / n
    tam = (p + z2_n / 2) / (1 + z2_n)
    nua = (_Z95 / (1 + z2_n)) * math.sqrt(p * (1 - p) / n + z2_n / (4 * n))
    thap, cao = max(0.0, tam - nua), min(1.0, tam + nua)
    # Đúng 0 và đúng 1 phải là ĐÚNG, không phải 2.8e-17. Bụi số thực ở đây làm
    # `thap <= ty_le` sai khi k=0, và in ra "-0.0%" trong báo cáo.
    if k == 0:
        thap = 0.0
    if k == n:
        cao = 1.0
    return Khoang(k, n, p, thap, cao)


def _binom_duoi(k: int, n: int) -> float:
    """P(X <= k) với X ~ Binom(n, 0.5)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)


@dataclass(frozen=True)
class SoCap:
    """
    Kết quả so hai bản trên CÙNG một bộ câu hỏi.

    `chi_B_dung` là con số đáng chú ý nhất và cũng là con số duy nhất mà điểm
    trung bình giấu hoàn toàn: những câu bản A trả lời đúng mà bản B làm hỏng.
    """

    n: int
    ca_hai_dung: int
    chi_A_dung: int      # A đúng, B sai  — B LÀM HỎNG
    chi_B_dung: int      # A sai, B đúng  — B SỬA ĐƯỢC
    ca_hai_sai: int
    p_value: float

    @property
    def khac_biet(self) -> int:
        return self.chi_A_dung + self.chi_B_dung

    @property
    def dang_ke(self) -> bool:
        """p < 0.05. Không đáng kể KHÔNG có nghĩa là hai bản như nhau."""
        return self.p_value < 0.05


def mcnemar(a: list[bool], b: list[bool]) -> SoCap:
    """
    Phép thử McNemar dạng chính xác cho hai bản chạy trên cùng bộ câu hỏi.

    Chỉ những câu HAI BÊN KHÁC NHAU mới mang thông tin. Câu cả hai cùng đúng
    hoặc cùng sai không nói gì về việc bản nào hơn — gộp chúng vào phép so là
    pha loãng tín hiệu, và đó chính là điều so hai số trung bình đang làm.

    Trả `p_value` hai phía. n nhỏ nên dùng bản nhị thức chính xác thay vì xấp
    xỉ chi-bình-phương (xấp xỉ đó sai khi số ca khác biệt dưới ~25).
    """
    if len(a) != len(b):
        raise ValueError(f"hai danh sách phải cùng độ dài: {len(a)} vs {len(b)}")

    ca_hai_dung = sum(1 for x, y in zip(a, b) if x and y)
    chi_A = sum(1 for x, y in zip(a, b) if x and not y)
    chi_B = sum(1 for x, y in zip(a, b) if y and not x)
    ca_hai_sai = sum(1 for x, y in zip(a, b) if not x and not y)

    khac = chi_A + chi_B
    if khac == 0:
        # Hai bản giống hệt nhau trên mọi câu. Không có bằng chứng nào cho việc
        # bản này hơn bản kia — p = 1, không phải p = 0.
        p = 1.0
    else:
        p = min(1.0, 2 * _binom_duoi(min(chi_A, chi_B), khac))

    return SoCap(len(a), ca_hai_dung, chi_A, chi_B, ca_hai_sai, p)


def cong_chan(ty_le: Khoang, nguong: float) -> tuple[bool, str]:
    """
    Quyết định cổng chặn, KÈM lời cảnh báo khi n quá nhỏ để quyết.

    Vẫn chặn theo điểm ước lượng — đổi sang chặn theo cận dưới sẽ làm mọi cổng
    trượt trên bộ eval nhỏ, và một cổng lúc nào cũng đỏ thì bị tắt.

    Nhưng khi khoảng tin cậy VẮT QUA ngưỡng thì kết quả pass/fail ấy không phân
    biệt được với ngẫu nhiên, và người đọc phải biết điều đó trước khi đi sửa
    model. Trả về (qua_khong, ghi_chu).
    """
    qua = ty_le.ty_le >= nguong
    if ty_le.n == 0:
        return qua, "n=0 — không đo được gì"
    if ty_le.thap <= nguong <= ty_le.cao:
        return qua, (
            f"⚠ KHÔNG PHÂN BIỆT ĐƯỢC với ngưỡng {nguong:.0%}: khoảng tin cậy "
            f"[{ty_le.thap:.0%}–{ty_le.cao:.0%}] vắt qua nó. n={ty_le.n} quá nhỏ "
            f"để kết luận — {'qua' if qua else 'trượt'} lần này có thể chỉ là nhiễu"
        )
    return qua, ""


__all__ = ["Khoang", "SoCap", "cong_chan", "mcnemar", "wilson"]
