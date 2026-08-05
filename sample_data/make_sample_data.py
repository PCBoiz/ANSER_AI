"""
sample_data/make_sample_data.py — dựng bảng tồn kho MẪU để chạy thử nội bộ.

VÌ SAO CÓ FILE NÀY
------------------
Dữ liệu thật của Hoàng Phát còn vài ngày nữa mới về, nhưng buổi chạy thử nội bộ
không đợi được. Vấn đề của mọi dữ liệu giả là nó dễ dãi: dựng đại một bảng đẹp
thì bộ soi lỗi không tìm ra gì, và ta kết luận nhầm rằng "chạy tốt".

Nên bảng này GIEO LỖI CÓ CHỦ ĐÍCH — mỗi lỗi ứng với đúng một phép kiểm trong
`core/inventory.py`. Danh sách lỗi gieo nằm ở `LOI_GIEO` ngay dưới, và
`tests/test_sample_data.py` chạy bộ soi lên chính file này rồi đối chiếu: thiếu
một lỗi là bộ soi hỏng, thừa một lỗi là bộ soi báo oan. Bảng mẫu vì vậy vừa là
dữ liệu chạy thử vừa là đề bài có đáp án.

ĐỊNH DẠNG
---------
Bắt chước bản xuất "Tổng hợp Nhập - Xuất - Tồn" của MISA kiểu A: tên nhóm (Đầu
kỳ / Nhập kho / Xuất kho / Cuối kỳ) nằm CÙNG dòng với "Mã hàng", tên cột con ở
dòng kế tiếp, và ô gộp để trống các cột sau. Đúng thứ `inventory_import.py`
phải xử lý, chứ không phải một bảng phẳng cho dễ.

Hàng hoá lấy theo ngành của khách: dầu nhờn, mỡ bò, dung dịch làm mát.

CHẠY
----
    python sample_data/make_sample_data.py
-> sample_data/ton_kho_mau.xlsx
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

KY_TU = "01/01/2026"
KY_DEN = "30/06/2026"      # 181 ngày — vượt ngưỡng 90 ngày của phép kiểm hàng chết
KHO = "Kho Hà Nội"


@dataclass
class Dong:
    code: str
    name: str
    unit: str
    opening_qty: float
    opening_value: float
    in_qty: float
    in_value: float
    out_qty: float
    out_value: float
    # Chỉ điền khi CỐ Ý phá cân đối; bỏ trống thì tự tính ĐK + N − X.
    closing_qty: float | None = None
    closing_value: float | None = None
    # Ghi số dạng chuỗi kiểu Việt Nam ("1.234.567") thay vì số — bản xuất thật
    # đôi khi ra như vậy, và đó là lúc `parse_vn_number` phải làm việc.
    chuoi_viet: bool = False
    loi_gieo: tuple[str, ...] = field(default_factory=tuple)

    def ck_qty(self) -> float:
        if self.closing_qty is not None:
            return self.closing_qty
        return self.opening_qty + self.in_qty - self.out_qty

    def ck_value(self) -> float:
        if self.closing_value is not None:
            return self.closing_value
        return self.opening_value + self.in_value - self.out_value


def _dv(qty: float, value: float) -> float:
    return value / qty if qty else 0.0


# ---------------------------------------------------------------------------
# Các dòng SẠCH — phải không sinh phát hiện nào
# ---------------------------------------------------------------------------

_SACH = [
    Dong("DN-CF4-200", "Dầu động cơ Diesel CF-4 15W40 phuy 200L", "phuy",
         20, 84_000_000, 40, 172_000_000, 45, 191_250_000),
    Dong("DN-SG-18", "Dầu động cơ xăng SG 20W50 can 18L", "can",
         60, 21_600_000, 120, 44_400_000, 140, 51_100_000),
    Dong("DN-TL-46", "Dầu thuỷ lực AW46 can 18L", "can",
         80, 24_000_000, 150, 45_750_000, 170, 51_425_000,
         chuoi_viet=True),
    Dong("DN-PHANH-1", "Dầu phanh DOT4 chai 1L", "chai",
         300, 21_000_000, 600, 43_200_000, 700, 49_700_000),
]

# ---------------------------------------------------------------------------
# Các dòng GIEO LỖI — mỗi dòng nhắm đúng một phép kiểm
# ---------------------------------------------------------------------------

_GIEO = [
    # Xuất 18 trong khi chỉ có 15 -> tồn cuối âm. Ngoài đời thường do thiếu
    # phiếu nhập chưa vào sổ, hoặc sai quy đổi phuy <-> lít.
    Dong("DN-TL-200", "Dầu thuỷ lực AW46 phuy 200L", "phuy",
         5, 16_500_000, 10, 33_500_000, 18, 59_400_000,
         loi_gieo=("negative_stock",)),

    # Hàng khuyến mại nhà cung cấp giao kèm: có số lượng, không ghi đồng nào.
    # Xuất 120/200 để tồn còn đủ bán ~4 tháng — nếu để tồn đủ bán quá 1 năm thì
    # dòng này dính THÊM cờ "bán chậm", và đề bài mất tính một-lỗi-một-dòng.
    Dong("KM-4T-08", "Nhớt xe máy 4T 0.8L (hàng khuyến mại)", "chai",
         0, 0, 200, 0, 120, 0,
         loi_gieo=("zero_valued_stock",)),

    # Giá nhập nhảy 20% so với giá tồn đầu kỳ.
    # Giá trị xuất tính theo BÌNH QUÂN GIA QUYỀN (40.800.000 / 42 xô) để đơn giá
    # tồn cuối bằng đơn giá đã bán — nếu không, dòng này dính thêm cờ "giá vốn
    # hàng tồn cao hơn hàng đã bán", vốn là hệ quả của cách tính chứ không phải
    # của giá nhập tăng.
    Dong("MO-EP2-15", "Mỡ bò chịu nhiệt EP2 xô 15kg", "xô",
         12, 10_200_000, 30, 30_600_000, 25, 24_285_714,
         loi_gieo=("price_jump",)),

    # Nhập một lần rồi nằm im suốt kỳ.
    Dong("DN-CAT-20", "Dầu cắt gọt kim loại can 20L", "can",
         30, 19_500_000, 0, 0, 0, 0,
         loi_gieo=("dead_stock",)),

    # Bán nhỏ giọt trong khi tồn đủ dùng nhiều năm.
    Dong("LC-COOL-200", "Dung dịch làm mát phuy 200L", "phuy",
         320, 128_000_000, 0, 0, 20, 8_000_000,
         loi_gieo=("slow_moving",)),

    # Hàng còn trong kho đắt hơn hàng vừa bán -> biên kỳ sau hẹp lại.
    # KHÔNG phải lỗi sổ sách; là cảnh báo cho kỳ sau.
    Dong("DN-GL5-18", "Dầu hộp số GL-5 90 can 18L", "can",
         10, 10_000_000, 20, 21_600_000, 15, 15_000_000,
         loi_gieo=("rising_cost_basis",)),

    # Tồn cuối ghi 20 trong khi 10 + 25 − 23 = 12. Bản xuất bị sửa tay.
    # Giá trị ghi theo ĐÚNG đơn giá đã bán (20 × 900.000) để lệch chỉ nằm ở chỗ
    # cân đối. Nếu để giá trị tự tính thì đơn giá tồn cuối tụt còn 565.000 và
    # dòng này dính thêm cờ "giá vốn hàng tồn giảm" — một hệ quả của con số bịa,
    # không phải một lỗi thứ hai.
    Dong("DN-BR-18", "Dầu bánh răng công nghiệp can 18L", "can",
         10, 9_000_000, 25, 23_000_000, 23, 20_700_000,
         closing_qty=20, closing_value=18_000_000,
         loi_gieo=("balance_mismatch",)),
]

DONG = _SACH + _GIEO

# Đáp án. `tests/test_sample_data.py` đối chiếu với kết quả soi thật.
LOI_GIEO: dict[str, tuple[str, ...]] = {d.code: d.loi_gieo for d in DONG if d.loi_gieo}


# ---------------------------------------------------------------------------
# Ghi file
# ---------------------------------------------------------------------------

def _so(value: float, kieu_chuoi: bool) -> object:
    """Số thật, hoặc chuỗi định dạng Việt Nam khi muốn thử bộ đọc số."""
    if not kieu_chuoi:
        return round(value, 2)
    nguyen = f"{abs(value):,.0f}".replace(",", ".")
    return f"-{nguyen}" if value < 0 else nguyen


def bang() -> list[list[object]]:
    """Ma trận ô, đúng bố cục MISA kiểu A."""
    rows: list[list[object]] = [
        ["CÔNG TY TNHH THƯƠNG MẠI VÀ VẬN TẢI HOÀNG PHÁT"],
        ["MST: 0109527605"],
        [],
        ["BẢNG TỔNG HỢP NHẬP - XUẤT - TỒN"],
        [f"Từ ngày {KY_TU} đến ngày {KY_DEN}"],
        [],
    ]
    # Ô gộp: tên nhóm chỉ xuất hiện ở cột ĐẦU của nhóm, các cột sau để trống —
    # `_build_columns` phải tự kéo sang phải. Bỏ chi tiết này là dựng một bài
    # dễ hơn thực tế, và bài dễ thì không kiểm được gì.
    rows.append(
        ["Tên kho", "Mã hàng", "Tên hàng", "ĐVT",
         "Đầu kỳ", "", "", "Nhập kho", "", "", "Xuất kho", "", "", "Cuối kỳ", "", ""]
    )
    rows.append(
        ["", "", "", ""]
        + ["Số lượng", "Giá trị", "Đơn giá BQ"] * 4
    )

    for d in DONG:
        ck_q, ck_v = d.ck_qty(), d.ck_value()
        rows.append([
            KHO, d.code, d.name, d.unit,
            _so(d.opening_qty, d.chuoi_viet), _so(d.opening_value, d.chuoi_viet),
            _so(_dv(d.opening_qty, d.opening_value), d.chuoi_viet),
            _so(d.in_qty, d.chuoi_viet), _so(d.in_value, d.chuoi_viet),
            _so(_dv(d.in_qty, d.in_value), d.chuoi_viet),
            _so(d.out_qty, d.chuoi_viet), _so(d.out_value, d.chuoi_viet),
            _so(_dv(d.out_qty, d.out_value), d.chuoi_viet),
            _so(ck_q, d.chuoi_viet), _so(ck_v, d.chuoi_viet),
            _so(_dv(ck_q, ck_v), d.chuoi_viet),
        ])

    rows.append([])
    rows.append(["", "", "Tổng cộng", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    return rows


def ghi_xlsx(path: Path) -> Path:
    try:
        from openpyxl import Workbook
    except ImportError:
        sys.exit("Thiếu openpyxl. Chạy: pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "Tong hop NXT"
    for row in bang():
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> None:
    path = ghi_xlsx(Path(__file__).parent / "ton_kho_mau.xlsx")
    print(f"Đã ghi: {path}")
    print(f"  {len(DONG)} mã hàng, kỳ {KY_TU} – {KY_DEN}")
    print(f"  {len(LOI_GIEO)} mã có lỗi gieo sẵn:")
    for code, loi in LOI_GIEO.items():
        print(f"    {code:14s} {', '.join(loi)}")
    print("\nTải file này lên mục Tồn kho bên Body để chạy thử bộ soi lỗi sổ sách.")


if __name__ == "__main__":
    main()
