"""
src/core/receivables.py — soi công nợ phải thu / phải trả từ số dư đối tác.

CÁI NÀY LÀM ĐƯỢC, CÁI KIA KHÔNG
-------------------------------
Đầu vào là số dư từng đối tác, không có ngày hoá đơn. Nên:

  làm được   mức độ tập trung · số dư ngược dấu · đối tác trùng · vừa mua vừa
             bán · mã số thuế sai · phải thu quy ra bao nhiêu ngày giá vốn
  KHÔNG làm  tuổi nợ (30/60/90 ngày) · nợ quá hạn · dự báo thu tiền

Ranh giới này được viết thẳng vào kết quả trả về (`không_phân_tích_được`) để
không ai đọc báo cáo rồi tưởng đã có phân tích tuổi nợ.

VÌ SAO TẬP TRUNG KHÁCH HÀNG LÀ RỦI RO CAO NHẤT VỚI DOANH NGHIỆP NHỎ
-------------------------------------------------------------------
Số liệu thật của Hoàng Phát: phải thu 3,88 tỷ trong khi tồn kho 2,87 tỷ — tiền
nằm ở khách nhiều hơn nằm ở kho. Hai khách lớn nhất chiếm 56% phải thu. Một
khách chậm trả là cả doanh nghiệp đứng hình, và đó không phải chuyện kho vận.
Phần mềm kế toán trình bày công nợ theo danh sách; danh sách không làm ai giật
mình, một tỷ lệ phần trăm thì có.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from src.core.findings import finding, sap_xep
from src.core.partner_import import Partner
from src.core.tax_id import chuan_hoa, kiem_ma_so_thue

# --- Ngưỡng nghiệp vụ (đổi được, có lý do) --------------------------------
_MOT_KHACH_PCT = 20.0     # một khách vượt 1/5 phải thu = mất khách đó là mất mảng lớn
_BA_KHACH_PCT = 50.0      # ba khách vượt một nửa = doanh nghiệp phụ thuộc số ít
_NGAY_PHAI_THU_CAO = 90   # quá 90 ngày giá vốn là vốn bị chiếm dụng quá lâu
_TIEN_TOL = 1.0           # đồng


def _so_du(p: Partner) -> float:
    return p.balance or 0.0


def _tong(ds: Iterable[Partner]) -> float:
    return sum(_so_du(p) for p in ds)


def _khoa(p: Partner) -> str:
    """Khoá gộp đối tác giữa hai danh sách: ưu tiên mã số thuế, không có thì mã."""
    mst = chuan_hoa(p.tax_id)
    return f"mst:{mst}" if mst else f"ma:{p.code.strip().upper()}"


# ---------------------------------------------------------------------------
# Từng phép kiểm
# ---------------------------------------------------------------------------

def _kiem_so_du_nguoc_dau(ds: list[Partner], la_khach: bool) -> list[dict[str, Any]]:
    """
    Phải thu âm = khách đã trả nhiều hơn số nợ. Phải trả âm = mình trả thừa NCC.

    Cả hai đều là TIỀN THẬT đang nằm sai chỗ, và cả hai đều không hiện lên
    trong bất kỳ báo cáo tổng nào vì chúng bị số dương của người khác che mất.
    """
    ra: list[dict[str, Any]] = []
    for p in ds:
        v = _so_du(p)
        if v >= -_TIEN_TOL:
            continue
        if la_khach:
            tieu_de = "Khách hàng có số dư phải thu ÂM"
            goi_y = ("Khách đã trả nhiều hơn số nợ ghi nhận: tiền về rồi mà hoá đơn "
                     "chưa xuất, hoặc một khoản mua hàng của chính đối tác này bị ghi "
                     "vào tài khoản phải thu. Đối chiếu sao kê với sổ chi tiết.")
        else:
            tieu_de = "Nhà cung cấp có số dư phải trả ÂM"
            goi_y = ("Đã trả nhiều hơn số nợ: tiền của mình đang nằm ở nhà cung cấp. "
                     "Đối chiếu để trừ vào đơn sau hoặc đòi lại.")
        ra.append(finding(
            "negative_receivable" if la_khach else "negative_payable",
            "trung bình", tieu_de,
            {"số_dư": v, "mã_số_thuế": p.tax_id or None},
            goi_y, code=p.code, product=p.label(), money_impact=abs(v),
        ))
    return ra


def _kiem_tap_trung(khach: list[Partner]) -> list[dict[str, Any]]:
    """Bao nhiêu phần trăm phải thu nằm ở một khách, và ở ba khách lớn nhất."""
    duong = [p for p in khach if _so_du(p) > _TIEN_TOL]
    tong = _tong(duong)
    if tong <= _TIEN_TOL or not duong:
        return []

    xep = sorted(duong, key=lambda p: -_so_du(p))
    ra: list[dict[str, Any]] = []

    dau = xep[0]
    pct = _so_du(dau) / tong * 100
    if pct >= _MOT_KHACH_PCT:
        ra.append(finding(
            "customer_concentration", "cao",
            f"Một khách chiếm {pct:.0f}% tổng phải thu",
            {"khách": dau.label(), "số_dư": _so_du(dau),
             "tổng_phải_thu": round(tong), "tỷ_lệ_%": round(pct, 1)},
            "Khách này chậm trả là dòng tiền cả công ty bị ảnh hưởng. Đặt hạn mức "
            "công nợ và điều kiện thanh toán riêng cho nhóm khách lớn.",
            code=dau.code, product=dau.label(), money_impact=_so_du(dau),
        ))

    if len(xep) >= 3:
        ba = sum(_so_du(p) for p in xep[:3])
        pct3 = ba / tong * 100
        if pct3 >= _BA_KHACH_PCT:
            ra.append(finding(
                "customer_concentration", "cao",
                f"Ba khách lớn nhất chiếm {pct3:.0f}% tổng phải thu",
                {"khách": [p.label() for p in xep[:3]],
                 "số_dư": [_so_du(p) for p in xep[:3]],
                 "tổng_phải_thu": round(tong), "tỷ_lệ_%": round(pct3, 1)},
                "Doanh nghiệp đang phụ thuộc số ít khách. Theo dõi riêng nhóm này "
                "hằng tuần thay vì gộp chung vào báo cáo công nợ.",
                money_impact=ba,
            ))
    return ra


def _kiem_vua_mua_vua_ban(
    khach: list[Partner], ncc: list[Partner]
) -> list[dict[str, Any]]:
    """
    Cùng một pháp nhân nằm ở cả hai danh sách.

    Hai số dư của cùng một đối tác nên được nhìn cùng lúc: nếu cùng dương thì
    bù trừ được, đỡ phải chuyển tiền hai chiều. Nếu số dư khách ÂM còn số dư
    nhà cung cấp bằng 0 thì gần như chắc chắn nghiệp vụ MUA đã bị ghi nhầm vào
    tài khoản phải thu.
    """
    theo_ncc: dict[str, Partner] = {_khoa(p): p for p in ncc}
    ra: list[dict[str, Any]] = []
    for k in khach:
        n = theo_ncc.get(_khoa(k))
        if n is None:
            continue
        thu, tra = _so_du(k), _so_du(n)
        if abs(thu) <= _TIEN_TOL and abs(tra) <= _TIEN_TOL:
            continue

        bang_chung = {
            "mã_khách_hàng": k.code, "số_dư_phải_thu": thu,
            "mã_nhà_cung_cấp": n.code, "số_dư_phải_trả": tra,
            "mã_số_thuế": k.tax_id or n.tax_id or None,
        }
        if thu > _TIEN_TOL and tra > _TIEN_TOL:
            tien = min(thu, tra)
            ra.append(finding(
                "partner_both_roles", "trung bình",
                "Vừa là khách vừa là nhà cung cấp — công nợ hai chiều bù trừ được",
                bang_chung | {"bù_trừ_được": round(tien)},
                "Lập biên bản bù trừ công nợ thay vì chuyển tiền hai chiều. "
                "Cần văn bản có chữ ký hai bên mới được hạch toán bù trừ.",
                code=k.code, product=k.label(), money_impact=tien,
            ))
        elif thu < -_TIEN_TOL:
            ra.append(finding(
                "partner_both_roles", "cao",
                "Đối tác vừa mua vừa bán, số dư phải thu đang ÂM",
                bang_chung,
                "Số dư phải thu âm ở một đối tác cũng là nhà cung cấp thường là do "
                "nghiệp vụ mua hàng bị ghi vào tài khoản phải thu. Tách lại theo đúng "
                "vai trò rồi mới đối chiếu số dư.",
                code=k.code, product=k.label(), money_impact=abs(thu),
            ))
        else:
            ra.append(finding(
                "partner_both_roles", "thấp",
                "Đối tác vừa là khách vừa là nhà cung cấp",
                bang_chung,
                "Theo dõi cả hai chiều để không bỏ sót cơ hội bù trừ khi cả hai "
                "số dư cùng phát sinh.",
                code=k.code, product=k.label(),
            ))
    return ra


def _kiem_ma_so_thue(ds: list[Partner], nhan: str) -> list[dict[str, Any]]:
    """Mã số thuế sai số kiểm tra, trùng nhau, hoặc thiếu ở một pháp nhân."""
    ra: list[dict[str, Any]] = []
    theo_mst: dict[str, list[Partner]] = {}

    for p in ds:
        kq = kiem_ma_so_thue(p.tax_id)
        if kq.hop_le is False:
            ra.append(finding(
                "invalid_tax_id", "cao",
                f"Mã số thuế {nhan} không hợp lệ",
                {"mã_số_thuế": p.tax_id, "lý_do": kq.ly_do, "số_dư": _so_du(p)},
                "Hoá đơn xuất với mã số thuế sai có thể bị bên mua từ chối và bị loại "
                "khấu trừ. Kiểm tra lại trên tra cứu của Tổng cục Thuế rồi sửa trong "
                "danh mục đối tác.",
                code=p.code, product=p.label(),
            ))
        elif kq.la_dinh_danh_ca_nhan:
            # Đúng khuôn theo Thông tư 86/2024/TT-BTC — không phải lỗi, chỉ là
            # không có số kiểm tra để đối chiếu. Báo ở đây là buộc tội nhầm.
            pass
        elif kq.hop_le is None and p.tax_id.strip():
            ra.append(finding(
                "invalid_tax_id", "trung bình",
                f"Mã số thuế {nhan} không đúng khuôn",
                {"mã_số_thuế": p.tax_id, "lý_do": kq.ly_do},
                "Mã số thuế phải là 10 chữ số, 13 chữ số cho đơn vị phụ thuộc, hoặc "
                "12 chữ số nếu là số định danh cá nhân.",
                code=p.code, product=p.label(),
            ))
        elif kq.hop_le is None and p.la_phap_nhan():
            ra.append(finding(
                "missing_tax_id", "trung bình",
                f"Tổ chức nhưng chưa có mã số thuế trong danh mục {nhan}",
                {"tên": p.name, "số_dư": _so_du(p)},
                "Tên có dạng tổ chức thì bắt buộc phải có mã số thuế để xuất hoá đơn. "
                "Bổ sung trước lần xuất hoá đơn tiếp theo.",
                code=p.code, product=p.label(),
            ))

        if kq.chuan_hoa:
            theo_mst.setdefault(kq.chuan_hoa, []).append(p)

    for mst, nhom in sorted(theo_mst.items()):
        if len(nhom) < 2:
            continue
        ra.append(finding(
            "duplicate_partner", "cao",
            f"Một mã số thuế dùng cho {len(nhom)} mã {nhan} khác nhau",
            {"mã_số_thuế": mst,
             "các_mã": [p.code for p in nhom],
             "tên": [p.name for p in nhom],
             "số_dư_từng_mã": [_so_du(p) for p in nhom],
             "tổng_số_dư": round(sum(_so_du(p) for p in nhom))},
            "Cùng một pháp nhân bị nhập thành nhiều đối tác — công nợ bị chia nhỏ nên "
            "nhìn nhầm là ai cũng nợ ít. Gộp về một mã rồi đối chiếu lại.",
            code=nhom[0].code, money_impact=sum(abs(_so_du(p)) for p in nhom),
        ))
    return ra


def _kiem_von_bi_chiem_dung(
    khach: list[Partner], gia_von_ngay: Optional[float]
) -> list[dict[str, Any]]:
    """Phải thu quy ra bao nhiêu ngày giá vốn — cách duy nhất nói 'nhiều' bằng số."""
    if not gia_von_ngay or gia_von_ngay <= 0:
        return []
    tong = sum(_so_du(p) for p in khach if _so_du(p) > 0)
    ngay = tong / gia_von_ngay
    if ngay < _NGAY_PHAI_THU_CAO:
        return []
    return [finding(
        "receivable_days_high", "cao",
        f"Phải thu tương đương {ngay:.0f} ngày giá vốn bán ra",
        {"tổng_phải_thu": round(tong), "giá_vốn_mỗi_ngày": round(gia_von_ngay),
         "số_ngày": round(ngay, 1), "ngưỡng": _NGAY_PHAI_THU_CAO},
        "Bán được hàng nhưng tiền chưa về: mỗi ngày bán ra đang phải chờ chừng ấy "
        "ngày mới thu được. Rút ngắn hạn thanh toán hoặc đặt hạn mức cho khách lớn.",
        money_impact=tong,
    )]


# ---------------------------------------------------------------------------
# Điểm vào
# ---------------------------------------------------------------------------

def audit_partners(
    khach_hang: list[Partner],
    nha_cung_cap: Optional[list[Partner]] = None,
    *,
    gia_von_moi_ngay: Optional[float] = None,
) -> dict[str, Any]:
    """
    Soi toàn bộ công nợ. `gia_von_moi_ngay` lấy từ tổng giá trị xuất kho chia
    số ngày của kỳ — không có thì bỏ qua phép kiểm số ngày, không đoán bừa.
    """
    ncc = list(nha_cung_cap or [])
    fs: list[dict[str, Any]] = []
    fs += _kiem_so_du_nguoc_dau(khach_hang, la_khach=True)
    fs += _kiem_so_du_nguoc_dau(ncc, la_khach=False)
    fs += _kiem_tap_trung(khach_hang)
    fs += _kiem_vua_mua_vua_ban(khach_hang, ncc)
    fs += _kiem_ma_so_thue(khach_hang, "khách hàng")
    fs += _kiem_ma_so_thue(ncc, "nhà cung cấp")
    fs += _kiem_von_bi_chiem_dung(khach_hang, gia_von_moi_ngay)

    phai_thu = sum(_so_du(p) for p in khach_hang if _so_du(p) > 0)
    phai_tra = sum(_so_du(p) for p in ncc if _so_du(p) > 0)
    tom_tat: dict[str, Any] = {
        "số_khách_hàng": len(khach_hang),
        "số_nhà_cung_cấp": len(ncc),
        "tổng_phải_thu": round(phai_thu),
        "tổng_phải_trả": round(phai_tra),
        "khách_có_số_dư": sum(1 for p in khach_hang if abs(_so_du(p)) > _TIEN_TOL),
        "số_phát_hiện": len(fs),
        "không_phân_tích_được": [
            "Tuổi nợ (30/60/90 ngày) và nợ quá hạn — số dư không kèm ngày hoá đơn. "
            "Cần thêm 'Sổ chi tiết công nợ phải thu' mới tính được.",
        ],
    }
    if gia_von_moi_ngay and gia_von_moi_ngay > 0:
        tom_tat["phải_thu_quy_ra_ngày"] = round(phai_thu / gia_von_moi_ngay, 1)
    return {"findings": sap_xep(fs), "summary": tom_tat}


def suc_khoe_von_luu_dong(
    *,
    phai_thu: float,
    phai_tra: float,
    ton_kho: float,
    gia_von_moi_ngay: Optional[float] = None,
) -> dict[str, Any]:
    """
    Ba con số kế toán quy về một câu hỏi: bao nhiêu tiền của mình đang không nằm
    trong tài khoản, và nó tương đương bao nhiêu ngày bán hàng.

    Phải thu và tồn kho là tiền mình đã bỏ ra chưa thu về; phải trả là tiền
    người khác cho mình dùng tạm. Hiệu số là vốn thực sự bị kẹt.
    """
    ket = phai_thu + ton_kho - phai_tra
    ra: dict[str, Any] = {
        "phải_thu": round(phai_thu),
        "tồn_kho": round(ton_kho),
        "phải_trả": round(phai_tra),
        "vốn_lưu_động_kẹt": round(ket),
    }
    if gia_von_moi_ngay and gia_von_moi_ngay > 0:
        ra["phải_thu_ngày"] = round(phai_thu / gia_von_moi_ngay, 1)
        ra["tồn_kho_ngày"] = round(ton_kho / gia_von_moi_ngay, 1)
        ra["phải_trả_ngày"] = round(phai_tra / gia_von_moi_ngay, 1)
        # Vòng quay tiền mặt: mua hàng → bán → thu tiền, trừ đi phần được nợ lại.
        ra["chu_kỳ_tiền_mặt_ngày"] = round(
            (phai_thu + ton_kho - phai_tra) / gia_von_moi_ngay, 1
        )
    return ra
