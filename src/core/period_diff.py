"""
src/core/period_diff.py — đối chiếu HAI LẦN XUẤT cùng một kỳ, tìm sửa hồi tố.

VÌ SAO CẦN
----------
Mọi phép kiểm trong `inventory.py` chỉ nhìn được MỘT bản báo cáo. Chúng bắt
được sổ tự mâu thuẫn với chính nó, nhưng mù hoàn toàn trước một loại lỗi khác:
sổ hôm nay hợp lệ, sổ tháng trước cũng hợp lệ, mà hai bản kể hai câu chuyện
khác nhau về CÙNG một quãng thời gian.

Ví dụ có thật (Hoàng Phát, cùng ngày bắt đầu 01/01/2026):

    VT00059   bản đến 24/07: xuất 4508 → tồn −21
              bản đến 11/08: xuất 4400 → tồn +87
    VT00039   bản đến 24/07: xuất  306 → tồn   0
              bản đến 11/08: xuất  414 → tồn −108

Kỳ dài hơn mà số xuất luỹ kế GIẢM là điều không thể xảy ra do phát sinh mới —
thời gian chỉ chạy một chiều. Đúng 108 lít rời mã này sang mã kia: một phiếu
xuất bị sửa mã hàng để dập lỗi âm kho, và lỗi mọc lại ở nơi nhận. Không bản
báo cáo đơn lẻ nào nhìn ra được chuyện đó.

ĐIỀU DỄ BÁO NHẦM NHẤT
---------------------
Với giá vốn BÌNH QUÂN CUỐI KỲ, `out_value` đổi trong khi `out_qty` giữ nguyên
là chuyện BÌNH THƯỜNG: kỳ dài hơn thì bình quân được tính lại trên nhiều lần
nhập hơn. Bắt lỗi chỗ này sẽ tạo ra một trận báo động giả trên gần như mọi mã.
Ngược lại `in_value` đổi mà `in_qty` giữ nguyên thì không có cách giải thích
lành nào — đơn giá trên một phiếu nhập đã qua đã bị sửa.

Module không sửa gì và không quy trách nhiệm ai. Nó chỉ nói: con số này từng
khác, và đây là số cũ, số mới, chênh bao nhiêu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.core.findings import finding as _tao_finding
from src.core.findings import sap_xep
from src.core.inventory import InventoryLine
from src.core.inventory_import import ParseResult

# Cùng dung sai với inventory.py — kế toán làm tròn đến đồng.
_QTY_TOL = 0.01
_VALUE_TOL = 2.0

# Các cột luỹ kế: kỳ dài hơn thì chỉ được PHÉP tăng.
_LUY_KE = (
    ("in_qty", "in_value", "nhập"),
    ("out_qty", "out_value", "xuất"),
)


@dataclass
class ChenhLech:
    """Một con số đã đổi giữa hai lần xuất."""
    code: str
    truong: str          # "nhập" / "xuất" / "tồn đầu kỳ"
    truoc: float
    sau: float

    @property
    def chenh(self) -> float:
        return self.sau - self.truoc


def _finding(
    kind: str,
    severity: str,
    code: Optional[str],
    product: Optional[str],
    title: str,
    evidence: dict[str, Any],
    suggestion: str,
    money_impact: Optional[float] = None,
) -> dict[str, Any]:
    """Thứ tự tham số riêng của module này; hình dạng thì dùng chung findings.py."""
    return _tao_finding(kind, severity, title, evidence, suggestion,
                        code=code, product=product, money_impact=money_impact)


def _lap_chi_muc(lines: list[InventoryLine]) -> dict[str, InventoryLine]:
    return {str(l.code).strip(): l for l in lines if str(l.code or "").strip()}


def _so_sanh_duoc(truoc: ParseResult, sau: ParseResult) -> list[str]:
    """
    Hai bản có so được không. Trả danh sách lý do KHÔNG so được — rỗng là so được.

    Thà từ chối so còn hơn so bừa rồi báo một loạt 'sửa hồi tố' chỉ vì người
    dùng chọn nhầm kho hoặc nhầm ngày bắt đầu.
    """
    ly_do: list[str] = []

    kho_t = (truoc.warehouse or "").strip().lower()
    kho_s = (sau.warehouse or "").strip().lower()
    if kho_t and kho_s and kho_t != kho_s:
        ly_do.append(f"Hai bản khác kho: '{truoc.warehouse}' và '{sau.warehouse}'.")

    if not truoc.period_start or not sau.period_start:
        ly_do.append("Thiếu ngày bắt đầu kỳ ở ít nhất một bản.")
    elif truoc.period_start != sau.period_start:
        ly_do.append(
            f"Hai bản khác ngày bắt đầu: {truoc.period_start} và {sau.period_start}. "
            "Số luỹ kế của hai kỳ khác gốc thì không so trực tiếp được."
        )

    if truoc.period_end and sau.period_end and sau.period_end < truoc.period_end:
        ly_do.append(
            f"Bản đưa vào làm 'sau' ({sau.period_end}) lại kết thúc TRƯỚC bản 'trước' "
            f"({truoc.period_end}) — nhiều khả năng truyền nhầm thứ tự hai tham số."
        )

    return ly_do


def _tim_ma_nhan(
    giam: ChenhLech,
    chi_muc_truoc: dict[str, InventoryLine],
    chi_muc_sau: dict[str, InventoryLine],
    truong_qty: str,
) -> list[str]:
    """
    Mã nào TĂNG đúng bằng lượng mã kia GIẢM — ứng viên của một phiếu bị sửa mã hàng.

    Khớp đúng bằng chứ không xấp xỉ. Đây là gợi ý điều tra, không phải kết luận:
    hai con số bằng nhau vẫn có thể là trùng hợp, nên trả về TẤT CẢ ứng viên
    thay vì chọn hộ một cái.
    """
    can = abs(giam.chenh)
    if can <= _QTY_TOL:
        return []
    ra: list[str] = []
    for ma, dong_sau in chi_muc_sau.items():
        if ma == giam.code:
            continue
        dong_truoc = chi_muc_truoc.get(ma)
        if dong_truoc is None:
            continue
        tang = getattr(dong_sau, truong_qty) - getattr(dong_truoc, truong_qty)
        if abs(tang - can) <= _QTY_TOL:
            ra.append(ma)
    return sorted(ra)


def doi_chieu_hai_lan_xuat(truoc: ParseResult, sau: ParseResult) -> dict[str, Any]:
    """
    So hai lần xuất cùng một kỳ. `truoc` là bản xuất SỚM hơn.

    Trả về {"findings": [...], "warnings": [...], "summary": {...}} — findings
    cùng hình dạng với `audit_inventory` để dùng lại chỗ hiển thị.
    """
    canh_bao = _so_sanh_duoc(truoc, sau)
    tom_tat: dict[str, Any] = {
        "kho": sau.warehouse or truoc.warehouse,
        "kỳ_bắt_đầu": truoc.period_start,
        "bản_trước_đến": truoc.period_end,
        "bản_sau_đến": sau.period_end,
        "số_mã_bản_trước": len(truoc.lines),
        "số_mã_bản_sau": len(sau.lines),
        "so_sánh_được": not canh_bao,
    }
    if canh_bao:
        return {"findings": [], "warnings": canh_bao, "summary": tom_tat}

    ct, cs = _lap_chi_muc(truoc.lines), _lap_chi_muc(sau.lines)
    fs: list[dict[str, Any]] = []
    chung = sorted(set(ct) & set(cs))

    # --- 1. Mã biến mất khỏi bản sau -------------------------------------
    for ma in sorted(set(ct) - set(cs)):
        d = ct[ma]
        fs.append(_finding(
            "line_disappeared", "cao", ma, d.label(),
            "Mã hàng có ở lần xuất trước, biến mất ở lần xuất sau",
            {"tồn_cuối_bản_trước": d.closing_qty,
             "giá_trị_cuối_bản_trước": d.closing_value},
            "Mã bị xoá, bị gộp sang mã khác, hoặc mọi chứng từ của nó đã bị huỷ. "
            "Đối chiếu sổ chi tiết của riêng mã này.",
            money_impact=abs(d.closing_value) if d.closing_value else None,
        ))

    # --- 2. Mã mới mà đã có tồn đầu kỳ -----------------------------------
    for ma in sorted(set(cs) - set(ct)):
        d = cs[ma]
        if abs(d.opening_qty) <= _QTY_TOL:
            continue        # hàng mới nhập lần đầu trong kỳ — hoàn toàn bình thường
        fs.append(_finding(
            "opening_appeared", "cao", ma, d.label(),
            "Mã mới xuất hiện nhưng đã có tồn đầu kỳ",
            {"tồn_đầu_kỳ": d.opening_qty, "giá_trị_đầu_kỳ": d.opening_value},
            "Cùng ngày bắt đầu kỳ mà lần xuất trước không có mã này. Số dư đầu kỳ "
            "được thêm vào sau. Kiểm tra chứng từ ghi số dư đầu kỳ.",
            money_impact=abs(d.opening_value) if d.opening_value else None,
        ))

    # --- 3. Tồn đầu kỳ đổi -----------------------------------------------
    # Cùng một ngày bắt đầu thì số dư đầu kỳ là hằng số. Đổi được nghĩa là sổ
    # của kỳ TRƯỚC ĐÓ đã bị sửa — nặng hơn sửa trong kỳ, vì báo cáo thuế của kỳ
    # trước đã nộp rồi.
    for ma in chung:
        a, b = ct[ma], cs[ma]
        if abs(a.opening_qty - b.opening_qty) > _QTY_TOL:
            fs.append(_finding(
                "opening_changed", "cao", ma, b.label(),
                "Tồn đầu kỳ đổi giữa hai lần xuất",
                {"đầu_kỳ_bản_trước": a.opening_qty, "đầu_kỳ_bản_sau": b.opening_qty,
                 "chênh": round(b.opening_qty - a.opening_qty, 4)},
                "Cùng ngày bắt đầu kỳ thì số dư đầu kỳ không được đổi. Sổ kỳ trước "
                "đã bị sửa sau khi chốt — kiểm tra xem kỳ đó đã khoá sổ chưa.",
            ))
        if (a.opening_value is not None and b.opening_value is not None
                and abs(a.opening_value - b.opening_value) > _VALUE_TOL):
            fs.append(_finding(
                "opening_changed", "cao", ma, b.label(),
                "Giá trị tồn đầu kỳ đổi giữa hai lần xuất",
                {"giá_trị_bản_trước": a.opening_value,
                 "giá_trị_bản_sau": b.opening_value,
                 "chênh": round(b.opening_value - a.opening_value)},
                "Giá vốn tồn đầu kỳ bị tính lại. Ảnh hưởng thẳng đến lãi gộp của "
                "kỳ trước đã nộp báo cáo.",
                money_impact=abs(b.opening_value - a.opening_value),
            ))

    # --- 4. Luỹ kế nhập/xuất GIẢM ----------------------------------------
    for ma in chung:
        a, b = ct[ma], cs[ma]
        for truong_qty, truong_val, ten in _LUY_KE:
            qa, qb = getattr(a, truong_qty), getattr(b, truong_qty)
            if qb - qa >= -_QTY_TOL:
                continue

            giam = ChenhLech(ma, ten, qa, qb)
            nhan = _tim_ma_nhan(giam, ct, cs, truong_qty)
            va, vb = getattr(a, truong_val), getattr(b, truong_val)
            tien = abs(vb - va) if (va is not None and vb is not None) else None

            bang_chung: dict[str, Any] = {
                f"{ten}_bản_trước": qa, f"{ten}_bản_sau": qb,
                "chênh": round(qb - qa, 4),
                f"giá_trị_{ten}_bản_trước": va, f"giá_trị_{ten}_bản_sau": vb,
            }
            goi_y = (
                f"Kỳ dài hơn mà số {ten} luỹ kế lại giảm — phát sinh mới không thể "
                f"làm giảm số đã có. Một chứng từ trong quãng đã báo cáo đã bị sửa, "
                f"xoá, hoặc huỷ ghi sổ."
            )
            if nhan:
                bang_chung["mã_tăng_đúng_bằng_lượng_này"] = nhan
                goi_y += (
                    f" Mã {', '.join(nhan)} tăng đúng {abs(round(qb - qa, 4)):g} ở cùng "
                    f"cột — nhiều khả năng một phiếu bị sửa mã hàng. Kiểm tra tồn kho "
                    f"của mã nhận trước khi coi là đã xử lý xong."
                )

            fs.append(_finding(
                "history_decreased", "cao", ma, b.label(),
                f"Số {ten} luỹ kế GIẢM dù kỳ dài hơn",
                bang_chung, goi_y, money_impact=tien,
            ))

    # --- 5. Giá trị nhập đổi mà số lượng giữ nguyên ----------------------
    # Chỉ xét cột NHẬP. Cột XUẤT đổi giá trị khi số lượng không đổi là hệ quả
    # bình thường của giá vốn bình quân cuối kỳ (xem docstring đầu file).
    for ma in chung:
        a, b = ct[ma], cs[ma]
        if abs(a.in_qty - b.in_qty) > _QTY_TOL:
            continue
        if a.in_value is None or b.in_value is None:
            continue
        if abs(a.in_value - b.in_value) <= _VALUE_TOL:
            continue
        fs.append(_finding(
            "purchase_value_changed", "trung bình", ma, b.label(),
            "Giá trị nhập đổi trong khi số lượng nhập không đổi",
            {"số_lượng_nhập": b.in_qty,
             "giá_trị_bản_trước": a.in_value, "giá_trị_bản_sau": b.in_value,
             "chênh": round(b.in_value - a.in_value)},
            "Cùng số lượng nhập mà giá trị khác đi nghĩa là đơn giá trên một phiếu "
            "nhập đã qua bị sửa. Đối chiếu với hoá đơn của nhà cung cấp.",
            money_impact=abs(b.in_value - a.in_value),
        ))

    fs = sap_xep(fs)

    tom_tat.update({
        "số_mã_so_được": len(chung),
        "số_phát_hiện": len(fs),
        "có_sửa_hồi_tố": any(
            f["kind"] in ("history_decreased", "opening_changed", "line_disappeared")
            for f in fs
        ),
        "tổng_tiền_ảnh_hưởng": round(sum(f["money_impact"] or 0 for f in fs)),
    })
    return {"findings": fs, "warnings": [], "summary": tom_tat}
