"""
src/core/partner_import.py — đọc DANH SÁCH KHÁCH HÀNG / NHÀ CUNG CẤP của MISA.

Hai bảng này cùng một khuôn, chỉ khác chữ trong tiêu đề cột mã:

    STT | Mã khách hàng    | Tên khách hàng    | Địa chỉ | Công nợ | Mã số thuế | Điện thoại
    STT | Mã nhà cung cấp  | Tên nhà cung cấp  | Địa chỉ | Công nợ | Mã số thuế | Điện thoại

CỘT 'CÔNG NỢ' LÀ SỐ DƯ, KHÔNG PHẢI TUỔI NỢ
------------------------------------------
Một con số duy nhất cho mỗi đối tác, không có ngày hoá đơn. Từ đây phân tích
được mức độ tập trung, số dư ngược dấu, đối tác trùng — nhưng KHÔNG phân tích
được nợ quá hạn bao lâu. Muốn có tuổi nợ phải xin thêm 'Sổ chi tiết công nợ
phải thu'. Module này không giả vờ biết thứ nó không biết.

TỰ KIỂM
-------
Cột STT của MISA chạy liên tục 1..N. Đọc ra N dòng mà STT lớn nhất khác N thì
đã bỏ sót hoặc nhân đôi dòng — bắt được lỗi đọc bảng mà không cần dòng tổng
(hai file thật đều có dòng 'Tổng' bỏ trống mọi cột số).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

from src.core.inventory_import import parse_vn_number
from src.core.tax_id import chuan_hoa
from src.core.utils import bo_dau

_MAX_ROWS = 50_000

KHACH_HANG = "khách hàng"
NHA_CUNG_CAP = "nhà cung cấp"

# Tên pháp nhân bắt buộc phải có mã số thuế; tên người thì không.
_PHAP_NHAN_RE = re.compile(
    r"^(công ty|cty|c\.ty|chi nhánh|doanh nghiệp|dn tư nhân|tổng công ty|"
    r"hợp tác xã|htx|trung tâm|nhà máy|xí nghiệp|tập đoàn|văn phòng|ngân hàng|"
    r"cửa hàng|trường|viện|bệnh viện)\b",
    re.IGNORECASE,
)


_norm = bo_dau


@dataclass
class Partner:
    """
    Một đối tác. `balance=None` nghĩa là CHƯA BIẾT số dư, không phải bằng 0 —
    cùng nguyên tắc với InventoryLine.
    """
    code: str
    name: str = ""
    address: str = ""
    balance: Optional[float] = None
    tax_id: str = ""
    phone: str = ""
    role: str = ""

    def label(self) -> str:
        return f"{self.code} {self.name}".strip()

    def la_phap_nhan(self) -> bool:
        """Có phải tổ chức không — quyết định việc thiếu mã số thuế có phải lỗi."""
        return bool(_PHAP_NHAN_RE.match((self.name or "").strip()))


@dataclass
class PartnerParseResult:
    partners: list[Partner] = field(default_factory=list)
    role: str = ""
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (
            bool(self.partners)
            and not self.checks.get("missing_columns")
            and not self.checks.get("stt_mismatch")
        )


# --- tìm tiêu đề ----------------------------------------------------------
# (tên trường, các cách MISA đặt tên cột)
_COT = (
    ("code", ("ma khach hang", "ma nha cung cap", "ma doi tac", "ma ncc", "ma kh", "ma")),
    ("name", ("ten khach hang", "ten nha cung cap", "ten doi tac", "ten ncc", "ten kh", "ten")),
    ("address", ("dia chi",)),
    ("balance", ("cong no", "so du", "du no")),
    ("tax_id", ("ma so thue", "mst")),
    ("phone", ("dien thoai", "so dien thoai", "dt")),
)
_BAT_BUOC = ("code", "name")


def _tim_tieu_de(rows: list[list[Any]]) -> Optional[int]:
    """Dòng tiêu đề là dòng đầu tiên có cả cột mã lẫn cột tên."""
    for i, row in enumerate(rows[:30]):
        o = [_norm(c) for c in row]
        co_ma = any(t.startswith("ma ") or t == "ma" for t in o)
        co_ten = any(t.startswith("ten") for t in o)
        if co_ma and co_ten:
            return i
    return None


def _map_cot(row: list[Any]) -> dict[str, int]:
    """
    Gán cột theo tiêu đề. Duyệt các bí danh dài trước để 'mã số thuế' không bị
    cột 'mã' nuốt mất — thứ tự khớp ở đây quyết định đúng sai của cả bảng.
    """
    o = [_norm(c) for c in row]
    dung: set[int] = set()
    ra: dict[str, int] = {}
    cap = [(truong, bd) for truong, bds in _COT for bd in bds]
    cap.sort(key=lambda x: -len(x[1]))
    for truong, bd in cap:
        if truong in ra:
            continue
        for i, text in enumerate(o):
            if i in dung or not text:
                continue
            if text == bd or text.startswith(bd + " "):
                ra[truong] = i
                dung.add(i)
                break
    return ra


def _doan_vai_tro(rows: list[list[Any]], hdr: dict[str, int], i_hdr: int) -> str:
    blob = _norm(" ".join(
        " ".join("" if c is None else str(c) for c in r) for r in rows[:i_hdr + 1]
    ))
    if "nha cung cap" in blob:
        return NHA_CUNG_CAP
    if "khach hang" in blob:
        return KHACH_HANG
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_partner_table(rows: list[list[Any]], role: str = "") -> PartnerParseResult:
    """Đọc bảng đối tác từ `list[list]` — nguồn nào cũng nạp được."""
    res = PartnerParseResult(role=role)
    if len(rows) > _MAX_ROWS:
        res.warnings.append(f"Bảng có {len(rows)} dòng, vượt trần {_MAX_ROWS} — cắt bớt.")
        rows = rows[:_MAX_ROWS]

    i_hdr = _tim_tieu_de(rows)
    if i_hdr is None:
        res.warnings.append("Không tìm thấy dòng tiêu đề có cả cột mã lẫn cột tên.")
        res.checks["missing_columns"] = list(_BAT_BUOC)
        return res

    hdr = _map_cot(rows[i_hdr])
    thieu = [t for t in _BAT_BUOC if t not in hdr]
    if thieu:
        res.checks["missing_columns"] = thieu
        res.warnings.append(f"Thiếu cột bắt buộc: {', '.join(thieu)}.")
        return res
    res.checks["columns"] = dict(hdr)
    if "balance" not in hdr:
        res.warnings.append("Không có cột 'Công nợ' — chỉ đọc được danh mục đối tác.")

    if not res.role:
        res.role = _doan_vai_tro(rows, hdr, i_hdr)

    def o(row: list[Any], truong: str) -> Any:
        i = hdr.get(truong)
        return row[i] if i is not None and i < len(row) else None

    stt_max = 0
    i_stt = next((i for i, c in enumerate(rows[i_hdr]) if _norm(c) == "stt"), None)

    for row in rows[i_hdr + 1:]:
        ma = _text(o(row, "code"))
        if not ma or _norm(ma) in {"tong", "tong cong", "cong"}:
            continue
        if i_stt is not None and i_stt < len(row):
            n = parse_vn_number(row[i_stt])
            if n is not None:
                stt_max = max(stt_max, int(n))
        res.partners.append(Partner(
            code=ma,
            name=_text(o(row, "name")),
            address=_text(o(row, "address")),
            balance=parse_vn_number(o(row, "balance")) if "balance" in hdr else None,
            # Qua chuan_hoa chứ không qua _text: ô mã số thuế định dạng kiểu số
            # bị Excel cắt mất số 0 đứng đầu, chỉ chuan_hoa mới bù lại được.
            tax_id=chuan_hoa(o(row, "tax_id")),
            phone=_text(o(row, "phone")),
            role=res.role,
        ))

    if not res.partners:
        res.warnings.append("Không đọc được dòng đối tác nào.")

    # Tự kiểm: STT liên tục 1..N thì STT lớn nhất phải bằng số dòng đọc được.
    if stt_max and stt_max != len(res.partners):
        res.checks["stt_mismatch"] = {"stt_lớn_nhất": stt_max, "số_dòng_đọc": len(res.partners)}
        res.warnings.append(
            f"STT lớn nhất là {stt_max} nhưng chỉ đọc được {len(res.partners)} dòng — "
            "có dòng bị bỏ sót hoặc đọc trùng."
        )

    trung = [m for m, n in _dem(p.code for p in res.partners) if n > 1]
    if trung:
        res.checks["duplicate_codes"] = trung
        res.warnings.append(f"Mã đối tác lặp trong file: {', '.join(trung[:5])}.")
    return res


def _dem(it: Any) -> list[tuple[str, int]]:
    d: dict[str, int] = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return sorted(d.items())


def _rows_from_workbook(source: Any, sheet: Optional[str]) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def load_partners_xlsx(
    path: str, sheet: Optional[str] = None, role: str = ""
) -> PartnerParseResult:
    return parse_partner_table(_rows_from_workbook(path, sheet), role=role)


def load_partners_xlsx_bytes(
    data: bytes, sheet: Optional[str] = None, role: str = ""
) -> PartnerParseResult:
    return parse_partner_table(_rows_from_workbook(BytesIO(data), sheet), role=role)
