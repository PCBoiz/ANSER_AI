"""
src/core/vat_catalog.py — danh mục hàng hoá và THUẾ SUẤT GTGT 8% hay 10%.

CĂN CỨ
------
Nghị quyết 204/2025/QH15 (17/6/2025) và Nghị định 174/2025/NĐ-CP: giảm 2% thuế
GTGT cho nhóm đang chịu 10%, áp dụng **01/7/2025 → 31/12/2026**.

Danh mục KHÔNG được giảm, giữ nguyên 10%:

    viễn thông · tài chính, ngân hàng, chứng khoán, bảo hiểm · kinh doanh bất
    động sản · sản phẩm kim loại · sản phẩm khai khoáng (trừ than) · hàng hoá
    dịch vụ chịu thuế tiêu thụ đặc biệt (TRỪ XĂNG)

So với Nghị định 180/2024/NĐ-CP trước đó, bản mới đã **bỏ khỏi danh mục loại
trừ**: than, sản phẩm dầu mỏ tinh chế (xăng, nhiên liệu dầu, **dầu mỡ bôi
trơn**, khí dầu mỏ), sản phẩm hoá chất, kim loại đúc sẵn, hàng hoá dịch vụ
công nghệ thông tin.

Nghĩa là dầu nhớt — toàn bộ mặt hàng của Hoàng Phát — **được giảm còn 8%** kể
từ 01/7/2025, trong khi trước đó chịu 10%. Đây là thay đổi dễ bỏ sót nhất vì
nó đi ngược thói quen nhiều năm.

BA MỨC KẾT LUẬN, KHÔNG PHẢI HAI
-------------------------------
`CHUA_XAC_DINH` là kết luận hợp lệ và là mặc định. Một bảng tra đoán bừa còn
tệ hơn không có bảng tra: đoán 8% cho mặt hàng thực ra 10% thì doanh nghiệp bị
truy thu và phạt. Vì vậy quy tắc loại trừ luôn được xét TRƯỚC quy tắc giảm.

Module này không quyết định thay kế toán. Mỗi kết luận đều kèm `can_cu` để
người có thẩm quyền kiểm lại, và mọi phát hiện đều nhắc phải xác nhận.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

from src.core.findings import finding, sap_xep
from src.core.inventory_import import parse_vn_number
from src.core.utils import bo_dau

HIEU_LUC_TU = "2025-07-01"
HIEU_LUC_DEN = "2026-12-31"
CAN_CU_CHUNG = "Nghị quyết 204/2025/QH15 và Nghị định 174/2025/NĐ-CP"

DUOC_GIAM = "được giảm 8%"
KHONG_GIAM = "không được giảm, giữ 10%"
CHUA_XAC_DINH = "chưa xác định"

# Giá trị MISA ghi ở cột 'Giảm 2% thuế suất thuế GTGT' khi chưa ai gắn cờ.
_CHUA_GAN_CO = {"chua xac dinh", "", "khong xac dinh"}


@dataclass
class SanPham:
    """Một dòng của DANH SÁCH HÀNG HOÁ, DỊCH VỤ."""
    code: str
    name: str = ""
    vat_flag: str = ""          # cột 'Giảm 2% thuế suất thuế GTGT' của MISA
    group: str = ""             # 'HH' / 'DV' / rỗng
    unit: str = ""
    qty: Optional[float] = None
    value: Optional[float] = None

    def label(self) -> str:
        return f"{self.code} {self.name}".strip()

    def chua_gan_co(self) -> bool:
        return bo_dau(self.vat_flag) in _CHUA_GAN_CO


@dataclass
class KetLuanThue:
    ket_luan: str = CHUA_XAC_DINH
    can_cu: str = ""
    tu_khoa: str = ""

    @property
    def chac_chan(self) -> bool:
        return self.ket_luan != CHUA_XAC_DINH


# ---------------------------------------------------------------------------
# Bảng tra. Thứ tự trong mỗi danh sách không quan trọng; thứ tự GIỮA hai danh
# sách thì có: loại trừ luôn được xét trước.
# ---------------------------------------------------------------------------

# (regex trên tên đã bỏ dấu, căn cứ)
_LOAI_TRU: tuple[tuple[str, str], ...] = (
    (r"\b(sat thep|thep|inox|nhom thoi|kim loai|ton (lanh|mau)|phoi thep|gang duc)\b",
     "Sản phẩm kim loại — không thuộc diện giảm"),
    (r"\b(quang|da xay dung|cat xay dung|soi xay dung|khai khoang)\b",
     "Sản phẩm khai khoáng (trừ than) — không thuộc diện giảm"),
    (r"\b(ruou|bia|thuoc la|xi ga|bai la|vang ma|hang ma)\b",
     "Hàng chịu thuế tiêu thụ đặc biệt — không thuộc diện giảm"),
    (r"\b(dieu hoa nhiet do|dieu hoa khong khi)\b",
     "Điều hoà công suất từ 90.000 BTU trở xuống chịu thuế TTĐB — cần xác nhận công suất"),
    (r"\b(vien thong|cuoc dien thoai|internet|3g|4g|5g)\b",
     "Dịch vụ viễn thông — không thuộc diện giảm"),
    (r"\b(bao hiem|chung khoan|ngan hang|tin dung|cho vay)\b",
     "Tài chính, ngân hàng, chứng khoán, bảo hiểm — không thuộc diện giảm"),
    (r"\b(bat dong san|cho thue van phong|chuyen nhuong quyen su dung dat)\b",
     "Kinh doanh bất động sản — không thuộc diện giảm"),
)

_DUOC_GIAM: tuple[tuple[str, str], ...] = (
    (r"\b(dau (nhot|nhon|boi tron|dong co|truyen dong|thuy luc|phanh|cau|hop so|"
     r"banh rang|cong nghiep|cat got|tro luc|chong gi|chong ri|ranh truot|may nen|"
     r"tuan hoan|bien the|lam mat|nhiet|gia nhiet|may khau|xich)|mo boi tron|"
     r"dau mo boi tron|nhot)\b",
     "Dầu mỡ bôi trơn — Nghị định 174/2025 đã bỏ 'sản phẩm dầu mỏ tinh chế' khỏi "
     "danh mục loại trừ"),
    # Tên chỉ có 'Dầu <hãng/mã>' — Dầu Caltex Rando HD 46, Dầu TL AW68, Dầu
    # Mobilgear 600 XP. Loại trừ tường minh dầu thực phẩm và dầu mỹ phẩm để quy
    # tắc này không đi lạc sang danh mục của ngành khác.
    # `\b` sau nhóm loại trừ là bắt buộc: thiếu nó thì 'ca' khớp vào 'Caltex' và
    # toàn bộ dòng hàng Caltex bị đẩy sang diện phải hỏi người.
    (r"^dau\b(?!\s+(?:an|ca|dua|oliu|me|lac|hao|giam|goi|tam|xa|thuc vat|com|phong)\b)",
     "Sản phẩm dầu mỏ tinh chế — thuộc diện được giảm từ 01/7/2025 "
     "(Nghị định 174/2025 bỏ khỏi danh mục loại trừ)"),
    (r"^mo\b(?!\s+(?:heo|lon|bo|ga|ca|dong vat|thuc pham)\b)",
     "Mỡ bôi trơn — thuộc nhóm dầu mỡ bôi trơn được giảm từ 01/7/2025"),
    (r"\b(xang|nhien lieu dau|dau diesel|dau do|khi dau mo|gas cong nghiep)\b",
     "Xăng và sản phẩm dầu mỏ tinh chế — thuộc diện được giảm từ 01/7/2025"),
    (r"\b(than (cam|da|to ong|cui)|than$)\b",
     "Than — thuộc diện được giảm"),
    (r"\b(cuoc van chuyen|van chuyen|van tai|boc xep|luu kho|logistics)\b",
     "Dịch vụ vận tải, bốc xếp — thuộc nhóm đang chịu 10%, được giảm"),
    (r"\b(dung dich (lam mat|lam sach|ve sinh|tay rua)|nuoc lam mat|dung moi|"
     r"hoa chat|phu gia|nuoc rua)\b",
     "Sản phẩm hoá chất — Nghị định 174/2025 đã bỏ khỏi danh mục loại trừ"),
    (r"\b(quat dien|quat|ao (mua|khoac|phong|thun)|mu (vai|luoi|bao hiem)|gang tay|"
     r"tui (deo|xach|vai)|binh giu nhiet|ban ghe|bao tay|gie lau|thung nhua|"
     r"can nhua|xo (nhua|da)|phuy|luoi chong chuot)\b",
     "Hàng hoá thông thường đang chịu thuế suất 10% — thuộc diện được giảm"),
)

# Không phải hàng hoá dịch vụ bán ra — không có thuế suất để bàn.
_KHONG_PHAI_HANG_HOA = re.compile(r"^(chi phi|cp )|^(chiet khau|giam gia)\b")

_LOAI_TRU_C = tuple((re.compile(p), c) for p, c in _LOAI_TRU)
_DUOC_GIAM_C = tuple((re.compile(p), c) for p, c in _DUOC_GIAM)


def phan_loai_thue_suat(ten: str, nhom: str = "") -> KetLuanThue:
    """
    Tra một tên hàng ra kết luận thuế suất.

    Xét loại trừ trước: nhầm sang 10% chỉ khiến hoá đơn đắt hơn và phải điều
    chỉnh; nhầm sang 8% thì bị truy thu cộng tiền chậm nộp. Hai sai lầm không
    cùng giá.
    """
    text = bo_dau(f"{ten} {nhom}")
    if not text.strip():
        return KetLuanThue()

    for rx, can_cu in _LOAI_TRU_C:
        if (m := rx.search(text)):
            return KetLuanThue(KHONG_GIAM, f"{can_cu} ({CAN_CU_CHUNG})", m.group(0))
    for rx, can_cu in _DUOC_GIAM_C:
        if (m := rx.search(text)):
            return KetLuanThue(DUOC_GIAM, f"{can_cu} ({CAN_CU_CHUNG})", m.group(0))
    return KetLuanThue()


# ---------------------------------------------------------------------------
# Soi cả danh mục
# ---------------------------------------------------------------------------

def audit_vat_catalog(san_pham: list[SanPham]) -> dict[str, Any]:
    """
    Đối chiếu cờ thuế trong MISA với bảng tra.

    Ba loại phát hiện, không loại nào tự kết luận thay kế toán:

    * cả danh mục chưa ai gắn cờ  — một phát hiện chung, vì báo riêng từng mã
      trên 161 dòng thì không ai đọc
    * mã chưa gắn cờ mà tra được  — kèm đề xuất và căn cứ
    * mã tra không ra             — nói thẳng là cần người xác nhận
    """
    fs: list[dict[str, Any]] = []
    bo_qua = [p for p in san_pham if _KHONG_PHAI_HANG_HOA.match(bo_dau(p.name))]
    san_pham = [p for p in san_pham if p not in bo_qua]
    chua_co = [p for p in san_pham if p.chua_gan_co()]
    dem = {DUOC_GIAM: 0, KHONG_GIAM: 0, CHUA_XAC_DINH: 0}
    can_nguoi: list[SanPham] = []
    de_xuat_8: list[SanPham] = []

    for p in san_pham:
        kl = phan_loai_thue_suat(p.name, p.group)
        dem[kl.ket_luan] += 1
        if not p.chua_gan_co():
            continue
        if kl.ket_luan == DUOC_GIAM:
            de_xuat_8.append(p)
        elif kl.ket_luan == CHUA_XAC_DINH:
            can_nguoi.append(p)
        else:
            fs.append(finding(
                "vat_rate_review", "cao",
                "Mã chưa gắn cờ thuế và có dấu hiệu KHÔNG được giảm",
                {"tên_hàng": p.name, "cờ_trong_misa": p.vat_flag or None,
                 "từ_khoá_khớp": kl.tu_khoa, "căn_cứ": kl.can_cu},
                "Nếu đang xuất hoá đơn 8% cho mã này thì có rủi ro bị truy thu. "
                "Kế toán xác nhận trước khi xuất hoá đơn tiếp theo.",
                code=p.code, product=p.label(),
            ))

    if chua_co and len(chua_co) == len(san_pham) and san_pham:
        fs.append(finding(
            "vat_flag_unset_all", "cao",
            f"Toàn bộ {len(san_pham)} mã đều để cờ thuế 'Chưa xác định'",
            {"số_mã": len(san_pham),
             "hiệu_lực_giảm_thuế": f"{HIEU_LUC_TU} → {HIEU_LUC_DEN}",
             "căn_cứ": CAN_CU_CHUNG,
             "tra_được_là_8%": len(de_xuat_8),
             "tra_được_là_10%": dem[KHONG_GIAM],
             "cần_người_xác_nhận": len(can_nguoi)},
            "Chưa mã nào được gắn cờ nên phần mềm không tự áp thuế suất — thuế suất "
            "đang do người nhập chọn tay trên từng hoá đơn, mỗi lần một khác được. "
            "Gắn cờ cho cả danh mục để phần mềm tự áp và tự chặn.",
        ))
    elif chua_co:
        fs.append(finding(
            "vat_flag_unset", "trung bình",
            f"{len(chua_co)}/{len(san_pham)} mã chưa gắn cờ thuế suất",
            {"các_mã": [p.code for p in chua_co[:20]], "tổng": len(chua_co)},
            "Gắn cờ để phần mềm tự áp thuế suất thay vì chọn tay từng hoá đơn.",
        ))

    if de_xuat_8:
        fs.append(finding(
            "vat_reduction_missed", "cao",
            f"{len(de_xuat_8)} mã thuộc diện được giảm còn 8% nhưng chưa gắn cờ",
            {"số_mã": len(de_xuat_8),
             "ví_dụ": [p.label()[:60] for p in de_xuat_8[:8]],
             "hiệu_lực": f"{HIEU_LUC_TU} → {HIEU_LUC_DEN}",
             "căn_cứ": phan_loai_thue_suat(de_xuat_8[0].name, de_xuat_8[0].group).can_cu},
            "Nghị định 174/2025 đã đưa dầu mỡ bôi trơn vào diện được giảm từ 01/7/2025 "
            "— khác với các năm trước. Xuất hoá đơn 10% cho nhóm này khiến giá bán cao "
            "hơn đối thủ 2% và bên mua có quyền yêu cầu điều chỉnh hoá đơn. "
            "Kiểm tra thuế suất đang ghi trên hoá đơn bán ra rồi gắn cờ lại cho cả nhóm.",
        ))

    if can_nguoi:
        fs.append(finding(
            "vat_needs_human", "trung bình",
            f"{len(can_nguoi)} mã bảng tra không kết luận được",
            {"số_mã": len(can_nguoi), "các_mã": [p.code for p in can_nguoi[:20]],
             "ví_dụ_tên": [p.name[:50] for p in can_nguoi[:8]]},
            "Tên hàng không khớp quy tắc nào. Kế toán tra theo mã ngành sản phẩm rồi "
            "gắn cờ thủ công — đừng suy từ mã hàng gần giống.",
        ))

    return {
        "findings": sap_xep(fs),
        "summary": {
            "số_mã": len(san_pham),
            "chưa_gắn_cờ": len(chua_co),
            "tra_ra_8%": dem[DUOC_GIAM],
            "tra_ra_10%": dem[KHONG_GIAM],
            "không_tra_được": dem[CHUA_XAC_DINH],
            "hiệu_lực_từ": HIEU_LUC_TU,
            "hiệu_lực_đến": HIEU_LUC_DEN,
            "căn_cứ": CAN_CU_CHUNG,
            "lưu_ý": "Kết luận của bảng tra là ĐỀ XUẤT. Người chịu trách nhiệm "
                     "về thuế suất trên hoá đơn vẫn là kế toán của doanh nghiệp.",
        },
    }


# ---------------------------------------------------------------------------
# Nhập từ file MISA
# ---------------------------------------------------------------------------

_COT = (
    ("code", ("ma",)),
    ("name", ("ten",)),
    ("vat_flag", ("giam 2% thue suat thue gtgt", "giam 2% thue gtgt", "giam thue gtgt")),
    ("group", ("nhom vthh", "nhom vat tu hang hoa", "nhom")),
    ("unit", ("don vi tinh chinh", "don vi tinh", "dvt")),
    ("qty", ("so luong ton", "so luong")),
    ("value", ("gia tri ton", "gia tri")),
)


@dataclass
class ProductParseResult:
    products: list[SanPham] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.products) and not self.checks.get("missing_columns")


def parse_product_table(rows: list[list[Any]]) -> ProductParseResult:
    res = ProductParseResult()
    i_hdr = next(
        (i for i, r in enumerate(rows[:30])
         if any(bo_dau(c) == "ma" for c in r) and any(bo_dau(c) == "ten" for c in r)),
        None,
    )
    if i_hdr is None:
        res.checks["missing_columns"] = ["code", "name"]
        res.warnings.append("Không tìm thấy dòng tiêu đề có cột 'Mã' và 'Tên'.")
        return res

    o = [bo_dau(c) for c in rows[i_hdr]]
    hdr: dict[str, int] = {}
    dung: set[int] = set()
    cap = [(t, bd) for t, bds in _COT for bd in bds]
    cap.sort(key=lambda x: -len(x[1]))          # bí danh dài trước, để 'mã' không nuốt 'mã số...'
    for truong, bd in cap:
        if truong in hdr:
            continue
        for i, text in enumerate(o):
            if i in dung or not text:
                continue
            if text == bd or text.startswith(bd + " "):
                hdr[truong] = i
                dung.add(i)
                break

    thieu = [t for t in ("code", "name") if t not in hdr]
    if thieu:
        res.checks["missing_columns"] = thieu
        res.warnings.append(f"Thiếu cột bắt buộc: {', '.join(thieu)}.")
        return res
    res.checks["columns"] = dict(hdr)
    if "vat_flag" not in hdr:
        res.warnings.append(
            "Không có cột 'Giảm 2% thuế suất thuế GTGT' — không đối chiếu được cờ thuế."
        )

    def o_(row: list[Any], truong: str) -> Any:
        i = hdr.get(truong)
        return row[i] if i is not None and i < len(row) else None

    for row in rows[i_hdr + 1:]:
        ma = o_(row, "code")
        ma = "" if ma is None else str(ma).strip()
        if not ma or bo_dau(ma) in {"tong", "tong cong"}:
            continue
        ten = o_(row, "name")
        if bo_dau(ten) in {"tong", "tong cong"}:
            continue
        res.products.append(SanPham(
            code=ma,
            name="" if ten is None else str(ten).strip(),
            vat_flag=str(o_(row, "vat_flag") or "").strip(),
            group=str(o_(row, "group") or "").strip(),
            unit=str(o_(row, "unit") or "").strip(),
            qty=parse_vn_number(o_(row, "qty")),
            value=parse_vn_number(o_(row, "value")),
        ))
    if not res.products:
        res.warnings.append("Không đọc được dòng hàng hoá nào.")
    return res


def _rows(source: Any, sheet: Optional[str]) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def load_products_xlsx(path: str, sheet: Optional[str] = None) -> ProductParseResult:
    return parse_product_table(_rows(path, sheet))


def load_products_xlsx_bytes(data: bytes, sheet: Optional[str] = None) -> ProductParseResult:
    return parse_product_table(_rows(BytesIO(data), sheet))
