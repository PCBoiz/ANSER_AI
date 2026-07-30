"""
offline_training/calibrate.py — CLI Giai đoạn 0: đối chiếu engine với giá thật.

Chạy được ngay trên máy, không cần GPU, không cần model. Đây là việc CHẶN mọi
giai đoạn khác trong ROADMAP.md.

    # 1. Sinh file mẫu, gửi khách điền
    python -m offline_training.calibrate template --out bao_gia_lich_su.csv

    # 2. Khách điền xong -> đối chiếu với quy tắc giá đang giả định
    python -m offline_training.calibrate pricing --csv bao_gia_lich_su.csv \
        --margin 10 --fuel-sens 0.35 --fuel-baseline 25000

    # 3. Trọng số chọn nhà xe (cần 2 file, xem `template --what carriers`)
    python -m offline_training.calibrate carriers \
        --carriers nha_xe.csv --choices lua_chon.csv

Mọi con số in ra đều đến từ src/core/calibration.py, chạy qua đúng
`compute_quote` / `select_carrier` của production (P4).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.calibration import (  # noqa: E402
    CarrierChoiceCase,
    HistoricalQuote,
    fit_carrier_weights,
    fit_pricing_rule,
    replay_carrier_choices,
    replay_pricing,
)
from src.core.carrier_selection import Carrier, QuoteOffer, RouteRequest  # noqa: E402
from src.core.inventory_import import parse_vn_number  # noqa: E402
from src.core.pricing import PricingRule, Surcharge  # noqa: E402

QUOTE_FIELDS = [
    "quote_id", "date", "route", "vehicle_type",
    "carrier_cost", "fuel_price", "actual_price", "surcharges", "note",
]
CARRIER_FIELDS = [
    "carrier_id", "name", "vehicle_types", "depot_lat", "depot_lon",
    "discount_pct", "credit_days", "years_partner", "on_time_rate",
]
CHOICE_FIELDS = [
    "case_id", "origin", "destination", "vehicle_type",
    "origin_lat", "origin_lon", "carrier_id", "offer_price", "chosen", "note",
]

_QUOTE_SAMPLE = [
    ["BG001", "2026-03-14", "Hà Nội → Đà Nẵng", "xe tải 5 tấn",
     "12000000", "25400", "13800000", "bốc xếp:500000", "khách quen, bớt chút"],
    ["BG002", "2026-04-02", "Hà Nội → TP.HCM", "container 20ft",
     "28000000", "26100", "31500000", "", ""],
]


def _num(value: Any) -> Optional[float]:
    """
    Số từ ô CSV — dùng CHUNG hàm đọc số của trình nhập tồn kho (P4).

    Bản viết riêng trước đây đọc '25.000' thành 25.0 vì chỉ gộp dấu chấm khi có
    từ hai dấu trở lên. Ô hay bị nhất chính là `fuel_price`, mà sai 1000 lần ở
    đó thì `fuel_ratio` thành 0,001 và toàn bộ hiệu chỉnh nhiên liệu hoá rác —
    im lặng, không một dòng cảnh báo. Hai nơi đọc số kiểu Việt Nam thì phải
    dùng chung một hàm, không viết lại lần thứ hai.
    """
    return parse_vn_number(value)


def _parse_surcharges(text: str) -> list[Surcharge]:
    """'bốc xếp:500000;chờ:200000' -> [Surcharge, Surcharge]"""
    out = []
    for part in (text or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, raw = part.partition(":")
        amount = _num(raw)
        if amount is not None:
            out.append(Surcharge(name=name.strip(), amount=amount))
    return out


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Lệnh: template
# ---------------------------------------------------------------------------

def cmd_template(args) -> int:
    out = Path(args.out)
    if args.what == "quotes":
        rows, header = _QUOTE_SAMPLE, QUOTE_FIELDS
    elif args.what == "carriers":
        header = CARRIER_FIELDS
        rows = [["NX01", "Nhà xe Minh Thành", "xe tải 5 tấn|xe tải 8 tấn",
                 "20.98", "105.81", "3", "30", "6", "0.94"]]
    else:
        header = CHOICE_FIELDS
        rows = [["C001", "Hà Nội", "Đà Nẵng", "xe tải 5 tấn",
                 "21.02", "105.85", "NX01", "12000000", "1", ""]]

    if out.exists() and not args.force:
        print(f"✗ {out} đã tồn tại. Thêm --force nếu muốn ghi đè.")
        return 1
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"✓ Đã tạo {out}")
    print(f"  Cột: {', '.join(header)}")
    if args.what == "quotes":
        print("\n  LƯU Ý khi khách điền:")
        print("  - carrier_cost = giá NHÀ XE báo cho mình hôm đó")
        print("  - actual_price = giá MÌNH BÁO cho khách cuối và đã CHỐT")
        print("  - fuel_price   = giá dầu ngày hôm đó (bắt buộc nếu muốn")
        print("                   hiệu chỉnh hệ số nhiên liệu)")
        print("  - surcharges   = 'tên:số tiền', nhiều khoản ngăn bằng dấu ;")
        print("  - Cần 15-20 dòng, TRẢI ĐỀU nhiều mức giá dầu khác nhau.")
    return 0


# ---------------------------------------------------------------------------
# Lệnh: pricing
# ---------------------------------------------------------------------------

def _load_quotes(path: Path) -> tuple[list[HistoricalQuote], list[str]]:
    rows, skipped = [], []
    for i, raw in enumerate(_read_rows(path), start=2):
        cost = _num(raw.get("carrier_cost"))
        actual = _num(raw.get("actual_price"))
        if not cost or not actual:
            skipped.append(f"dòng {i}: thiếu carrier_cost hoặc actual_price")
            continue
        rows.append(HistoricalQuote(
            quote_id=(raw.get("quote_id") or f"dòng{i}").strip(),
            date=(raw.get("date") or "").strip(),
            route=(raw.get("route") or "").strip(),
            vehicle_type=(raw.get("vehicle_type") or "").strip(),
            carrier_cost=cost,
            actual_price=actual,
            fuel_price=_num(raw.get("fuel_price")),
            surcharges=_parse_surcharges(raw.get("surcharges", "")),
            note=(raw.get("note") or "").strip(),
        ))
    return rows, skipped


def _print_pricing(report: dict[str, Any]) -> None:
    s = report["summary"]
    if not s:
        for w in report["warnings"]:
            print(f"  ⚠ {w}")
        return
    verdict = "ĐẠT" if s["passed"] else "CHƯA ĐẠT"
    print(f"  Số báo giá đối chiếu : {s['rows']}"
          + (f"   (bỏ {s['rows_dropped']} dòng lỗi)" if s.get("rows_dropped") else ""))
    print(f"  Sai lệch TB tuyệt đối: {s['mape_pct']}%   (cổng < {s['gate_pct']}%)  → {verdict}")
    print(f"  Lệch hệ thống (bias) : {s['bias_pct']:+}%")
    print(f"  Trung vị / p90 / max : {s['median_abs_dev_pct']}% / "
          f"{s['p90_abs_dev_pct']}% / {s['max_abs_dev_pct']}%")
    print(f"  Số ca trong ngưỡng   : {s['within_gate']}/{s['rows']}")
    if report.get("worst"):
        print("\n  5 ca lệch nhất:")
        for w in report["worst"]:
            print(f"    {w['quote_id']:<10} {w['route'][:28]:<28} "
                  f"thực {w['actual_price']:>12,.0f}  engine {w['predicted_price']:>12,.0f}  "
                  f"{w['deviation_pct']:+.1f}%")
    for w in report["warnings"]:
        print(f"  ⚠ {w}")


def cmd_pricing(args) -> int:
    path = Path(args.csv)
    if not path.exists():
        print(f"✗ Không thấy {path}")
        return 1
    rows, skipped = _load_quotes(path)
    for message in skipped:
        print(f"  ⚠ bỏ qua {message}")
    if not rows:
        print("✗ Không đọc được báo giá nào.")
        return 1

    rule = PricingRule(
        base_margin_pct=args.margin,
        fuel_sensitivity=args.fuel_sens,
        fuel_baseline_price=args.fuel_baseline,
        min_margin_amount=args.min_margin,
    )

    print("\n=== QUY TẮC GIÁ ĐANG GIẢ ĐỊNH ===")
    _print_pricing(replay_pricing(rows, rule))

    print("\n=== SAU KHI HIỆU CHỈNH THEO DỮ LIỆU THẬT ===")
    fit = fit_pricing_rule(rows, rule)
    if fit.get("fitted"):
        f = fit["fitted"]
        print(f"  base_margin_pct  : {args.margin} → {f['base_margin_pct']}")
        note = "" if f["fuel_sensitivity_was_fitted"] else "  (giữ nguyên — xem cảnh báo)"
        print(f"  fuel_sensitivity : {args.fuel_sens} → {f['fuel_sensitivity']}{note}")
        print(f"  Sai lệch TB      : {fit['mape_pct_current']}% → {fit['mape_pct_fitted']}%")
        print(f"  Giá dầu biến động: {fit['fuel_spread_pct']}%")
        if fit.get("gate_false_pass"):
            print("  ⛔ ĐẠT GIẢ — quy tắc cũ lọt cổng nhưng tham số vẫn sai. Dùng bộ trên.")
        print()
        _print_pricing(fit["replay_with_fitted"])
    for w in fit.get("warnings", []):
        print(f"  ⚠ {w}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"current": replay_pricing(rows, rule), "fit": fit},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n✓ Đã ghi chi tiết ra {args.json}")
    return 0


# ---------------------------------------------------------------------------
# Lệnh: carriers
# ---------------------------------------------------------------------------

def _load_carrier_cases(carriers_path: Path, choices_path: Path):
    by_id: dict[str, Carrier] = {}
    for raw in _read_rows(carriers_path):
        cid = (raw.get("carrier_id") or "").strip()
        if not cid:
            continue
        types = {t.strip() for t in (raw.get("vehicle_types") or "").split("|") if t.strip()}
        by_id[cid] = Carrier(
            id=cid, name=(raw.get("name") or cid).strip(), vehicle_types=types,
            depot_lat=_num(raw.get("depot_lat")), depot_lon=_num(raw.get("depot_lon")),
            discount_pct=_num(raw.get("discount_pct")),
            credit_days=(lambda v: None if v is None else int(v))(_num(raw.get("credit_days"))),
            years_partner=_num(raw.get("years_partner")),
            on_time_rate=_num(raw.get("on_time_rate")),
        )

    grouped: dict[str, dict[str, Any]] = {}
    for raw in _read_rows(choices_path):
        case_id = (raw.get("case_id") or "").strip()
        cid = (raw.get("carrier_id") or "").strip()
        price = _num(raw.get("offer_price"))
        if not case_id or cid not in by_id or not price:
            continue
        g = grouped.setdefault(case_id, {"offers": [], "carriers": [], "chosen": None, "raw": raw})
        g["offers"].append(QuoteOffer(carrier_id=cid, price=price))
        g["carriers"].append(by_id[cid])
        if str(raw.get("chosen", "")).strip() in {"1", "x", "X", "true", "TRUE", "có"}:
            g["chosen"] = cid

    cases = []
    for case_id, g in grouped.items():
        if g["chosen"] is None:
            continue
        r = g["raw"]
        cases.append(CarrierChoiceCase(
            case_id=case_id,
            request=RouteRequest(
                origin=(r.get("origin") or "").strip(),
                destination=(r.get("destination") or "").strip(),
                vehicle_type=(r.get("vehicle_type") or "").strip(),
                origin_lat=_num(r.get("origin_lat")), origin_lon=_num(r.get("origin_lon")),
            ),
            carriers=g["carriers"], offers=g["offers"],
            chosen_carrier_id=g["chosen"], note=(r.get("note") or "").strip(),
        ))
    return cases


def cmd_carriers(args) -> int:
    cp, hp = Path(args.carriers), Path(args.choices)
    if not cp.exists() or not hp.exists():
        print(f"✗ Cần cả hai file: {cp} và {hp}")
        return 1
    cases = _load_carrier_cases(cp, hp)
    if not cases:
        print("✗ Không dựng được ca nào (mỗi case_id cần đúng một dòng chosen=1).")
        return 1

    print("\n=== TRỌNG SỐ ĐANG GIẢ ĐỊNH ===")
    rep = replay_carrier_choices(cases)
    s = rep["summary"]
    print(f"  Chọn đúng: {s['top1_hits']}/{s['cases']}  ({s['top1_accuracy_pct']}%)")
    if s["informative_cases"] < s["cases"]:
        print(f"  Trên {s['informative_cases']} ca có từ 2 ứng viên: "
              f"{s['top1_accuracy_informative_pct']}%   ← con số đáng tin")
    for c in rep["cases"]:
        if c["khớp"]:
            continue
        tag = " [sát nút]" if c["is_close_call"] else ""
        print(f"\n  ✗ {c['case_id']}{tag}: khách chọn {c['khách_chọn']}, "
              f"engine chọn {c['engine_chọn']} (khách xếp #{c['xếp_hạng_bên_khách_chọn']})")
        for g in c["thua_ở"]:
            print(f"      thua ở {g['label']}: {g['giá_trị_bên_khách_chọn']} "
                  f"so với {g['giá_trị_bên_engine_chọn']}")
        if c["note"]:
            print(f"      ghi chú: {c['note']}")
    for w in rep["warnings"]:
        print(f"  ⚠ {w}")

    print("\n=== SAU KHI HIỆU CHỈNH ===")
    fit = fit_carrier_weights(cases)
    print(f"  Trong mẫu: {fit['accuracy_in_sample_pct']}%   "
          f"Kiểm chéo bỏ-một: {fit['accuracy_loo_pct']}%")
    if fit["moved"]:
        print("  Trọng số dịch chuyển:")
        for k, v in sorted(fit["moved"].items(), key=lambda kv: -abs(kv[1])):
            print(f"    {k:<12} {fit['base'][k]:.2f} → {fit['fitted'][k]:.2f}  ({v:+.2f})")
    else:
        print("  Không trọng số nào cần dịch chuyển.")
    for w in fit["warnings"]:
        print(f"  ⚠ {w}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calibrate", description="Giai đoạn 0 — đối chiếu engine với dữ liệu thật")
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("template", help="sinh file CSV mẫu để khách điền")
    t.add_argument("--what", choices=["quotes", "carriers", "choices"], default="quotes")
    t.add_argument("--out", default="bao_gia_lich_su.csv")
    t.add_argument("--force", action="store_true")
    t.set_defaults(func=cmd_template)

    p = sub.add_parser("pricing", help="đối chiếu công thức giá")
    p.add_argument("--csv", required=True)
    p.add_argument("--margin", type=float, default=10.0)
    p.add_argument("--fuel-sens", type=float, default=0.35)
    p.add_argument("--fuel-baseline", type=float, default=None)
    p.add_argument("--min-margin", type=float, default=0.0)
    p.add_argument("--json", default=None, help="ghi báo cáo đầy đủ ra file JSON")
    p.set_defaults(func=cmd_pricing)

    c = sub.add_parser("carriers", help="đối chiếu trọng số chọn nhà xe")
    c.add_argument("--carriers", required=True)
    c.add_argument("--choices", required=True)
    c.set_defaults(func=cmd_carriers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
