"""
offline_training/eval_ke_toan.py — đo lớp kiểm KẾ TOÁN, và chặn hồi quy.

VÌ SAO CẦN, KHI ĐÃ CÓ 826 TEST
------------------------------
Test đơn vị trả lời "hàm này có làm đúng thứ tôi nghĩ không". Bộ eval này trả
lời hai câu khác hẳn, mà không test đơn vị nào trả lời được:

  1. Trên MỘT BỘ SỔ THẬT, ta bắt được bao nhiêu phần lỗi, và báo oan bao nhiêu?
  2. Luật mới thêm hôm nay có làm hỏng luật cũ không?

Câu 2 đã hỏng một lần rồi: phép kiểm hàng giá trị 0 từng báo oan 29/38 dòng
trên kho khuyến mại — mọi test đơn vị vẫn xanh, vì mỗi hàm vẫn làm đúng thứ nó
được viết ra để làm.

HAI CÁCH ĐO CHO HAI LOẠI CÂU HỎI
--------------------------------
* Dữ liệu thật (đã ẩn danh) — KHÔNG ai biết chắc sổ có bao nhiêu lỗi, nên không
  chấm đúng/sai được. Ở đây chốt kết quả hôm nay làm MỐC và báo khi nó ĐỔI.
* Ca GIEO LỖI — lỗi do chính ta đặt vào bản đã ẩn danh đó, nên biết chắc đáp án.
  Ở đây chấm bắt được / báo oan, kèm khoảng tin cậy.

Gieo lỗi vào chính dữ liệu thật chứ không dựng bảng bịa: một bảng bịa đẹp đẽ
không có kho khuyến mại giá trị 0, không có hai phương pháp giá vốn chạy song
song, và không có mã hàng bị sửa hồi tố.

MỘT ĐIỀU PHẢI NÓI THẲNG
-----------------------
Đáp án của các ca gieo lỗi do TÔI đặt, chưa kế toán nào xác nhận. Bộ eval này đo
được "code có làm đúng thứ ta định không" và "hôm nay có khác hôm qua không".
Nó KHÔNG chứng minh được "cách hiểu nghiệp vụ của ta là đúng". Muốn cái đó thì
phải có kế toán thật rà một vòng — không bộ eval tự dựng nào thay được.

CHẠY
----
    python -m offline_training.eval_ke_toan            # báo cáo đầy đủ
    python -m offline_training.eval_ke_toan --json kq.json
    python -m offline_training.eval_ke_toan --cap-nhat-moc   # chốt mốc mới
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.core.inventory import audit_inventory
from src.core.inventory_import import parse_inventory_table
from src.core.partner_import import parse_partner_table
from src.core.period_diff import doi_chieu_hai_lan_xuat
from src.core.receivables import audit_partners
from src.core.vat_catalog import audit_vat_catalog, parse_product_table
from offline_training.stats import wilson

GOC = Path(__file__).resolve().parent.parent
DU_LIEU = GOC / "tests" / "du_lieu_eval"
MOC = DU_LIEU / "moc.json"

Luoi = list[list[Any]]


def nap(ten: str) -> Luoi:
    return json.loads((DU_LIEU / f"{ten}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Chạy bốn lớp kiểm trên bộ dữ liệu
# ---------------------------------------------------------------------------

def _dau_van(f: dict[str, Any]) -> tuple[str, str, Any]:
    """Dấu vân của một phát hiện — đủ để so hai lần chạy, không phụ thuộc câu chữ."""
    return (f["kind"], f["code"] or "", f["money_impact"])


def chay_ton_kho(luoi: Luoi) -> list[dict[str, Any]]:
    r = parse_inventory_table(luoi)
    return audit_inventory(r.lines, warehouse=r.warehouse,
                           period_start=r.period_start,
                           period_end=r.period_end)["findings"]


def chay_doi_tac(kh: Luoi, ncc: Luoi, gia_von_ngay: float | None = None) -> list[dict[str, Any]]:
    return audit_partners(parse_partner_table(kh).partners,
                          parse_partner_table(ncc).partners,
                          gia_von_moi_ngay=gia_von_ngay)["findings"]


def chay_thue(luoi: Luoi) -> list[dict[str, Any]]:
    return audit_vat_catalog(parse_product_table(luoi).products)["findings"]


def chay_hai_ky(cu: Luoi, moi: Luoi) -> list[dict[str, Any]]:
    return doi_chieu_hai_lan_xuat(parse_inventory_table(cu),
                                  parse_inventory_table(moi))["findings"]


GIA_VON_NGAY = 7_833_688_922 / 223      # từ chính bộ dữ liệu, không đặt bừa


def chay_tat_ca() -> dict[str, list[dict[str, Any]]]:
    """Bốn lớp kiểm trên bộ dữ liệu chưa động vào."""
    return {
        "ton_kho": chay_ton_kho(nap("ton_kho_11_08")),
        "ton_kho_km": chay_ton_kho(nap("ton_kho_km_24_07")),
        "doi_tac": chay_doi_tac(nap("khach_hang"), nap("nha_cung_cap"), GIA_VON_NGAY),
        "thue": chay_thue(nap("hang_hoa")),
        "hai_ky": chay_hai_ky(nap("ton_kho_24_07"), nap("ton_kho_11_08")),
    }


# ---------------------------------------------------------------------------
# Ca gieo lỗi — lỗi đặt vào bản đã ẩn danh, đáp án biết trước
# ---------------------------------------------------------------------------

@dataclass
class CaGieo:
    ma: str
    lop: str                       # khớp khoá trong chay_tat_ca()
    mo_ta: str
    gieo: Callable[[dict[str, Luoi]], None]
    mong_doi_kind: str
    mong_doi_code: str = ""
    # Phát hiện khác được phép mọc thêm do chính phép gieo (không tính là báo oan).
    keo_theo: tuple[str, ...] = field(default_factory=tuple)


def _o(luoi: Luoi, ma_hang: str) -> list[Any]:
    """Dòng của một mã hàng trong bảng tồn kho."""
    for r in luoi:
        if len(r) > 1 and str(r[1]).strip() == ma_hang:
            return r
    raise KeyError(ma_hang)


def _o_doi_tac(luoi: Luoi, ma: str) -> list[Any]:
    for r in luoi:
        if len(r) > 1 and str(r[1]).strip() == ma:
            return r
    raise KeyError(ma)


# Cột bảng tồn kho: 0 kho, 1 mã, 2 tên, 3 đvt, 4-6 đầu kỳ, 7-9 nhập,
# 10-12 xuất, 13-15 cuối kỳ (SL / giá trị / đơn giá).
def _gieo_ton_am(d):
    r = _o(d["ton_kho_11_08"], "VT00001")
    r[10] = float(r[10]) + 100_000      # xuất vọt lên
    r[13] = float(r[4]) + float(r[7]) - float(r[10])


def _gieo_lech_can_doi(d):
    r = _o(d["ton_kho_11_08"], "VT00002")
    r[13] = float(r[13]) + 37           # cuối kỳ không còn bằng ĐK+N-X


def _gieo_gia_tri_am_sl_duong(d):
    r = _o(d["ton_kho_11_08"], "VT00003")
    r[14] = -abs(float(r[14])) - 1_000


def _gieo_het_hang_con_gia_tri(d):
    r = _o(d["ton_kho_11_08"], "VT00004")
    r[13] = 0
    r[14] = 5_000_000


def _gieo_gia_nhap_vot(d):
    r = _o(d["ton_kho_11_08"], "VT00005")
    r[8] = float(r[8]) * 3              # giá trị nhập gấp ba, số lượng giữ nguyên


def _gieo_mst_sai(d):
    r = _o_doi_tac(d["khach_hang"], "KH00002")
    s = str(r[5])
    r[5] = s[:-1] + str((int(s[-1]) + 1) % 10)


def _gieo_mst_trung(d):
    a = _o_doi_tac(d["khach_hang"], "KH00003")
    b = _o_doi_tac(d["khach_hang"], "KH00004")
    b[5] = a[5]


def _gieo_cong_no_am(d):
    r = _o_doi_tac(d["khach_hang"], "KH00008")
    r[4] = -abs(float(r[4]) or 1) - 9_000_000


def _gieo_to_chuc_thieu_mst(d):
    r = _o_doi_tac(d["khach_hang"], "KH00009")
    r[5] = ""


def _gieo_hang_chiu_ttdb(d):
    for r in d["hang_hoa"]:
        if len(r) > 2 and str(r[1]).strip() == "VT00010":
            r[2] = "Rượu vang Đà Lạt biếu khách"
            return
    raise KeyError("VT00010")


def _gieo_xuat_giam_hoi_to(d):
    """
    Phải đọc kỳ TRƯỚC rồi mới đặt số, chứ không trừ đại một lượng.

    Bản đầu trừ cứng 50 khỏi kỳ sau — nhưng VT00007 bán thêm hơn 50 đơn vị giữa
    hai kỳ, nên sau khi trừ nó VẪN cao hơn kỳ trước và không có gì bất thường
    để bắt. Ca eval khi đó báo "BỎ SÓT" cho một phép kiểm hoàn toàn đúng: bộ đo
    hỏng, không phải bộ được đo hỏng.
    """
    truoc = float(_o(d["ton_kho_24_07"], "VT00007")[10])
    r = _o(d["ton_kho_11_08"], "VT00007")
    r[10] = truoc - 50                  # kỳ sau xuất ÍT hơn kỳ trước 50 đơn vị
    r[13] = float(r[4]) + float(r[7]) - r[10]


def _gieo_dau_ky_doi(d):
    r = _o(d["ton_kho_11_08"], "VT00011")
    r[4] = float(r[4]) + 25


CAC_CA: tuple[CaGieo, ...] = (
    CaGieo("ton_am", "ton_kho", "Xuất vượt xa số có -> tồn cuối âm",
           _gieo_ton_am, "negative_stock", "VT00001",
           keo_theo=("value_sign_conflict", "cost_drift", "rising_cost_basis",
                     "falling_cost_basis", "slow_moving", "dead_stock",
                     "costing_method_mixed")),
    CaGieo("lech_can_doi", "ton_kho", "ĐK + Nhập − Xuất ≠ CK",
           _gieo_lech_can_doi, "balance_mismatch", "VT00002",
           keo_theo=("costing_method_mixed", "rising_cost_basis")),
    CaGieo("gia_tri_am", "ton_kho", "Còn hàng nhưng giá trị âm",
           _gieo_gia_tri_am_sl_duong, "value_sign_conflict", "VT00003",
           keo_theo=("balance_mismatch", "costing_method_mixed",
                     "rising_cost_basis", "falling_cost_basis")),
    CaGieo("het_hang_con_tien", "ton_kho", "Hết hàng mà vẫn treo giá trị",
           _gieo_het_hang_con_gia_tri, "value_sign_conflict", "VT00004",
           keo_theo=("balance_mismatch", "costing_method_mixed")),
    CaGieo("gia_nhap_vot", "ton_kho", "Giá nhập gấp ba",
           _gieo_gia_nhap_vot, "price_jump", "VT00005",
           keo_theo=("balance_mismatch", "costing_method_mixed",
                     "rising_cost_basis", "falling_cost_basis")),
    CaGieo("mst_sai", "doi_tac", "Mã số thuế sai số kiểm tra",
           _gieo_mst_sai, "invalid_tax_id", "KH00002"),
    CaGieo("mst_trung", "doi_tac", "Hai khách dùng chung một mã số thuế",
           _gieo_mst_trung, "duplicate_partner", "KH00003"),
    # `customer_concentration` và `receivable_days_high` tính trên TỔNG phải thu,
    # nên đổi số dư một khách là chúng đổi theo — dấu vân khác đi và trông như
    # phát hiện mới. Đó là hệ quả đúng của phép gieo, không phải báo oan.
    CaGieo("cong_no_am", "doi_tac", "Khách có số dư phải thu âm",
           _gieo_cong_no_am, "negative_receivable", "KH00008",
           keo_theo=("customer_concentration", "receivable_days_high")),
    CaGieo("thieu_mst", "doi_tac", "Tổ chức không có mã số thuế",
           _gieo_to_chuc_thieu_mst, "missing_tax_id", "KH00009"),
    CaGieo("hang_ttdb", "thue", "Hàng chịu thuế TTĐB lẫn trong danh mục",
           _gieo_hang_chiu_ttdb, "vat_rate_review", "VT00010",
           keo_theo=("vat_reduction_missed", "vat_needs_human")),
    CaGieo("xuat_giam", "hai_ky", "Kỳ dài hơn mà xuất luỹ kế giảm",
           _gieo_xuat_giam_hoi_to, "history_decreased", "VT00007"),
    CaGieo("dau_ky_doi", "hai_ky", "Tồn đầu kỳ đổi giữa hai lần xuất",
           _gieo_dau_ky_doi, "opening_changed", "VT00011"),
)


def _chay_lop(lop: str, d: dict[str, Luoi]) -> list[dict[str, Any]]:
    if lop == "ton_kho":
        return chay_ton_kho(d["ton_kho_11_08"])
    if lop == "doi_tac":
        return chay_doi_tac(d["khach_hang"], d["nha_cung_cap"], GIA_VON_NGAY)
    if lop == "thue":
        return chay_thue(d["hang_hoa"])
    if lop == "hai_ky":
        return chay_hai_ky(d["ton_kho_24_07"], d["ton_kho_11_08"])
    raise ValueError(lop)


def cham_gieo_loi() -> dict[str, Any]:
    """Từng ca: gieo một lỗi, xem có bắt được không, và có mọc thêm gì không."""
    goc = {t: nap(t) for t in ("ton_kho_11_08", "ton_kho_24_07", "khach_hang",
                               "nha_cung_cap", "hang_hoa")}
    nen = {lop: {_dau_van(f) for f in _chay_lop(lop, goc)}
           for lop in ("ton_kho", "doi_tac", "thue", "hai_ky")}

    ket: list[dict[str, Any]] = []
    for ca in CAC_CA:
        d = copy.deepcopy(goc)
        ca.gieo(d)
        moi = _chay_lop(ca.lop, d)
        them = [f for f in moi if _dau_van(f) not in nen[ca.lop]]

        bat_duoc = any(
            f["kind"] == ca.mong_doi_kind
            and (not ca.mong_doi_code or f["code"] == ca.mong_doi_code)
            for f in them
        )
        cho_phep = {ca.mong_doi_kind, *ca.keo_theo}
        bao_oan = sorted({(f["kind"], f["code"]) for f in them
                          if f["kind"] not in cho_phep})
        ket.append({
            "ma": ca.ma, "lớp": ca.lop, "mô_tả": ca.mo_ta,
            "mong_đợi": f"{ca.mong_doi_kind}/{ca.mong_doi_code}",
            "bắt_được": bat_duoc,
            "báo_oan": bao_oan,
            "số_phát_hiện_mọc_thêm": len(them),
        })

    bat = sum(1 for r in ket if r["bắt_được"])
    sach = sum(1 for r in ket if not r["báo_oan"])
    n = len(ket)
    return {
        "ca": ket,
        "tóm_tắt": {
            "số_ca": n,
            "bắt_được": bat,
            "tỷ_lệ_bắt": wilson(bat, n).__dict__,
            "ca_không_báo_oan": sach,
            "tỷ_lệ_sạch": wilson(sach, n).__dict__,
        },
    }


# ---------------------------------------------------------------------------
# Mốc — chốt kết quả hôm nay để biết ngày mai có đổi không
# ---------------------------------------------------------------------------

def dung_moc() -> dict[str, Any]:
    return {lop: sorted([list(_dau_van(f)) for f in fs])
            for lop, fs in chay_tat_ca().items()}


def so_voi_moc() -> dict[str, Any]:
    if not MOC.exists():
        return {"có_mốc": False}
    cu = json.loads(MOC.read_text(encoding="utf-8"))
    nay = dung_moc()
    ra: dict[str, Any] = {"có_mốc": True, "khớp": True, "lớp": {}}
    for lop in sorted(set(cu) | set(nay)):
        a = {tuple(x) for x in cu.get(lop, [])}
        b = {tuple(x) for x in nay.get(lop, [])}
        mat, moc_them = sorted(a - b), sorted(b - a)
        ra["lớp"][lop] = {
            "số_phát_hiện": len(b),
            "biến_mất": [list(x) for x in mat],
            "mọc_thêm": [list(x) for x in moc_them],
        }
        if mat or moc_them:
            ra["khớp"] = False
    return ra


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Đo lớp kiểm kế toán")
    p.add_argument("--json", help="ghi kết quả ra file")
    p.add_argument("--cap-nhat-moc", action="store_true",
                   help="chốt kết quả hôm nay làm mốc mới")
    a = p.parse_args(argv)

    if a.cap_nhat_moc:
        MOC.write_text(json.dumps(dung_moc(), ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"Đã ghi mốc mới: {MOC}")
        return 0

    gieo = cham_gieo_loi()
    hoi_quy = so_voi_moc()

    print("=" * 76)
    print("GIEO LỖI — lỗi đặt vào sổ thật đã ẩn danh, đáp án biết trước")
    print("=" * 76)
    for r in gieo["ca"]:
        dau = "bắt được " if r["bắt_được"] else "BỎ SÓT   "
        oan = f"  BÁO OAN: {r['báo_oan']}" if r["báo_oan"] else ""
        print(f"  [{dau}] {r['ma']:<20} {r['mô_tả'][:44]:<46}{oan}")

    t = gieo["tóm_tắt"]
    print(f"\n  bắt được  {t['bắt_được']}/{t['số_ca']}   "
          f"khoảng {t['tỷ_lệ_bắt']['thap']:.1%}–{t['tỷ_lệ_bắt']['cao']:.1%}")
    print(f"  không oan {t['ca_không_báo_oan']}/{t['số_ca']}   "
          f"khoảng {t['tỷ_lệ_sạch']['thap']:.1%}–{t['tỷ_lệ_sạch']['cao']:.1%}")

    print()
    print("=" * 76)
    print("HỒI QUY — sổ thật, so với mốc đã chốt")
    print("=" * 76)
    if not hoi_quy["có_mốc"]:
        print("  Chưa có mốc. Chạy --cap-nhat-moc để chốt lần đầu.")
    else:
        for lop, v in hoi_quy["lớp"].items():
            dau = "KHÁC MỐC" if (v["biến_mất"] or v["mọc_thêm"]) else "khớp   "
            print(f"  [{dau}] {lop:<12} {v['số_phát_hiện']} phát hiện")
            for x in v["biến_mất"]:
                print(f"        BIẾN MẤT: {x}")
            for x in v["mọc_thêm"]:
                print(f"        MỌC THÊM: {x}")

    kq = {"gieo_loi": gieo, "hoi_quy": hoi_quy}
    if a.json:
        Path(a.json).write_text(json.dumps(kq, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"\nĐã ghi {a.json}")

    dat = (t["bắt_được"] == t["số_ca"]
           and t["ca_không_báo_oan"] == t["số_ca"]
           and hoi_quy.get("khớp", True))
    print("\n" + ("ĐẠT" if dat else "KHÔNG ĐẠT"))
    return 0 if dat else 1


if __name__ == "__main__":
    sys.exit(main())
