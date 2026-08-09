"""
offline_training/compare_runs.py — so HAI lần chạy benchmark THEO CẶP.

VÌ SAO CẦN
----------
Trước bản này, baseline và bản tinh chỉnh được so bằng cách mở hai file .txt và
nhìn hai con số. Cách đó bỏ sót đúng thứ nguy hiểm nhất.

Hai bản chạy trên CÙNG một bộ câu hỏi, nên mỗi câu là một cặp có đối chứng. Bỏ
thông tin cặp đi rồi so hai số trung bình là vứt gần hết sức mạnh thống kê, và
quan trọng hơn — nó giấu hoàn toàn **vùng thoái lui**:

    baseline  70%  ->  tinh chỉnh  70%

Nhìn thì "không đổi gì". Nhưng có thể bản mới đã làm hỏng 3 câu và sửa được 3
câu khác. Ba câu hỏng đó là ba tình huống khách từng dùng được, nay không dùng
được nữa — và không con số trung bình nào cho thấy điều đó.

CÁCH DÙNG
---------
    python offline_training/benchmark_v3.py --model Qwen/Qwen3-8B --no-gate \
        --json /content/baseline.json
    python offline_training/benchmark_v3.py --model $AWQ_DIR \
        --json /content/tuned.json
    python -m offline_training.compare_runs /content/baseline.json /content/tuned.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.stats import mcnemar, wilson


def _doc(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"Không có file {path}. Chạy benchmark_v3.py với --json trước.")
    except json.JSONDecodeError as exc:
        sys.exit(f"{path} không phải JSON hợp lệ: {exc}")


def _khop_theo_id(a: dict, b: dict) -> tuple[list[bool], list[bool], list[str], list[str]]:
    """
    Ghép hai lần chạy THEO `_id`, không theo thứ tự.

    Ghép theo vị trí là sai ngay khi một lần chạy dùng `--max-samples` hoặc bộ
    eval được sinh lại — và sai kiểu im lặng: mọi câu bị so với một câu khác,
    cho ra một bảng kết quả trông hoàn toàn bình thường.
    """
    ma = dict(zip(a.get("row_ids") or [], a.get("per_row") or []))
    mb = dict(zip(b.get("row_ids") or [], b.get("per_row") or []))
    chung = [i for i in (a.get("row_ids") or []) if i in mb]
    chi_a = [i for i in ma if i not in mb]
    chi_b = [i for i in mb if i not in ma]
    return [ma[i] for i in chung], [mb[i] for i in chung], chung, chi_a + chi_b


def so_mot_muc(ten: str, a: dict, b: dict) -> None:
    va, vb, ids, lech = _khop_theo_id(a, b)
    if not ids:
        print(f"\n[{ten}] không có câu nào chung giữa hai lần chạy — bỏ qua")
        return

    ka, kb = wilson(sum(va), len(va)), wilson(sum(vb), len(vb))
    kq = mcnemar(va, vb)

    print(f"\n{'─' * 66}")
    print(f"[{ten}]  {len(ids)} câu chung" + (f"  (bỏ {len(lech)} câu chỉ có ở một bên)" if lech else ""))
    print(f"  bản A (nền)      {ka}")
    print(f"  bản B (tinh chỉnh) {kb}")

    if ka.thap < kb.cao and kb.thap < ka.cao:
        print("    hai khoảng CHỒNG NHAU — nhìn riêng từng bản thì chưa kết luận được")

    print(f"\n  So theo cặp — chỉ {kq.khac_biet} câu hai bên khác nhau mang thông tin:")
    print(f"    B sửa được    {kq.chi_B_dung:3d} câu")
    print(f"    B LÀM HỎNG    {kq.chi_A_dung:3d} câu   ← số trung bình giấu con số này")
    print(f"    cả hai đúng   {kq.ca_hai_dung:3d}")
    print(f"    cả hai sai    {kq.ca_hai_sai:3d}")
    print(f"    p = {kq.p_value:.4f}  ->  ", end="")
    if kq.khac_biet == 0:
        print("hai bản cho kết quả GIỐNG HỆT nhau trên mọi câu")
    elif kq.dang_ke:
        ai = "B hơn A" if kq.chi_B_dung > kq.chi_A_dung else "A hơn B"
        print(f"khác biệt ĐÁNG KỂ ({ai})")
    else:
        print("CHƯA đủ bằng chứng — khác biệt này không phân biệt được với ngẫu nhiên")

    hong = [i for i, x, y in zip(ids, va, vb) if x and not y]
    if hong:
        print(f"\n  ⚠ {len(hong)} câu bản mới LÀM HỎNG: {', '.join(hong[:12])}"
              + (" …" if len(hong) > 12 else ""))
        print("    Đây là những tình huống trước đó dùng được, nay không.")


def main() -> None:
    p = argparse.ArgumentParser(description="So hai lần chạy benchmark theo cặp")
    p.add_argument("nen", help="JSON của bản nền (baseline)")
    p.add_argument("moi", help="JSON của bản tinh chỉnh")
    args = p.parse_args()

    a, b = _doc(args.nen), _doc(args.moi)
    print("=" * 66)
    print("  SO HAI LẦN CHẠY THEO CẶP")
    print(f"  A (nền)       : {a.get('model', '?')}")
    print(f"  B (tinh chỉnh): {b.get('model', '?')}")
    print("=" * 66)

    sa, sb = a.get("sections") or {}, b.get("sections") or {}
    chung = [m for m in sa if m in sb]
    if not chung:
        sys.exit("Hai file không có mục nào chung. Hai lần chạy có dùng cùng --skip không?")

    for muc in chung:
        so_mot_muc(muc, sa[muc], sb[muc])

    thieu = sorted(set(sa) ^ set(sb))
    if thieu:
        print(f"\n(chỉ một bên có: {', '.join(thieu)})")

    print(f"\n{'=' * 66}")
    print("Đọc bảng trên: dòng 'B LÀM HỎNG' là dòng quan trọng nhất. Điểm trung")
    print("bình tăng mà dòng đó lớn nghĩa là model đổi tính chứ không phải giỏi lên.")


if __name__ == "__main__":
    main()
