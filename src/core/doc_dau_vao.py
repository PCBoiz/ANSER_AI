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

GIỚI HẠN, CÓ CHỦ ĐÍCH
---------------------
- Số viết bằng chữ ("năm triệu rưỡi") KHÔNG đọc được. A khi đó không thấy số đó
  trong câu, nên không chặn — lỗi chép sai số viết bằng chữ vẫn lọt.
- `tach_*` chỉ nhận dạng câu có cấu trúc rõ. Không nhận ra thì trả None/[] và
  tầng trên giữ nguyên tham số của model — không đoán.
"""

from __future__ import annotations

import json
import re
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
    r"\s*(?P<dv>tỷ|ty|triệu|trieu|tr|nghìn|ngàn|nghin|ngan|k|" + _DON_VI_TIEN + r")?"
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


def doc_so_tien(cau: str) -> list[int]:
    """
    Mọi số tiền trong câu, theo thứ tự xuất hiện (VND, số nguyên).

    Nhận: "12.500.000 đồng", "7.450.000đ", "5 triệu", "5,4 triệu", "15tr", "500k",
    "28.500 đồng/lít", số trần >= 5 chữ số (JSON dán kèm).
    Bỏ: phần trăm ("8%"), ngày ("20/12", "26/10/2026"), năm, số lượng ("3 cái"),
    số bắt đầu bằng 0 (điện thoại, mã).
    """
    ra = []
    for m in _SO.finditer(cau or ""):
        v = _thanh_so(m.group("so"), m.group("dv"))
        if v and v > 0:
            ra.append(v)
    return ra


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
    so = [(m, _thanh_so(m.group("so"), m.group("dv"))) for m in _SO.finditer(q)]
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
    "dinh_dang_vnd",
    "doc_so_tien",
    "so_tien_bi_bo_sot",
    "tach_hoa_don",
    "tach_loi_chao",
    "tham_so_chon_nha_xe",
]
