"""
src/core/inventory.py — kiểm toán tồn kho + cầu nối giá vốn. CODE THUẦN, KHÔNG LLM (P1).

NGHIỆP VỤ
---------
Doanh nghiệp vừa phân phối dầu nhớt vừa làm vận tải. Phần mềm kế toán (MISA /
Fast / Bravo) xuất ra bảng "TỔNG HỢP TỒN KHO" theo cùng một hình dạng:

    Mã hàng | Tên hàng | ĐVT | Đầu kỳ (SL, GT, ĐGBQ) | Nhập kho (…) | Xuất kho (…) | Cuối kỳ (…)

Bảng đó *luôn* cân đối về cộng trừ — phần mềm tự tính. Nhưng cân đối KHÔNG có
nghĩa là đúng: tồn âm, số lượng và giá trị ngược dấu, hàng có số lượng mà không
có giá trị — tất cả đều nằm dưới lớp cân đối và không ai nhìn ra bằng mắt.

VÌ SAO LÀ CODE, KHÔNG PHẢI LLM
------------------------------
Cùng lý do đã chốt cho reporting.py (27/07/2026): con số tài chính sai mà *nghe
có vẻ đúng* là loại lỗi tệ nhất. Ở đây còn nặng hơn — output là lời buộc tội sổ
sách. Một phát hiện sai làm chủ DN mất niềm tin ngay lập tức, một phát hiện bỏ
sót thì vô hại. Nên mọi kiểm tra ở đây phải chứng minh được, kèm bằng chứng để
đối chiếu tay. LLM chỉ diễn giải (nhánh REPORT).

BÀI HỌC 30/07/2026 — GIỚI HẠN CỦA BẢNG TỔNG HỢP
------------------------------------------------
Bản đầu của module này có một kiểm tra sai: nó coi "đơn giá tồn cuối cao hơn
mọi giá đầu vào" là bằng chứng sổ ghi sai. Chạy trên bản xuất thật 119 mã thì
nó gắn cờ 18 mã — và cả 18 đều VÔ TỘI.

`in_value / in_qty` là giá nhập *bình quân cả kỳ*, không phải giá từng lô. Với
FIFO và giá tăng dần, hàng bán ra là lô cũ rẻ, hàng nằm lại là lô mới đắt, nên
đơn giá tồn cuối vượt giá nhập bình quân là kết quả ĐÚNG. Cả 18 mã đều mang
đúng chữ ký đó: xuất < bình quân < tồn cuối.

Nguyên tắc rút ra: bảng tổng hợp không cho thấy giá từng lô, nên mọi kết luận
về *cách tính* giá vốn đều nằm ngoài tầm chứng minh của nó. Một quy tắc bắn
trên hàng chục mã cùng lúc thì nghi quy tắc trước, đừng nghi sổ sách.

VÌ SAO ĐÂY LÀ MẢNH GHÉP CÒN THIẾU CỦA BÁO CÁO LÃI LỖ
----------------------------------------------------
reporting.build_report phải tự thú "chỉ 62% doanh thu có giá vốn" vì không ai
nhập giá vốn theo từng dòng bán. Cột "Xuất kho / Giá trị" trong bảng này CHÍNH
LÀ giá vốn, ở mức từng mã hàng. `unit_cost_table` + `fill_missing_cogs` bắc cầu
sang SaleLine để lãi gộp tính được trên gần 100% doanh thu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

# --- Dung sai -------------------------------------------------------------
# Phần mềm kế toán làm tròn đến đồng; đừng báo lỗi vì chênh 1 đồng.
_QTY_TOL = 0.01
_VALUE_TOL = 2.0            # đồng
_UNIT_TOL = 1.0             # đồng/ĐVT — dùng khi so đơn giá

# --- Ngưỡng nghiệp vụ (đổi được, có lý do) --------------------------------
_PRICE_JUMP_PCT = 10.0      # giá nhập lệch >=10% so với giá tồn đầu kỳ
_COST_DRIFT_PCT = 5.0       # giá vốn hàng tồn lệch >=5% so với hàng đã bán
_METHOD_MIN_SPREAD_PCT = 1.0  # biên giá tối thiểu để phân biệt FIFO / bình quân
_DEAD_MIN_DAYS = 90         # kỳ ngắn hơn 90 ngày thì "chưa xuất" là bình thường
_SLOW_DAYS_OF_SUPPLY = 365  # tồn đủ bán trên 1 năm = vốn chôn

_SEVERITY_ORDER = {"cao": 0, "trung bình": 1, "thấp": 2}


@dataclass
class InventoryLine:
    """
    Một dòng của bảng TỔNG HỢP TỒN KHO.

    `None` ở cột giá trị nghĩa là CHƯA BIẾT, không phải 0 — giữ đúng nguyên tắc
    của reporting.py. Kho khuyến mại thường có giá trị bằng 0 *thật* (hàng không
    được ghi nhận giá vốn), đó là một phát hiện riêng chứ không phải thiếu dữ liệu.
    """
    code: str
    name: str = ""
    unit: str = ""
    opening_qty: float = 0.0
    opening_value: Optional[float] = None
    in_qty: float = 0.0
    in_value: Optional[float] = None
    out_qty: float = 0.0
    out_value: Optional[float] = None
    closing_qty: float = 0.0
    closing_value: Optional[float] = None

    # -- tiện ích nội bộ ---------------------------------------------------
    def label(self) -> str:
        return f"{self.code} {self.name}".strip()

    def _unit_cost(self, qty: float, value: Optional[float]) -> Optional[float]:
        if value is None or qty <= _QTY_TOL:
            return None
        return value / qty

    def opening_unit(self) -> Optional[float]:
        return self._unit_cost(self.opening_qty, self.opening_value)

    def in_unit(self) -> Optional[float]:
        return self._unit_cost(self.in_qty, self.in_value)

    def out_unit(self) -> Optional[float]:
        return self._unit_cost(self.out_qty, self.out_value)

    def closing_unit(self) -> Optional[float]:
        return self._unit_cost(self.closing_qty, self.closing_value)

    def input_units(self) -> list[float]:
        """Mọi đơn giá đã ĐI VÀO kho trong kỳ (tồn đầu + nhập)."""
        return [u for u in (self.opening_unit(), self.in_unit()) if u is not None]


def _finding(
    kind: str,
    severity: str,
    line: Optional[InventoryLine],
    title: str,
    evidence: dict[str, Any],
    suggestion: str,
    money_impact: Optional[float] = None,
) -> dict[str, Any]:
    """Một phát hiện luôn kèm bằng chứng số để chủ DN đối chiếu tay được."""
    return {
        "kind": kind,
        "severity": severity,
        "code": line.code if line else None,
        "product": line.label() if line else None,
        "unit": line.unit if line else None,
        "title": title,
        "evidence": evidence,
        "money_impact": None if money_impact is None else round(money_impact),
        "suggestion": suggestion,
    }


# ---------------------------------------------------------------------------
# Từng phép kiểm tra — mỗi hàm trả về list phát hiện cho MỘT dòng
# ---------------------------------------------------------------------------

def _check_balance(line: InventoryLine) -> list[dict[str, Any]]:
    """
    ĐK + Nhập − Xuất = CK, cả số lượng lẫn giá trị.

    Lệch ở đây nghĩa là bản xuất bị cắt dòng hoặc bị sửa tay — mọi kết luận sau
    đó đều vô nghĩa, nên đây là lỗi chặn.
    """
    out: list[dict[str, Any]] = []
    exp_qty = line.opening_qty + line.in_qty - line.out_qty
    if abs(exp_qty - line.closing_qty) > _QTY_TOL:
        out.append(_finding(
            "balance_mismatch", "cao", line,
            "Số lượng không cân đối",
            {"đầu_kỳ": line.opening_qty, "nhập": line.in_qty, "xuất": line.out_qty,
             "cuối_kỳ_phải_là": round(exp_qty, 2), "cuối_kỳ_ghi": line.closing_qty},
            "Bản xuất có thể bị thiếu dòng hoặc sửa tay. Xuất lại từ phần mềm kế toán.",
        ))

    vals = (line.opening_value, line.in_value, line.out_value, line.closing_value)
    if all(v is not None for v in vals):
        exp_val = line.opening_value + line.in_value - line.out_value  # type: ignore[operator]
        if abs(exp_val - line.closing_value) > _VALUE_TOL:             # type: ignore[operator]
            out.append(_finding(
                "balance_mismatch", "cao", line,
                "Giá trị không cân đối",
                {"đầu_kỳ": line.opening_value, "nhập": line.in_value,
                 "xuất": line.out_value, "cuối_kỳ_phải_là": round(exp_val),
                 "cuối_kỳ_ghi": line.closing_value},
                "Bản xuất có thể bị thiếu dòng hoặc sửa tay. Xuất lại từ phần mềm kế toán.",
            ))
    return out


def _check_negative(line: InventoryLine) -> list[dict[str, Any]]:
    """Tồn cuối âm = đã xuất nhiều hơn số thực có. Luôn là lỗi thật."""
    if line.closing_qty >= -_QTY_TOL:
        return []
    return [_finding(
        "negative_stock", "cao", line,
        "Tồn kho âm — xuất nhiều hơn số có",
        {"đầu_kỳ": line.opening_qty, "nhập": line.in_qty, "xuất": line.out_qty,
         "cuối_kỳ": line.closing_qty, "thiếu": round(abs(line.closing_qty), 2)},
        "Thiếu phiếu nhập chưa vào sổ, hoặc sai quy đổi đơn vị (phuy/can → lít). "
        "Đối chiếu phiếu nhập với nhà cung cấp trong kỳ.",
        money_impact=abs(line.closing_value) if line.closing_value else None,
    )]


def _check_value_sign(line: InventoryLine) -> list[dict[str, Any]]:
    """
    Số lượng và giá trị phải cùng dấu. Đây là mâu thuẫn thật sự không thể có:
    còn hàng trong kho mà giá trị âm, hoặc hết hàng mà vẫn còn giá trị.
    """
    out: list[dict[str, Any]] = []
    for stage, label in (("closing", "cuối kỳ"), ("opening", "đầu kỳ")):
        qty = getattr(line, f"{stage}_qty")
        val = getattr(line, f"{stage}_value")
        if val is None:
            continue
        if qty > _QTY_TOL and val < -_VALUE_TOL:
            out.append(_finding(
                "value_sign_conflict", "cao", line,
                f"Tồn {label} có số lượng dương nhưng giá trị âm",
                {"số_lượng": qty, "giá_trị": val},
                "Giá vốn ghi âm cho hàng đang có thật. Đối chiếu sổ chi tiết.",
                money_impact=abs(val),
            ))
        elif abs(qty) <= _QTY_TOL and abs(val) > _VALUE_TOL:
            out.append(_finding(
                "value_sign_conflict", "cao", line,
                f"Tồn {label} hết hàng nhưng vẫn còn giá trị",
                {"số_lượng": qty, "giá_trị": val},
                "Giá trị treo lại trên mã đã hết hàng — thường do phiếu xuất "
                "thiếu giá vốn. Đối chiếu sổ chi tiết.",
                money_impact=abs(val),
            ))
    return out


def _check_cost_drift(line: InventoryLine) -> list[dict[str, Any]]:
    """
    So giá vốn hàng CÒN TRONG KHO với giá vốn hàng ĐÃ BÁN trong kỳ.

    ĐÂY KHÔNG PHẢI KIỂM TRA LỖI — và một phiên bản trước của hàm này đã sai vì
    tưởng là (30/07/2026, phát hiện khi chạy trên bản xuất thật 119 mã).

    Sai ở đâu: `in_value / in_qty` là giá nhập BÌNH QUÂN CẢ KỲ, không phải giá
    từng lô. Với FIFO và giá tăng dần, hàng bán ra là lô cũ rẻ còn hàng nằm lại
    là lô mới đắt — nên đơn giá tồn cuối VƯỢT giá nhập bình quân là chuyện hoàn
    toàn bình thường, không phải bằng chứng sổ sai. Bảng tổng hợp không cho thấy
    giá từng lô nên không thể kết luận ngược lại. 18/18 mã bị gắn cờ oan đều có
    đúng chữ ký FIFO: xuất < bình quân < tồn cuối.

    Cái ĐÚNG mà con số này nói lên là chuyện của kỳ SAU: hàng còn trong kho đắt
    hơn hàng vừa bán, nên nếu giá bán không đổi thì biên lợi nhuận kỳ tới hẹp
    lại. Đó mới là thứ chủ DN cần biết.
    """
    out_u, ck_u = line.out_unit(), line.closing_unit()
    if out_u is None or ck_u is None or out_u <= 0 or line.closing_qty <= _QTY_TOL:
        return []

    drift = (ck_u - out_u) / out_u * 100
    if abs(drift) < _COST_DRIFT_PCT:
        return []

    extra = (ck_u - out_u) * line.closing_qty
    if drift > 0:
        return [_finding(
            "rising_cost_basis", "trung bình", line,
            f"Giá vốn hàng tồn cao hơn hàng đã bán {drift:.1f}%",
            {"đơn_giá_đã_bán": round(out_u, 2), "đơn_giá_còn_tồn": round(ck_u, 2),
             "số_lượng_tồn": line.closing_qty, "chênh_lệch_pct": round(drift, 1)},
            "Bán hết chỗ tồn này ở giá bán hiện tại thì biên lợi nhuận kỳ sau sẽ "
            "hẹp hơn kỳ này. Cân nhắc điều chỉnh bảng giá bán trước khi xả hàng.",
            money_impact=extra,
        )]
    return [_finding(
        "falling_cost_basis", "thấp", line,
        f"Giá vốn hàng tồn thấp hơn hàng đã bán {abs(drift):.1f}%",
        {"đơn_giá_đã_bán": round(out_u, 2), "đơn_giá_còn_tồn": round(ck_u, 2),
         "số_lượng_tồn": line.closing_qty, "chênh_lệch_pct": round(drift, 1)},
        "Giá vốn đang giảm: giữ nguyên giá bán thì biên kỳ sau rộng hơn, hoặc "
        "hạ giá để giành đơn mà vẫn đủ biên.",
        money_impact=extra,
    )]


def _costing_method(line: InventoryLine) -> Optional[str]:
    """
    Đoán phương pháp tính giá vốn — CỰC KỲ dè dặt, thà không biết còn hơn đoán sai.

    Đã siết lại sau khi bản đầu nhận nhầm FIFO thành bình quân trên dữ liệu thật
    (30/07/2026): chỉ so đơn giá xuất với bình quân là không đủ, vì khi giá nhập
    ít biến động thì FIFO và bình quân cho gần như cùng một con số.

    Dấu hiệu phân biệt thật nằm ở chỗ khác:

      - BÌNH QUÂN (di động): hàng xuất và hàng còn lại mang CÙNG một đơn giá,
        và đơn giá đó xấp xỉ bình quân cả kỳ. Cả ba phải trùng nhau.
      - FIFO: xuất đúng bằng giá lô đầu kỳ, và không xuất quá số lượng lô đó.

    Không thoả cả hai -> None. Bảng tổng hợp không cho thấy giá từng lô, nên
    nhiều trường hợp vốn dĩ không thể kết luận, và nói "không biết" mới là câu
    trả lời đúng.
    """
    o_u, i_u, x_u = line.opening_unit(), line.in_unit(), line.out_unit()
    ck_u = line.closing_unit()
    if o_u is None or i_u is None or x_u is None:
        return None
    if line.opening_value is None or line.in_value is None:
        return None
    wavg = (line.opening_value + line.in_value) / (line.opening_qty + line.in_qty)
    # Biên giá đầu kỳ vs giá nhập phải đủ rộng thì hai phương pháp mới tách ra
    # được. Giá gần như nhau (VT00016 lệch 5đ, VT00036 lệch 209đ trên bản xuất
    # thật) thì FIFO và bình quân cho cùng một con số — kết luận lúc đó là nhiễu.
    if wavg <= 0 or abs(o_u - i_u) / wavg * 100 < _METHOD_MIN_SPREAD_PCT:
        return None

    band = max(_UNIT_TOL, abs(o_u - i_u) * 0.05)

    if abs(x_u - o_u) <= _UNIT_TOL and line.out_qty <= line.opening_qty + _QTY_TOL:
        return "fifo"
    # Bình quân: đòi CẢ hàng xuất lẫn hàng tồn cùng mang đơn giá bình quân.
    if ck_u is not None and abs(x_u - wavg) <= band and abs(ck_u - wavg) <= band:
        return "bình quân"
    return None


def _check_dead_and_slow(line: InventoryLine, period_days: int) -> list[dict[str, Any]]:
    """Hàng chết (không xuất đơn vị nào) và hàng bán quá chậm so với tồn."""
    out: list[dict[str, Any]] = []
    if line.closing_qty <= _QTY_TOL:
        return out

    if line.out_qty <= _QTY_TOL and period_days >= _DEAD_MIN_DAYS:
        out.append(_finding(
            "dead_stock", "trung bình", line,
            f"Không xuất đơn vị nào trong {period_days} ngày",
            {"tồn_cuối": line.closing_qty, "xuất_trong_kỳ": line.out_qty,
             "số_ngày": period_days},
            "Vốn đọng, không sinh doanh thu. Cân nhắc xả hàng hoặc ngừng nhập lại.",
            money_impact=line.closing_value,
        ))
        return out

    if line.out_qty > _QTY_TOL and period_days > 0:
        daily = line.out_qty / period_days
        days_supply = line.closing_qty / daily
        if days_supply >= _SLOW_DAYS_OF_SUPPLY:
            out.append(_finding(
                "slow_moving", "trung bình", line,
                f"Tồn đủ bán ~{days_supply / 365:.1f} năm",
                {"tồn_cuối": line.closing_qty, "xuất_trong_kỳ": line.out_qty,
                 "số_ngày_kỳ": period_days, "số_ngày_đủ_bán": round(days_supply)},
                "Nhập nhiều hơn nhu cầu thực. Dừng nhập mã này cho tới khi tồn về "
                "mức bán được trong 3 tháng.",
                money_impact=line.closing_value,
            ))
    return out


def _check_price_jump(line: InventoryLine) -> list[dict[str, Any]]:
    """Giá nhập lệch mạnh so với giá tồn đầu kỳ — cảnh báo biên lợi nhuận."""
    o_u, i_u = line.opening_unit(), line.in_unit()
    if o_u is None or i_u is None or o_u <= 0:
        return []
    change = (i_u - o_u) / o_u * 100
    if abs(change) < _PRICE_JUMP_PCT:
        return []
    up = change > 0
    return [_finding(
        "price_jump", "trung bình" if up else "thấp", line,
        f"Giá nhập {'tăng' if up else 'giảm'} {abs(change):.1f}%",
        {"giá_đầu_kỳ": round(o_u), "giá_nhập_mới": round(i_u),
         "thay_đổi_pct": round(change, 1)},
        "Kiểm tra giá bán đã điều chỉnh theo chưa — nếu chưa thì mã này đang bán lỗ."
        if up else "Giá vốn giảm: cơ hội giữ giá bán để tăng biên, hoặc giảm giá để giành đơn.",
    )]


def _check_zero_value(line: InventoryLine) -> list[dict[str, Any]]:
    """
    Hàng có số lượng nhưng giá trị bằng 0 — điển hình là kho khuyến mại.

    Đây là hàng thật, có giá vốn thật, nhưng không được ghi nhận đồng nào. Hệ
    quả: chi phí khuyến mại vô hình, lãi gộp bị thổi lên mà không ai thấy.
    """
    if line.closing_qty <= _QTY_TOL:
        return []
    moved = line.in_qty > _QTY_TOL or line.out_qty > _QTY_TOL
    if line.closing_value is None or abs(line.closing_value) > _VALUE_TOL or not moved:
        return []
    if line.in_value is not None and abs(line.in_value) > _VALUE_TOL:
        return []
    return [_finding(
        "zero_valued_stock", "cao", line,
        "Hàng có số lượng nhưng không ghi nhận giá trị",
        {"tồn_cuối": line.closing_qty, "nhập": line.in_qty, "xuất": line.out_qty,
         "giá_trị_ghi_sổ": 0},
        "Nếu là hàng nhà cung cấp tài trợ thì hợp lệ. Nếu là hàng mua để khuyến "
        "mại thì chi phí đang bị bỏ ngoài sổ → lãi gộp đang cao hơn thực tế.",
    )]


# ---------------------------------------------------------------------------
# Kiểm toán toàn bảng
# ---------------------------------------------------------------------------

def audit_inventory(
    lines: list[InventoryLine],
    warehouse: str = "",
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
) -> dict[str, Any]:
    """
    Chạy toàn bộ kiểm tra trên một bảng TỔNG HỢP TỒN KHO.

    Trả dict có cấu trúc để nhánh REPORT diễn giải — cùng hình dạng quy ước với
    reporting.build_report (`summary` / `explain` / `warnings`) nên model đã học
    nhánh đó đọc được ngay, không cần train thêm.
    """
    period_days = _period_days(period_start, period_end)
    findings: list[dict[str, Any]] = []
    methods: dict[str, list[str]] = {}

    for line in lines:
        findings += _check_balance(line)
        findings += _check_negative(line)
        findings += _check_value_sign(line)
        findings += _check_cost_drift(line)
        findings += _check_dead_and_slow(line, period_days)
        findings += _check_price_jump(line)
        findings += _check_zero_value(line)

        if (m := _costing_method(line)):
            methods.setdefault(m, []).append(line.code)

    findings += _check_method_consistency(lines, methods)

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9),
                                 -(f["money_impact"] or 0)))

    summary, warnings = _summarize(lines, period_days)
    high = [f for f in findings if f["severity"] == "cao"]
    if high:
        warnings.append(
            f"{len(high)} phát hiện mức CAO ảnh hưởng trực tiếp đến con số lãi — "
            "cần đối chiếu sổ chi tiết trước khi dùng báo cáo này để quyết định."
        )

    return {
        "warehouse": warehouse,
        "period": {"start": period_start, "end": period_end, "days": period_days},
        "summary": summary,
        "findings": findings,
        "explain": {
            "confidence": "cao" if not high else "trung bình",
            "checks_run": [
                "cân đối số lượng & giá trị", "tồn kho âm",
                "số lượng và giá trị ngược dấu", "trôi giá vốn tồn so với đã bán",
                "phương pháp tính giá vốn", "hàng chết & bán chậm",
                "biến động giá nhập", "hàng không ghi nhận giá trị",
            ],
            "costing_methods_detected": {k: sorted(v) for k, v in methods.items()},
            "note": (
                "Mọi phát hiện đều dựa trên chính bảng này, không suy đoán. "
                "money_impact là ước lượng quy mô tiền liên quan, không phải "
                "tiền mất."
            ),
            "limits": (
                "Bảng tổng hợp KHÔNG cho thấy giá từng lô nhập, nên không thể "
                "kết luận sổ ghi sai chỉ vì đơn giá tồn cuối cao hơn giá nhập "
                "bình quân — với FIFO và giá tăng trong kỳ, đó là kết quả đúng. "
                "Muốn kết luận về giá vốn phải đối chiếu sổ chi tiết theo lô."
            ),
        },
        "warnings": warnings,
    }


def _check_method_consistency(
    lines: list[InventoryLine], methods: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """
    Hai phương pháp tính giá vốn trong cùng một sổ, cùng một kỳ.

    VAS 02 buộc áp dụng nhất quán. Không nhất quán thì lãi gộp giữa các mặt hàng
    không so sánh được với nhau — mà "mặt hàng nào lãi nhất" lại đúng là câu chủ
    DN hỏi nhiều nhất.
    """
    if len(methods) < 2:
        return []

    by_code = {ln.code: ln for ln in lines}
    # Phương pháp thiểu số là nghi phạm — báo chênh lệch nếu quy về đa số.
    major = max(methods, key=lambda k: len(methods[k]))
    minor_codes = [c for m, cs in methods.items() if m != major for c in cs]

    delta_total = 0.0
    details = []
    for code in minor_codes:
        ln = by_code[code]
        if ln.opening_value is None or ln.in_value is None or ln.out_value is None:
            continue
        wavg = (ln.opening_value + ln.in_value) / (ln.opening_qty + ln.in_qty)
        delta = wavg * ln.out_qty - ln.out_value
        delta_total += delta
        details.append({"mã": code, "giá_vốn_ghi": round(ln.out_value),
                        "nếu_theo_bình_quân": round(wavg * ln.out_qty),
                        "chênh": round(delta)})

    return [_finding(
        "costing_method_mixed", "cao", None,
        f"Hai phương pháp tính giá vốn chạy song song: {' và '.join(sorted(methods))}",
        {"phương_pháp": {k: sorted(v) for k, v in methods.items()},
         "đa_số": major, "chi_tiết_thiểu_số": details},
        "VAS 02 buộc áp dụng nhất quán. Đang lệch thì lãi gộp giữa các mặt hàng "
        "không so sánh được — chọn một phương pháp và tính lại cả kỳ.",
        money_impact=delta_total if details else None,
    )]


def _summarize(
    lines: list[InventoryLine], period_days: int
) -> tuple[dict[str, Any], list[str]]:
    """Số tổng của kỳ. Mã thiếu giá trị được ĐẾM RIÊNG, không cộng như 0."""
    warnings: list[str] = []

    def total(attr: str) -> tuple[float, int]:
        s, missing = 0.0, 0
        for ln in lines:
            v = getattr(ln, attr)
            if v is None:
                missing += 1
            else:
                s += v
        return s, missing

    opening, m1 = total("opening_value")
    inbound, m2 = total("in_value")
    outbound, m3 = total("out_value")
    closing, m4 = total("closing_value")
    missing = max(m1, m2, m3, m4)
    if missing:
        warnings.append(
            f"{missing}/{len(lines)} mã thiếu cột giá trị — số tổng dưới đây chỉ "
            "tính trên phần có dữ liệu."
        )

    avg_stock = (opening + closing) / 2
    turnover = outbound / avg_stock if avg_stock > 0 else None
    days_on_hand = (
        avg_stock / (outbound / period_days)
        if outbound > 0 and period_days > 0 else None
    )

    cross_dock = [
        ln for ln in lines
        if ln.in_qty > _QTY_TOL
        and abs(ln.in_qty - ln.out_qty) <= _QTY_TOL
        and abs(ln.closing_qty) <= _QTY_TOL
    ]

    return {
        "sku_count": len(lines),
        "opening_value": round(opening),
        "in_value": round(inbound),
        "out_value": round(outbound),          # = giá vốn hàng bán của kỳ
        "closing_value": round(closing),
        "turnover": round(turnover, 2) if turnover else None,
        "days_on_hand": round(days_on_hand) if days_on_hand else None,
        # Mã "mua đứt bán đoạn": nhập bao nhiêu xuất hết bấy nhiêu. Nhóm này đặt
        # hàng theo đơn nên KHÔNG cần dự báo tồn kho — chỉ cần chốt giá nhanh.
        "cross_dock_skus": len(cross_dock),
        "cross_dock_value": round(sum(ln.in_value or 0 for ln in cross_dock)),
    }, warnings


def _period_days(start: Optional[str], end: Optional[str]) -> int:
    if not start or not end:
        return 0
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10])
    except ValueError:
        return 0
    return max(0, (d1 - d0).days)


# ---------------------------------------------------------------------------
# Cầu nối sang reporting.py — lấp chỗ giá vốn còn thiếu
# ---------------------------------------------------------------------------

def unit_cost_of(line: InventoryLine) -> tuple[Optional[float], str]:
    """
    Đơn giá vốn của một dòng, KÈM chỗ nó được lấy ra.

    Ưu tiên đơn giá XUẤT (đúng nghĩa giá vốn hàng bán trong kỳ). Mã không phát
    sinh xuất thì lùi về đơn giá tồn cuối, rồi tồn đầu — vẫn là giá vốn hợp lệ
    để ước lượng, chỉ kém chính xác hơn.

    Trả cả nguồn vì ba mức này KHÔNG đáng tin như nhau: "xuất" là giá vốn thật
    đã phát sinh, còn "tồn đầu" chỉ là giá của hàng chưa bán được ngày nào. Ai
    nhìn con số cũng phải biết mình đang nhìn loại nào.
    """
    for value, source in (
        (line.out_unit(), "xuất"),
        (line.closing_unit(), "tồn cuối"),
        (line.opening_unit(), "tồn đầu"),
    ):
        if value is not None and value > 0:
            return value, source
    return None, ""


def unit_cost_table(lines: list[InventoryLine]) -> dict[str, float]:
    """Bảng tra đơn giá vốn theo mã hàng VÀ theo tên hàng."""
    table: dict[str, float] = {}
    for ln in lines:
        cost, _ = unit_cost_of(ln)
        if cost is None:
            continue
        for key in (ln.code, ln.name):
            k = (key or "").strip()
            if k:
                table[k] = cost
    return table


def fill_missing_cogs(sales: list[Any], table: dict[str, float]) -> dict[str, Any]:
    """
    Điền `cogs` cho các dòng bán đang thiếu, bằng đơn giá vốn × số lượng.

    SỬA TẠI CHỖ danh sách `sales` (list[reporting.SaleLine]) và trả về thống kê
    để báo cáo nói thật được nguồn gốc con số: giá vốn ước từ bảng tồn kho KHÔNG
    giống giá vốn ghi theo từng phiếu xuất, và người đọc phải biết điều đó.

    Dòng thiếu số lượng thì BỎ QUA — không có gì để nhân, và đoán bừa ở đây sẽ
    tạo ra đúng loại "con số nghe có vẻ đúng" mà cả module này sinh ra để tránh.
    """
    filled = skipped_no_match = skipped_no_qty = already = 0

    for s in sales:
        if getattr(s, "cogs", None) is not None:
            already += 1
            continue
        name = (getattr(s, "product", "") or "").strip()
        cost = table.get(name)
        if cost is None:
            skipped_no_match += 1
            continue
        qty = getattr(s, "quantity", 0) or 0
        if qty <= 0:
            skipped_no_qty += 1
            continue
        s.cogs = cost * qty
        filled += 1

    total = len(sales)
    notes = []
    if filled:
        notes.append(
            f"{filled} dòng bán được điền giá vốn ƯỚC TÍNH từ bảng tồn kho "
            "(đơn giá xuất bình quân × số lượng), không phải giá vốn theo từng phiếu."
        )
    if skipped_no_match:
        notes.append(f"{skipped_no_match} dòng không khớp được mã/tên hàng nào trong bảng tồn kho.")
    if skipped_no_qty:
        notes.append(f"{skipped_no_qty} dòng thiếu số lượng nên không suy ra được giá vốn.")

    return {
        "filled": filled,
        "already_had_cogs": already,
        "skipped_no_match": skipped_no_match,
        "skipped_no_quantity": skipped_no_qty,
        "coverage_pct": round((filled + already) / total * 100, 1) if total else 0.0,
        "notes": notes,
    }


__all__ = [
    "InventoryLine",
    "audit_inventory",
    "unit_cost_table",
    "fill_missing_cogs",
]
