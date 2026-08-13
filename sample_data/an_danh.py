"""
sample_data/an_danh.py — sinh bộ dữ liệu eval ẨN DANH từ bản xuất MISA thật.

VÌ SAO
------
Bộ eval kế toán cần chạy trên dữ liệu THẬT: những thứ đáng giá nhất đã tìm ra
(sửa hồi tố 108 lít, 157 mã sai diện thuế, tập trung 66% phải thu) đều không
dựng lại được bằng dữ liệu bịa. Nhưng bốn file gốc chứa **tên khách hàng, mã số
thuế và số tiền từng người đang nợ** — đẩy lên GitHub là đưa danh sách khách của
Hoàng Phát cho bên thứ ba giữ (P2).

Script này tách hai thứ đó ra: **giữ mọi thuộc tính phép kiểm dựa vào**, thay
mọi thứ nhận dạng được người thật.

    GIỮ NGUYÊN            mã hàng · tên hàng · mọi con số tiền và số lượng ·
                          ngày kỳ · tên kho · cấu trúc bảng · dạng tên pháp nhân
                          ("CÔNG TY TNHH ...") · dạng mã số thuế (10 / 13 / 12 số)

    THAY HẾT              tên công ty · tên người · địa chỉ · số điện thoại ·
                          giá trị mã số thuế · tên và mã số thuế của chính DN

TÊN THƯƠNG HIỆU TRONG TÊN HÀNG THÌ GIỮ
--------------------------------------
"Mỡ bôi trơn ... hiệu ANOPEC", "Dầu Caltex Rando HD 46" — đây là TÊN MẶT HÀNG,
không phải danh tính đối tác, và chúng là thứ bảng tra thuế đọc. Trùng hợp là
ANOPEC vừa là thương hiệu vừa là tên một nhà cung cấp; bản ghi nhà cung cấp đó
ĐÃ được thay tên, chỉ tên hàng giữ nguyên. Thay nốt cả tên hàng thì bộ eval
thuế mất đúng thứ nó cần đo, đổi lại một mức riêng tư mà hàng hoá bán công khai
vốn không có.

Mã số thuế thay thế được sinh sao cho **vẫn đúng số kiểm tra** — nếu không thì
`test_receivables` sẽ thấy một loạt mã sai và đo nhầm hoàn toàn.

ĐẦU RA LÀ LƯỚI Ô, KHÔNG PHẢI .XLSX
----------------------------------
Xuất `list[list]` dạng JSON để test nạp thẳng vào `parse_inventory_table` /
`parse_partner_table` / `parse_product_table`. Ba cái lợi: trình đọc bảng vẫn
được kiểm (đó mới là chỗ hay hỏng), file đọc và soát được trong git thay vì nhị
phân, và test không cần openpyxl.

CHẠY
----
    python sample_data/an_danh.py                   # đọc từ ~/Downloads
    python sample_data/an_danh.py --nguon <thư_mục>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

GOC_DU_AN = Path(__file__).resolve().parent.parent
RA = GOC_DU_AN / "tests" / "du_lieu_eval"

TEP = {
    "ton_kho_24_07": "Tong_hop_ton_kho-Hoàng-Phát-Kho-HH-24-07.xlsx",
    "ton_kho_11_08": "Tong_hop_ton_kho-37.xlsx",
    "ton_kho_km_24_07": "Tong_hop_ton_kho-Hoàng-Phát-Kho-KM-24-07.xlsx",
    "hang_hoa": "Danh_sach_hang_hoa_dich_vu.xlsx",
    "khach_hang": "Danh_sach_khach_hang.xlsx",
    "nha_cung_cap": "Danh_sach_nha_cung_cap.xlsx",
}

_TRONG_SO = (31, 29, 23, 19, 17, 13, 7, 5, 3)

# Tiền tố pháp nhân phải GIỮ: `Partner.la_phap_nhan()` dựa vào chúng để biết
# thiếu mã số thuế có phải lỗi không.
_TIEN_TO = (
    "CÔNG TY CỔ PHẦN", "CÔNG TY TNHH MỘT THÀNH VIÊN", "CÔNG TY TNHH",
    "CHI NHÁNH CÔNG TY CỔ PHẦN", "CHI NHÁNH CÔNG TY TNHH", "CHI NHÁNH",
    "HỢP TÁC XÃ", "DOANH NGHIỆP", "TỔNG CÔNG TY", "TRUNG TÂM", "HỘ KINH DOANH",
)

_TU_DAT_TEN = [
    "AN BÌNH", "BẢO LONG", "CAO NGUYÊN", "ĐẠI DƯƠNG", "ĐÔNG PHONG", "GIA HUY",
    "HÀ GIANG", "HOÀNG SƠN", "KIM LONG", "LẠC VIỆT", "MINH KHÔI", "NAM PHONG",
    "PHÚ THÀNH", "QUANG MINH", "SAO MAI", "TÂN TIẾN", "THIÊN LONG", "TRƯỜNG AN",
    "VẠN XUÂN", "VIỆT TIẾN", "XUÂN HOÀ", "YÊN BÁI", "BÌNH MINH", "CHÍ CÔNG",
]
_HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Ngô"]
_DEM = ["Văn", "Thị", "Đức", "Minh", "Quang", "Hải", "Thanh", "Xuân", "Hữu"]
_TEN = ["An", "Bình", "Cường", "Dũng", "Hà", "Khánh", "Lâm", "Nam", "Phúc", "Sơn"]


def _so_kiem_tra(chin_so: str) -> int:
    return 10 - (sum(int(chin_so[i]) * _TRONG_SO[i] for i in range(9)) % 11)


class KhoTen:
    """Ánh xạ ổn định: cùng một giá trị gốc luôn ra cùng một giá trị giả.

    Ổn định là điều kiện bắt buộc — đối tác KH00021 nằm ở CẢ hai danh sách, và
    phép kiểm "vừa mua vừa bán" gộp theo mã số thuế. Sinh hai mã khác nhau cho
    cùng một pháp nhân là làm phép kiểm đó im lặng.
    """

    def __init__(self) -> None:
        self.ten: dict[str, str] = {}
        self.mst: dict[str, str] = {}
        self._i_ten = 0
        self._i_nguoi = 0
        self._i_mst = 0

    def doi_ten(self, goc: str) -> str:
        goc = (goc or "").strip()
        if not goc:
            return ""
        if goc in self.ten:
            return self.ten[goc]

        tren = goc.upper()
        tien_to = next((t for t in _TIEN_TO if tren.startswith(t)), None)
        if tien_to:
            tu = _TU_DAT_TEN[self._i_ten % len(_TU_DAT_TEN)]
            so = self._i_ten // len(_TU_DAT_TEN)
            self._i_ten += 1
            moi = f"{tien_to} {tu}" + (f" {so + 1}" if so else "")
        else:
            i = self._i_nguoi
            self._i_nguoi += 1
            moi = (f"{_HO[i % len(_HO)]} {_DEM[(i // len(_HO)) % len(_DEM)]} "
                   f"{_TEN[(i // 7) % len(_TEN)]}")
            if i >= len(_HO) * len(_DEM):
                moi += f" {i}"
        self.ten[goc] = moi
        return moi

    def doi_mst(self, goc: Any) -> str:
        """Sinh mã thay thế GIỮ NGUYÊN DẠNG và vẫn đúng số kiểm tra."""
        s = re.sub(r"[\s.]", "", str(goc or "")).strip()
        if not s:
            return ""
        if s in self.mst:
            return self.mst[s]

        m = re.fullmatch(r"(\d{10})[-]?(\d{3})?", s)
        if m:
            moi = self._muoi_so()
            if m.group(2):
                moi = f"{moi}-{m.group(2)}"
        elif re.fullmatch(r"\d{12}", s):
            # Số định danh cá nhân — không có số kiểm tra, chỉ cần 12 chữ số.
            self._i_mst += 1
            moi = f"{(700000000000 + self._i_mst * 7919) % 1000000000000:012d}"
        else:
            moi = s          # dạng lạ thì giữ nguyên để vẫn kiểm được nhánh đó
        self.mst[s] = moi
        return moi

    def _muoi_so(self) -> str:
        while True:
            self._i_mst += 1
            chin = f"{(310000000 + self._i_mst * 104729) % 1000000000:09d}"
            kt = _so_kiem_tra(chin)
            if 0 <= kt <= 9:
                return chin + str(kt)


def _doc_luoi(path: Path) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _dong_tieu_de(luoi: list[list[Any]]) -> int:
    """Chỉ số dòng tiêu đề — mọi dòng DƯỚI nó là dữ liệu, tuyệt đối không đụng."""
    for i, row in enumerate(luoi[:30]):
        o = [str(c or "").strip().lower() for c in row]
        if any(t == "mã" or t.startswith("mã hàng") or t.startswith("mã khách")
               or t.startswith("mã nhà cung cấp") for t in o):
            return i
    return 0


def _sach_dong_dau(luoi: list[list[Any]], kho: KhoTen) -> None:
    """
    Xoá tên và mã số thuế của CHÍNH doanh nghiệp ở phần đầu bản xuất.

    CHỈ quét phần TRÊN dòng tiêu đề. Bản đầu quét cứng 8 dòng đầu, và trong file
    danh mục hàng hoá thì dòng 5–7 đã là HÀNG THẬT: quy tắc nhận địa chỉ khớp
    vào "Dầu nhớt động cơ xe máy 4 kỳ..." (vì có "4 ") rồi thay tên ba mặt hàng
    bằng "Địa chỉ đã ẩn". Bảng tra thuế tụt từ 157 xuống 154 mã — một bộ eval
    tự làm hỏng dữ liệu của chính nó, và sẽ đo ra con số thấp hơn sự thật mãi
    mãi mà không ai biết vì sao.
    """
    for r in range(_dong_tieu_de(luoi)):
        for c, o in enumerate(luoi[r]):
            if not isinstance(o, str):
                continue
            t = o.strip()
            if t.upper().startswith(("CÔNG TY", "CHI NHÁNH")):
                luoi[r][c] = kho.doi_ten(t)
            elif t.lower().startswith("mã số thuế"):
                luoi[r][c] = "Mã số thuế: " + kho.doi_mst(re.sub(r"\D", "", t))
            elif re.search(r"\d{1,4}\s|ngõ|ngách|đường|phố|phường|quận|xã|huyện",
                           t, re.IGNORECASE) and "ngày" not in t.lower():
                luoi[r][c] = "Địa chỉ đã ẩn"


def an_danh_doi_tac(luoi: list[list[Any]], kho: KhoTen) -> list[list[Any]]:
    """Bảng khách hàng / nhà cung cấp: cột Tên, Địa chỉ, Mã số thuế, Điện thoại."""
    ra = [list(r) for r in luoi]
    i_hdr = next(i for i, r in enumerate(ra)
                 if any(str(c or "").strip().lower().startswith("mã ") for c in r))
    cot = {str(c or "").strip().lower(): i for i, c in enumerate(ra[i_hdr])}
    i_ten = next((i for k, i in cot.items() if k.startswith("tên")), None)
    i_dc = next((i for k, i in cot.items() if k.startswith("địa chỉ")), None)
    i_mst = next((i for k, i in cot.items() if k.startswith("mã số thuế")), None)
    i_dt = next((i for k, i in cot.items() if k.startswith("điện thoại")), None)

    for r in ra[i_hdr + 1:]:
        if i_ten is not None and i_ten < len(r) and isinstance(r[i_ten], str):
            if r[i_ten].strip().lower() not in ("", "tổng"):
                r[i_ten] = kho.doi_ten(r[i_ten])
        if i_dc is not None and i_dc < len(r) and r[i_dc]:
            r[i_dc] = "Địa chỉ đã ẩn"
        if i_mst is not None and i_mst < len(r) and r[i_mst]:
            r[i_mst] = kho.doi_mst(r[i_mst])
        if i_dt is not None and i_dt < len(r) and r[i_dt]:
            r[i_dt] = "0900000000"
    ra[0] = [str(ra[0][0] or "")] + [""] * (len(ra[0]) - 1)
    return ra


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sinh bộ eval ẩn danh từ bản xuất MISA")
    p.add_argument("--nguon", default=str(Path.home() / "Downloads"))
    p.add_argument("--ra", default=str(RA))
    a = p.parse_args(argv)

    nguon, ra_dir = Path(a.nguon), Path(a.ra)
    ra_dir.mkdir(parents=True, exist_ok=True)
    kho = KhoTen()

    thieu = [t for t in TEP.values() if not (nguon / t).exists()]
    if thieu:
        print(f"Thiếu file trong {nguon}:", *thieu, sep="\n  ")
        return 1

    # Đối tác TRƯỚC: để mã số thuế và tên của chúng vào kho ánh xạ, rồi các file
    # sau tham chiếu lại đúng giá trị đó.
    for ten, tep in (("khach_hang", TEP["khach_hang"]),
                     ("nha_cung_cap", TEP["nha_cung_cap"])):
        luoi = an_danh_doi_tac(_doc_luoi(nguon / tep), kho)
        (ra_dir / f"{ten}.json").write_text(
            json.dumps(luoi, ensure_ascii=False, indent=1, default=str) + "\n",
            encoding="utf-8")
        print(f"  {ten}.json  ({len(luoi)} dòng)")

    for ten in ("ton_kho_24_07", "ton_kho_11_08", "ton_kho_km_24_07", "hang_hoa"):
        luoi = _doc_luoi(nguon / TEP[ten])
        _sach_dong_dau(luoi, kho)
        (ra_dir / f"{ten}.json").write_text(
            json.dumps(luoi, ensure_ascii=False, indent=1, default=str) + "\n",
            encoding="utf-8")
        print(f"  {ten}.json  ({len(luoi)} dòng)")

    print(f"\nĐã thay {len(kho.ten)} tên và {len(kho.mst)} mã số thuế.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
