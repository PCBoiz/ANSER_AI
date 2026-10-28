"""
src/core/doc_dau_vao.py — đọc ĐẦU VÀO của tool từ chính câu người dùng, bằng mã.

VÌ SAO (BR-04 §5.2, BR-05; chủ dự án chốt 28/10/2026)
-----------------------------------------------------
Chốt neo số liệu (`guard_answer`) soi CÂU TRẢ LỜI so với KẾT QUẢ tool. Nó mù
trước lỗi ở chiều ngược lại: model CHÉP SAI ĐẦU VÀO rồi tool tính đúng trên số
sai. Đo được trên vLLM thật: hoá đơn hai dòng 5.000.000 + 500.000, model gửi
cho `vat` đúng MỘT dòng, Brain trả lời "tổng thực tế 5.500.000đ" kèm "kết quả
từ công cụ VAT" — sai mà trông có nguồn.

Hai cách, áp TUỲ TRƯỜNG HỢP:

  B — mã bóc thay model, khi câu có cấu trúc đọc được:
      `tach_hoa_don`  hoá đơn dán (JSON, hoặc các dòng "tên: số")  -> `vat`
      `tach_loi_chao` nhiều lời chào giá trong câu                -> `carrier_selection`
  A — lưới cho mọi trường hợp còn lại (`so_tien_bi_bo_sot`): mọi số tiền người
      dùng đưa ra phải có mặt trong tham số gửi cho tool. Thiếu thì KHÔNG chạy
      tool, hỏi lại đích danh số bị bỏ sót.

Mọi hàm ở đây là mã tất định, không gọi model, không đụng mạng — chỉ thư viện
chuẩn, để test được ở mọi máy.

A soát HAI CHIỀU (bổ sung 28/10 sau lần chạy thật):
  - `so_tien_bi_bo_sot`          số trong câu không có trong tham số -> chép THIẾU
  - `so_tien_khong_co_trong_cau` số tiền trong tham số không có trong câu -> BỊA
Số đọc được cả viết bằng chữ ("năm triệu rưỡi", "hai trăm nghìn") lẫn kiểu nói
tắt ("5 triệu rưỡi", "12tr5", "5 triệu 200 nghìn").

`co_so_thue` đọc câu nói giá ĐÃ GỒM hay CHƯA GỒM VAT. Không nói rõ thì `vat`
hỏi lại (chủ dự án chốt 28/10): hiểu sai chỗ này là lệch nguyên khoản thuế.

GIỚI HẠN, CÓ CHỦ ĐÍCH
---------------------
- Số chữ chỉ được coi là TIỀN khi có đơn vị nghìn/triệu/tỷ ("năm trăm" trơn,
  "năm 2026" không phải tiền).
- `tach_*` chỉ nhận dạng câu có cấu trúc rõ. Không nhận ra thì trả None/[] và
  tầng trên giữ nguyên tham số của model — không đoán.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------------------
# Đọc số tiền
# ---------------------------------------------------------------------------

# Đơn vị nhân. "tr" phải đứng riêng (\b) để không nuốt chữ "trả", "trong".
_HE_SO = {
    "tỷ": 1_000_000_000, "ty": 1_000_000_000,
    "triệu": 1_000_000, "trieu": 1_000_000, "tr": 1_000_000,
    "nghìn": 1_000, "ngàn": 1_000, "nghin": 1_000, "ngan": 1_000, "k": 1_000,
}
_DON_VI_TIEN = r"đồng|dong|vnđ|vnd|đ|d"

_SO = re.compile(
    r"(?<![\w.,/])"                                   # không dính vào số/chữ phía trước
    r"(?P<so>\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
    r"(?![\d/])"                                      # không phải mảnh ngày "20/12"
    r"(?:\s*(?P<dv>tỷ|ty|triệu|trieu|tr|nghìn|ngàn|nghin|ngan|k|" + _DON_VI_TIEN + r")"
    # Nói tắt sau đơn vị: "5 triệu rưỡi", "12tr5", "5 triệu 2." — chữ số lẻ chỉ
    # nhận khi đứng cuối cụm, nên "5 triệu 2 chuyến" không thành 5.200.000.
    r"(?:\s*(?P<ruoi>rưỡi|ruoi)"
    r"|\s*(?P<le>\d{1,3})(?=\s*(?:$|[,;!?)\n]|\.(?!\d)|đồng|dong|đ(?!\w))))?"
    r")?"
    r"(?![\wđ%])",                                    # đơn vị là trọn từ; loại "8%"
    re.IGNORECASE,
)


def _thanh_so(chuoi: str, dv: str | None) -> int | None:
    nhom_nghin = re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", chuoi)
    he_so = _HE_SO.get((dv or "").lower())
    if he_so:
        # Có nhóm nghìn thì dấu là dấu NGĂN NGHÌN: "1.500 nghìn" = 1.500.000.
        # Không có thì là dấu thập phân: "5,4 triệu", "1.5 tỷ".
        gia_tri = (float(re.sub(r"[.,]", "", chuoi)) if nhom_nghin
                   else float(chuoi.replace(",", ".")))
        return round(gia_tri * he_so)
    if nhom_nghin:
        return int(re.sub(r"[.,]", "", chuoi))                  # "12.500.000"
    if dv:                                                       # "500000đ"
        return int(float(chuoi.replace(",", "."))) if "." not in chuoi and "," not in chuoi else None
    if chuoi.isdigit() and len(chuoi) >= 5 and not chuoi.startswith("0"):
        return int(chuoi)                                        # số trần trong JSON dán kèm
    return None                                                  # "3 cái", "2026", "40 feet"


def _gia_tri(m: re.Match) -> int | None:
    v = _thanh_so(m.group("so"), m.group("dv"))
    he_so = _HE_SO.get((m.group("dv") or "").lower())
    if v is None or not he_so:
        return v
    if m.group("ruoi"):
        return v + he_so // 2                                     # "5 triệu rưỡi"
    if m.group("le"):
        le = m.group("le")
        return v + int(le) * he_so // 10 ** len(le)               # "12tr5", "5 triệu 200"
    return v


# Số viết bằng chữ. Không dấu chỉ nhận những chữ ít nhập nhằng; "tư", "lăm",
# "nhăm", "mốt" chỉ là số khi đứng ngay sau "mươi".
_CHU_SO = {
    "không": 0, "khong": 0, "một": 1, "mot": 1, "hai": 2, "ba": 3, "bốn": 4,
    "bon": 4, "năm": 5, "nam": 5, "sáu": 6, "sau": 6, "bảy": 7, "bẩy": 7,
    "bay": 7, "tám": 8, "tam": 8, "chín": 9, "chin": 9,
}
_SAU_MUOI = {"mốt": 1, "tư": 4, "lăm": 5, "nhăm": 5, "lam": 5}
_MUOI = {"mươi", "muoi"}
_TRAM = {"trăm", "tram"}
_LINH = {"linh", "lẻ"}
_RUOI = {"rưỡi", "ruoi"}
_DON_VI_CHU = {
    "nghìn": 1_000, "ngàn": 1_000, "nghin": 1_000, "ngan": 1_000,
    "triệu": 1_000_000, "trieu": 1_000_000, "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
}
_TU_SO = (set(_CHU_SO) | set(_SAU_MUOI) | _MUOI | {"mười"} | _TRAM | _LINH | _RUOI
          | set(_DON_VI_CHU))


def _gia_tri_chu(tu: list[str]) -> int | None:
    """Một cụm số bằng chữ -> VND. None = không hợp ngữ pháp số, hoặc không có
    đơn vị nghìn/triệu/tỷ (khi đó không coi là tiền)."""
    tong = nhom = 0
    cho = None                   # chữ số đang chờ: chưa biết là hàng trăm, chục hay đơn vị
    don_vi = None                # đơn vị gần nhất đã gặp
    truoc = None
    for t in tu:
        if t in _SAU_MUOI and truoc in (_MUOI | {"mười"}):
            if cho is not None:
                return None
            cho = _SAU_MUOI[t]
        elif t in _CHU_SO:
            if cho is not None:                       # hai chữ số liền nhau: "hai ba triệu"
                return None
            cho = _CHU_SO[t]
        elif t in _MUOI and cho:                      # "hai mươi"
            nhom, cho = nhom + cho * 10, None
        elif t == "mười" or (t in _MUOI and cho is None):   # "mười", "muoi" không dấu
            nhom += 10
        elif t in _TRAM:
            if not cho:
                return None
            nhom, cho = nhom + cho * 100, None
        elif t in _LINH:
            if truoc not in _TRAM:
                return None
        elif t in _DON_VI_CHU:
            v = nhom + (cho or 0)
            if not v:
                return None
            don_vi = _DON_VI_CHU[t]
            tong, nhom, cho = tong + v * don_vi, 0, None
        elif t in _RUOI:
            if truoc in _TRAM:
                nhom += 50                            # "trăm rưỡi" = 150
            elif truoc in _DON_VI_CHU:
                tong += _DON_VI_CHU[truoc] // 2       # "năm triệu rưỡi"
            else:
                return None
        else:
            return None
        truoc = t
    if not don_vi:
        return None
    du = nhom + (cho or 0)
    if du:
        # Nói tắt sau đơn vị: "năm triệu hai" = 5,2 triệu; "hai triệu năm trăm"
        # = 2 triệu 500 nghìn.
        tong += du * don_vi // 10 if (nhom == 0 and du < 10) else du * don_vi // 1000
    return tong or None


def _so_bang_chu(cau: str) -> list[tuple[int, int]]:
    """[(vị trí, giá trị)] cho mọi cụm số viết bằng chữ có đơn vị."""
    ra: list[tuple[int, int]] = []
    cum: list[re.Match] = []

    def chot() -> None:
        tu = [m.group(0).lower() for m in cum]
        i = 0
        while i < len(tu):
            for j in range(len(tu), i, -1):           # cụm dài nhất hợp lệ từ i
                v = _gia_tri_chu(tu[i:j])
                if v:
                    ra.append((cum[i].start(), v))
                    i = j
                    break
            else:
                i += 1

    for m in re.finditer(r"[^\W\d_]+", cau):
        la_tu_so = m.group(0).lower() in _TU_SO
        if la_tu_so and cum and not cau[cum[-1].end():m.start()].strip():
            cum.append(m)
            continue
        chot()
        cum = [m] if la_tu_so else []
    chot()
    return ra


def doc_so_tien(cau: str) -> list[int]:
    """
    Mọi số tiền trong câu, theo thứ tự xuất hiện (VND, số nguyên).

    Nhận: "12.500.000 đồng", "7.450.000đ", "5 triệu", "5,4 triệu", "15tr", "500k",
    "28.500 đồng/lít", số trần >= 5 chữ số (JSON dán kèm); nói tắt "5 triệu
    rưỡi", "12tr5", "5 triệu 200 nghìn"; chữ "năm triệu rưỡi", "hai trăm nghìn".
    Bỏ: phần trăm ("8%"), ngày ("20/12", "26/10/2026"), năm, số lượng ("3 cái"),
    số bắt đầu bằng 0 (điện thoại, mã).
    """
    q = unicodedata.normalize("NFC", cau or "")
    ra: list[tuple[int, int]] = []
    truoc: re.Match | None = None
    for m in _SO.finditer(q):
        v = _gia_tri(m)
        if not v or v <= 0:
            truoc = None
            continue
        # "5 triệu 200 nghìn" là MỘT khoản: gộp khi chỉ cách nhau khoảng trắng và
        # đơn vị sau nhỏ hơn đơn vị trước.
        hs = _HE_SO.get((m.group("dv") or "").lower())
        hs_truoc = truoc is not None and _HE_SO.get((truoc.group("dv") or "").lower())
        if (hs and hs_truoc and hs < hs_truoc and v < hs_truoc
                and not q[truoc.end():m.start()].strip()):
            ra[-1] = (ra[-1][0], ra[-1][1] + v)
            truoc = None
            continue
        ra.append((m.start(), v))
        truoc = m
    ra.extend(_so_bang_chu(q))
    return [v for _, v in sorted(ra, key=lambda x: x[0])]


# ---------------------------------------------------------------------------
# A — chốt neo đầu vào
# ---------------------------------------------------------------------------

def _so_trong_tham_so(args: Any) -> set[int]:
    """Mọi con số trong tham số, cộng tích đơn giá × số lượng của từng dòng hàng."""
    gom: set[int] = set()

    def di(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            gom.add(round(x))
        elif isinstance(x, dict):
            gia = x.get("price")
            sl = x.get("qty")
            if isinstance(gia, (int, float)) and isinstance(sl, (int, float)) \
                    and not isinstance(gia, bool) and not isinstance(sl, bool):
                gom.add(round(gia * sl))     # người dùng hay viết thành tiền của dòng
            for v in x.values():
                di(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                di(v)

    di(args)
    return gom


def so_tien_bi_bo_sot(cau: str, args: dict) -> list[int]:
    """
    Số tiền có trong câu người dùng mà KHÔNG có mặt trong tham số gửi cho tool.

    Rỗng = tham số phủ đủ mọi số người dùng đưa ra. Không rỗng = model chép
    thiếu hoặc chép sai — chạy tool lúc này là tính đúng trên đầu vào sai.
    """
    co = _so_trong_tham_so(args)
    thieu: list[int] = []
    for v in doc_so_tien(cau):
        if v not in co and v not in thieu:
            thieu.append(v)
    return thieu


# Khoá mang SỐ TIỀN trong tham số của `vat` / `quote`. Chiều "bịa" chỉ soi các
# khoá này: `qty`, `%`, `fuel_sensitivity` không phải tiền và người dùng hay
# nói theo đơn vị khác ("5 tấn" -> 5000 kg).
_KHOA_TIEN = {
    "price", "stated_total", "carrier_cost", "current_fuel_price",
    "fuel_baseline_price", "min_margin_amount", "amount",
}


def so_tien_khong_co_trong_cau(cau: str, args: dict, bo_qua: tuple[str, ...] = ()) -> list[int]:
    """
    Số tiền model ĐIỀN vào tham số mà người dùng KHÔNG hề đưa — chiều ngược của
    `so_tien_bi_bo_sot`. Không rỗng = model bịa hoặc chép sai chữ số; chạy tool
    lúc này là tính đúng trên một con số không có nguồn.

    Đơn giá của dòng hàng được chấp nhận khi chính nó HOẶC thành tiền
    (đơn giá × số lượng) có trong câu. `bo_qua`: khoá cấp cao do MÃ điền (ví dụ
    `items` sau khi cách B bóc), không phải model.
    """
    trong_cau = set(doc_so_tien(cau))
    bia: list[int] = []

    def la_so(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def ghi(v: float) -> None:
        v = round(v)
        if v > 0 and v not in trong_cau and v not in bia:
            bia.append(v)

    def di(x: Any) -> None:
        if isinstance(x, dict):
            gia, sl = x.get("price"), x.get("qty")
            if la_so(gia) and not (la_so(sl) and round(gia * sl) in trong_cau):
                ghi(gia)
            for k, v in x.items():
                if k in _KHOA_TIEN and k != "price" and la_so(v):
                    ghi(v)
                elif isinstance(v, (dict, list, tuple)):
                    di(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                di(v)

    di({k: v for k, v in (args or {}).items() if k not in bo_qua})
    return bia


# ---------------------------------------------------------------------------
# Giá đã gồm VAT hay chưa — câu hỏi nghiệp vụ, mã KHÔNG đoán
# ---------------------------------------------------------------------------

_DA_GOM_VAT = re.compile(
    r"(?:đã|da)\s+(?:bao\s+)?(?:gồm|gom|có|co|tính|tinh)\s+(?:cả\s+|ca\s+)?(?:thuế|thue|vat|gtgt)"
    r"|(?:bao\s+gồm|bao\s+gom|gồm|gom)\s+(?:cả\s+|ca\s+)?(?:thuế|thue|vat|gtgt)"
    r"|sau\s+(?:thuế|thue|vat)|incl\.?\s*vat|giá\s+có\s+vat",
    re.IGNORECASE,
)
_CHUA_GOM_VAT = re.compile(
    r"(?:chưa|chua|không|khong)\s+(?:bao\s+)?(?:gồm\s+|gom\s+|có\s+|co\s+|tính\s+|tinh\s+)?"
    r"(?:cả\s+|ca\s+)?(?:thuế|thue|vat|gtgt)"
    r"|trước\s+(?:thuế|vat)|truoc\s+(?:thue|vat)|excl\.?\s*vat",
    re.IGNORECASE,
)
# Hoá đơn GTGT ghi riêng một dòng tiền thuế ("VAT: 650.000", khoá JSON "vat")
# -> các dòng hàng là giá trước thuế.
_DONG_THUE_RIENG = re.compile(
    r"(?:^|[\n;{,\"'])\s*(?:tiền\s+)?(?:thuế|thue|vat|gtgt|tax)[^:\n\"'=%]{0,20}[\"']?\s*[:=]\s*\d[\d.,]*(?!\s*%)\s*(?:$|[\n;,}đdv])",
    re.IGNORECASE,
)

# Câu hỏi lại — cũng là MỐC để nhận ra câu trả lời ở lượt sau.
MOC_HOI_THUE = "là giá chưa gồm VAT hay đã gồm VAT"
CAU_HOI_THUE = (
    f"Các số tiền trên hoá đơn {MOC_HOI_THUE}? Bạn trả lời \"chưa gồm VAT\" "
    "hoặc \"đã gồm VAT\" là tôi tính tiếp ngay — hiểu sai chỗ này là lệch "
    "nguyên khoản thuế."
)


def co_so_thue(cau: str) -> str | None:
    """
    "chua_gom" | "da_gom" | None. None = câu không nói, hoặc nói cả hai chiều
    (mâu thuẫn) — tầng trên hỏi lại, không đoán.
    """
    q = unicodedata.normalize("NFC", cau or "")
    # "chưa gồm VAT" chứa "gồm VAT": soát chiều phủ định trước rồi xoá nó đi.
    chua = bool(_CHUA_GOM_VAT.search(q) or _DONG_THUE_RIENG.search(q))
    da = bool(_DA_GOM_VAT.search(_CHUA_GOM_VAT.sub(" ", q)))
    if chua == da:
        return None
    return "chua_gom" if chua else "da_gom"


def noi_tra_loi_hoi_thue(cau: str, history: list[dict] | None) -> str | None:
    """
    Lượt trước Brain hỏi `CAU_HOI_THUE`, lượt này người dùng trả lời "chưa gồm
    VAT" -> ghép tin nhắn hoá đơn của lượt trước với câu trả lời, để `vat` chạy
    lại trên ĐỦ dữ liệu. None khi không phải câu trả lời cho câu hỏi đó.
    """
    if co_so_thue(cau) is None or not history:
        return None
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") != "assistant":
            continue
        if MOC_HOI_THUE not in str(history[i].get("content") or ""):
            return None
        for j in range(i - 1, -1, -1):
            if history[j].get("role") == "user":
                return f"{history[j].get('content')}\n{cau}"
        return None
    return None


TOOL_DOC_TU_CAU = ("vat", "quote", "carrier_selection")


def chot_dau_vao(ten: str, args: dict, cau: str) -> tuple[dict, str | None, str]:
    """
    MỘT chỗ duy nhất quyết định đầu vào tool lấy từ câu người dùng — `chat.py`
    gọi lúc phục vụ, `benchmark_v3.py` gọi lúc đo (R4: đo đúng thứ chạy thật).

    Trả (args, câu_hỏi_lại | None, lý_do). `lý_do`:
      ""               không áp dụng (tool khác, câu rỗng, hoặc bóc không được)
      "boc_loi_chao"   carrier_selection: mã dựng carriers/offers từ câu
      "ok"             vat/quote: đầu vào khớp câu, chạy tool được
      "bo_sot"         có số tiền trong câu mà tham số thiếu
      "bia"            tham số có số tiền không có trong câu
      "thue"           vat: câu không nói giá đã gồm VAT hay chưa
    """
    args = dict(args or {})
    if not cau or ten not in TOOL_DOC_TU_CAU:
        return args, None, ""

    if ten == "carrier_selection":
        tu_cau = tham_so_chon_nha_xe(cau)
        return ({**args, **tu_cau}, None, "boc_loi_chao") if tu_cau else (args, None, "")

    ma_dien: tuple[str, ...] = ()
    if ten == "vat":
        dong = tach_hoa_don(cau)
        if dong:
            args, ma_dien = {**args, "items": dong}, ("items",)

    bo_sot = so_tien_bi_bo_sot(cau, args)
    if bo_sot:
        ds = ", ".join(dinh_dang_vnd(v) for v in bo_sot)
        cach_viet = (
            "Bạn liệt kê lại giúp tôi từng khoản (tên: số tiền), mỗi khoản một "
            "dòng, kèm tổng ghi trên hoá đơn nếu có nhé."
            if ten == "vat" else
            "Bạn cho tôi biết rõ khoản đó là giá nhà xe chào, giá dầu hiện tại, "
            "giá dầu lúc chốt bảng giá, hay một phụ phí nhé."
        )
        return args, (
            f"Tôi chưa đưa được khoản {ds} đồng trong tin nhắn của bạn vào phép "
            "tính, nên chưa dám trả lời — tính thiếu một khoản là ra con số sai. "
            + cach_viet
        ), "bo_sot"

    bia = so_tien_khong_co_trong_cau(cau, args, bo_qua=ma_dien)
    if bia:
        ds = ", ".join(dinh_dang_vnd(v) for v in bia)
        return args, (
            f"Tôi không thấy khoản {ds} đồng trong tin nhắn của bạn, nên không "
            "dùng nó để tính — tôi không tự thêm số. Bạn gửi lại đủ các khoản "
            "(tên: số tiền) giúp tôi nhé."
        ), "bia"

    if ten == "vat":
        co_so = co_so_thue(cau)
        if co_so is None:
            return args, CAU_HOI_THUE, "thue"
        args = {**args, "prices_include_vat": co_so == "da_gom"}
    return args, None, "ok"


def dinh_dang_vnd(v: int) -> str:
    return f"{v:,}".replace(",", ".")


# ---------------------------------------------------------------------------
# B — hoá đơn dán kèm -> dòng hàng cho `vat`
# ---------------------------------------------------------------------------

# Nhãn KHÔNG phải dòng hàng: tổng, thuế, chiết khấu… Bóc nhầm "Tổng cộng" thành
# một dòng hàng là cộng tổng vào chính nó.
_KHONG_PHAI_DONG_HANG = re.compile(
    r"tổng|tong|total|thuế|thue|vat|gtgt|chiết khấu|chiet khau|giảm giá|giam gia"
    r"|discount|tax|subtotal|cộng|cong tien",
    re.IGNORECASE,
)
_KHOA_TEN = ("name", "ten", "tên", "description", "item")
_KHOA_GIA = ("price", "unit_price", "don_gia", "đơn_giá", "gia")
_KHOA_SL = ("qty", "quantity", "so_luong", "số_lượng", "sl")


def _lay(d: dict, khoa: tuple[str, ...]) -> Any:
    for k in khoa:
        if k in d:
            return d[k]
    return None


def _dong_tu_json(obj: Any) -> list[dict] | None:
    # {"items": [...], ...}
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        obj = obj["items"]
    # [{"name":…, "unit_price":…, "quantity":…}, …]
    if isinstance(obj, list):
        ra = []
        for d in obj:
            if not isinstance(d, dict):
                return None
            gia, sl = _lay(d, _KHOA_GIA), _lay(d, _KHOA_SL)
            if isinstance(gia, bool) or not isinstance(gia, (int, float)):
                return None
            if sl is None:
                sl = 1
            if isinstance(sl, bool) or not isinstance(sl, (int, float)):
                return None
            ra.append({"name": str(_lay(d, _KHOA_TEN) or "Unknown"), "price": gia, "qty": sl})
        return ra or None
    # {"Cước vận chuyển HN-HP": 5000000, "Phụ phí xăng dầu": 500000}
    if isinstance(obj, dict):
        ra = []
        for ten, gia in obj.items():
            if _KHONG_PHAI_DONG_HANG.search(str(ten)):
                continue
            if isinstance(gia, bool) or not isinstance(gia, (int, float)):
                return None
            ra.append({"name": str(ten), "price": gia, "qty": 1})
        return ra or None
    return None


_DONG_TEN_SO = re.compile(r"^\s*[-•*+]?\s*(?P<ten>[^:\n]{1,60}?)\s*[:=]\s*(?P<so>.+?)\s*$")


def tach_hoa_don(cau: str) -> list[dict] | None:
    """
    Dòng hàng của MỘT tờ hoá đơn dán trong câu, dạng `VatItem` (`name`, `price`,
    `qty`). None = không nhận ra cấu trúc nào — tầng trên giữ nguyên `items` của
    model, không đoán.

    Nhận hai dạng:
      1. JSON: object `{"tên": số}`, mảng dòng hàng, hoặc `{"items": [...]}`
      2. Từ HAI dòng trở lên dạng "tên: số tiền" (mỗi dòng một khoản)
    """
    q = cau or ""
    # 1. JSON — thử từ khối ngoặc lớn nhất trở xuống
    for m in re.finditer(r"[\[{]", q):
        for dong in (q.rfind("}"), q.rfind("]")):
            if dong > m.start():
                try:
                    ra = _dong_tu_json(json.loads(q[m.start():dong + 1]))
                except (ValueError, TypeError):
                    continue
                if ra:
                    return ra
    # 2. Các dòng "tên: số"
    ra = []
    for dong in re.split(r"[\n;]", q):
        m = _DONG_TEN_SO.match(dong)
        if not m or _KHONG_PHAI_DONG_HANG.search(m.group("ten")):
            continue
        so = doc_so_tien(m.group("so"))
        if len(so) == 1:
            ra.append({"name": m.group("ten").strip(), "price": so[0], "qty": 1})
    return ra if len(ra) >= 2 else None


# ---------------------------------------------------------------------------
# B — nhiều lời chào giá -> carriers/offers cho `carrier_selection`
# ---------------------------------------------------------------------------

# Chỉ gỡ động từ CÓ DẤU (cộng "chao"/"bao gia" không dấu, ít khi là tên riêng).
# "gia", "la" không dấu thì không gỡ: nhà xe "Phú Gia" phải giữ nguyên tên.
_DUOI_DONG_TU = re.compile(
    r"(?:\s*(?:vừa\s+)?(?:chào\s+giá|chào|chao|báo\s+giá|bao\s+gia|báo|chốt|giá|là|[=:-]))+\s*$",
    re.IGNORECASE,
)
# Không gỡ "bên": "Bên A chào …" thì "Bên A" là tên.
_DAU_THUA = re.compile(r"^\s*(?:còn|và|với|rồi)\s+", re.IGNORECASE)
_CHIET_KHAU = re.compile(r"(?:chiết khấu|chiet khau|ck)\s*(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)
_CONG_NO = re.compile(r"(?:công nợ|cong no)\s*(\d+)\s*(?:ngày|ngay)", re.IGNORECASE)


def tach_loi_chao(cau: str) -> list[dict]:
    """
    Các lời chào giá trong câu: `[{"ten", "gia", "chiet_khau_pct", "cong_no_ngay"}]`.

    Tên nhà xe = đoạn chữ ngay trước số tiền, tính từ dấu ngăn gần nhất (, ; :
    xuống dòng), bỏ động từ "chào/báo/chốt" và từ nối "còn/và". Điều khoản đọc
    trong đoạn từ sau số tiền tới số tiền kế tiếp. Lời chào không có tên thì bỏ.
    """
    q = cau or ""
    so = [(m, _gia_tri(m)) for m in _SO.finditer(q)]
    so = [(m, v) for m, v in so if v]
    ra: list[dict] = []
    for i, (m, gia) in enumerate(so):
        dau = max(q.rfind(c, 0, m.start()) for c in ",;:\n")
        if i > 0:
            dau = max(dau, so[i - 1][0].end())
        ten = _DAU_THUA.sub("", _DUOI_DONG_TU.sub("", q[dau + 1:m.start()])).strip(" ,.;:-")
        if not ten or len(ten) > 40 or not re.search(r"[^\W\d_]", ten):
            continue
        het = so[i + 1][0].start() if i + 1 < len(so) else len(q)
        duoi = q[m.end():het]
        ck, cn = _CHIET_KHAU.search(duoi), _CONG_NO.search(duoi)
        if any(r["ten"].lower() == ten.lower() for r in ra):
            continue
        ra.append({
            "ten": ten,
            "gia": gia,
            "chiet_khau_pct": float(ck.group(1).replace(",", ".")) if ck else None,
            "cong_no_ngay": int(cn.group(1)) if cn else None,
        })
    return ra


def tham_so_chon_nha_xe(cau: str) -> dict | None:
    """
    `carriers` + `offers` cho `/tools/carrier-selection` dựng từ câu. None khi
    bóc được dưới hai lời chào — không có gì để so.

    `vehicle_types` để rỗng: câu không nói nhà xe nào có xe gì, và lọc cứng của
    tool bỏ qua kiểm loại xe khi danh sách rỗng — không đoán.
    """
    loi_chao = tach_loi_chao(cau)
    if len(loi_chao) < 2:
        return None
    carriers, offers = [], []
    for i, lc in enumerate(loi_chao, 1):
        ma = f"C{i}"
        carriers.append({"id": ma, "name": lc["ten"], "vehicle_types": [],
                         "discount_pct": lc["chiet_khau_pct"],
                         "credit_days": lc["cong_no_ngay"]})
        offers.append({"carrier_id": ma, "price": lc["gia"]})
    return {"carriers": carriers, "offers": offers}


__all__ = [
    "CAU_HOI_THUE",
    "MOC_HOI_THUE",
    "TOOL_DOC_TU_CAU",
    "chot_dau_vao",
    "co_so_thue",
    "dinh_dang_vnd",
    "doc_so_tien",
    "noi_tra_loi_hoi_thue",
    "so_tien_bi_bo_sot",
    "so_tien_khong_co_trong_cau",
    "tach_hoa_don",
    "tach_loi_chao",
    "tham_so_chon_nha_xe",
]
