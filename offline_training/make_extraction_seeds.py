"""
make_extraction_seeds.py — BƯỚC 1 pipeline v3: sinh ground truth trích xuất.

VÌ SAO SINH JSON TRƯỚC, TIN NHẮN SAU (reverse-generation)
---------------------------------------------------------
Cách cũ (xuôi): đưa tin nhắn cho teacher, tin cả nhãn teacher gán — nhãn sai
thì train sai mà không biết. Cách này (ngược): sinh JSON ground truth TẤT ĐỊNH
trước bằng code thuần, rồi mới nhờ teacher viết tin nhắn tự nhiên chứa đúng
các thông tin đó (reverse_generate.py). Nhãn đúng tuyệt đối theo cấu trúc —
teacher chỉ đóng góp phần ngôn ngữ, thứ duy nhất nó giỏi hơn code.

Mọi tên công ty/người/email đều HƯ CẤU (P2: không đưa dữ liệu khách pilot
lên DeepSeek API). Địa danh/tuyến đường là thông tin công khai.

CHẠY (không cần GPU, không cần mạng):
  python offline_training/make_extraction_seeds.py --n 600 --n-eval 100
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from offline_training.dgen_common import GENERATED_DIR
from src.core.schemas import QuoteExtraction

# ---------------------------------------------------------------------------
# Kho giá trị — địa danh công khai, tên/email hư cấu
# ---------------------------------------------------------------------------

ORIGINS = [
    "Hữu Nghị", "KCN Quế Võ", "KCN Yên Phong", "KCN VSIP Bắc Ninh",
    "KCN Thăng Long", "Nội Bài", "cảng Đình Vũ", "kho Long Biên",
    "Gia Lâm", "Đông Anh", "KCN Tân Trường", "bến xe Nước Ngầm",
]
DESTINATIONS = [
    "Hải Phòng", "Bắc Giang", "Bắc Ninh", "Hà Nội", "Lạng Sơn", "Móng Cái",
    "Thanh Hóa", "Vinh", "Đà Nẵng", "Hạ Long", "Nam Định", "Việt Trì",
]
CARGO_TYPES = [
    "hàng lạnh", "hàng khô", "sắt thép", "vải cuộn", "linh kiện điện tử",
    "nông sản", "hàng dễ vỡ", "gạo đóng bao",
]

# Cụm từ người dùng hay nói -> giá trị chuẩn hoá model phải xuất ra
VEHICLE_PHRASES: dict[str, list[str]] = {
    "1.5T": ["xe 1.5 tấn", "xe 1 tấn rưỡi", "xe tải 1t5", "xe 1.5 tan"],
    "3T": ["xe 3 tấn", "xe ba tấn", "xe 3 tan", "tải 3 tấn"],
    "5T": ["xe 5 tấn", "xe năm tấn", "xe 5 tan", "tải 5 tấn"],
    "dau_keo": ["đầu kéo", "xe container", "cont 40 feet", "xe cont", "công-ten-nơ"],
}

# Tên/email hư cấu — không phải người thật
PERSONAS = [
    ("anh Tuấn", "tuan@minhlongtrans.vn"),
    ("chị Hòa", "hoa.nguyen@vanphatlog.vn"),
    ("anh Đức", "duc@haianexpress.vn"),
    ("chị Mai", "mai.tran@thanhdatvt.vn"),
    ("anh Phong", "phong@songhonglogistics.vn"),
    ("chị Lan", "lan@vietcargo247.vn"),
]

STYLES = [
    "đầy đủ dấu, lịch sự",
    "không dấu hoàn toàn (kiểu gõ nhanh trên điện thoại)",
    "nhắn vội, viết tắt (vd: 'bao gia', 'HP' thay cho Hải Phòng, 't3' thay cho thứ 3)",
    "giọng nói chuyển thành văn bản: câu liền mạch, rất ít dấu câu",
]

# Index khớp date.weekday(): 0 = thứ Hai
VN_WEEKDAY_SHORT = ["thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "thứ 7", "chủ nhật"]

# Cụm mơ hồ: NGƯỜI ĐỌC cũng không quy được ra ngày -> ground truth phải là null.
# Dạy model kỷ luật "mơ hồ thì để null" quan trọng ngang dạy nó đổi ngày đúng.
AMBIGUOUS_DATE_PHRASES = [
    "cuối tuần này", "đầu tháng sau", "trong tuần", "sớm nhất có thể",
    "khi nào tiện xếp xe",
]

# Tổ hợp trường bắt buộc bị thiếu (dạy nhánh hỏi-lại của chat.py)
MISSING_PATTERNS: list[tuple[tuple[str, ...], int]] = [
    ((), 55),
    (("destination",), 12),
    (("vehicle_type",), 12),
    (("origin",), 8),
    (("origin", "vehicle_type"), 7),
    (("destination", "vehicle_type"), 6),
]


# ---------------------------------------------------------------------------
# Sinh cụm ngày + ngày chuẩn tương ứng
# ---------------------------------------------------------------------------

def next_weekday(anchor: date, weekday: int) -> date:
    """Ngày `weekday` (0=thứ Hai) của TUẦN SAU tính từ anchor."""
    return anchor + timedelta(days=(7 - anchor.weekday()) + weekday)


def make_date_phrase(anchor: date, rng: random.Random):
    """Trả (cụm_từ, ngày_chuẩn | None). None = cụm mơ hồ, ground truth null."""
    kind = rng.choices(
        ["mai", "kia", "tuan_sau", "explicit", "ambiguous"],
        weights=[20, 8, 30, 27, 15],
    )[0]
    if kind == "mai":
        return "ngày mai", anchor + timedelta(days=1)
    if kind == "kia":
        return "ngày kia", anchor + timedelta(days=2)
    if kind == "tuan_sau":
        weekday = rng.randrange(7)
        return f"{VN_WEEKDAY_SHORT[weekday]} tuần sau", next_weekday(anchor, weekday)
    if kind == "explicit":
        target = anchor + timedelta(days=rng.randrange(3, 45))
        return f"ngày {target.day}/{target.month}", target
    return rng.choice(AMBIGUOUS_DATE_PHRASES), None


# ---------------------------------------------------------------------------
# Sinh một seed
# ---------------------------------------------------------------------------

# Trường mà câu nối tiếp thường đổi, kèm mẫu câu người Việt hay dùng.
# Đây là thứ dạy model KẾ THỪA ngữ cảnh: "thế xe 3 tấn thì sao?" phải giữ
# nguyên tuyến đường của lượt trước chứ không để null.
FOLLOWUP_CHANGES = {
    "vehicle_type": "đổi sang loại xe khác",
    "destination": "đổi điểm giao hàng",
    "pickup_date": "đổi ngày lấy hàng",
    "cargo_type": "đổi loại hàng",
}


def make_followup_seed(base: dict, index: int, rng: random.Random) -> dict:
    """
    Biến một seed ĐẦY ĐỦ thành cặp 2 lượt.

    Lượt 1 = yêu cầu đầy đủ (đã có trong `base`).
    Lượt 2 = câu ngắn chỉ nêu THỨ THAY ĐỔI; ground truth kế thừa mọi trường
    còn lại từ lượt 1. Không có lịch sử thì bài toán này bất khả — đó chính là
    điều cần dạy.
    """
    gt2 = dict(base["ground_truth"])
    facts2: dict[str, str] = {}

    field = rng.choice([f for f in FOLLOWUP_CHANGES if base["ground_truth"].get(f)]
                       or ["vehicle_type"])

    if field == "vehicle_type":
        canonical = rng.choice([v for v in VEHICLE_PHRASES
                                if v != base["ground_truth"]["vehicle_type"]])
        gt2["vehicle_type"] = canonical
        facts2["vehicle_phrase"] = rng.choice(VEHICLE_PHRASES[canonical])
    elif field == "destination":
        new_dest = rng.choice([d for d in DESTINATIONS
                               if d != base["ground_truth"]["destination"]])
        gt2["destination"] = facts2["destination"] = new_dest
    elif field == "pickup_date":
        anchor = date.fromisoformat(base["today"])
        phrase, resolved = make_date_phrase(anchor, rng)
        while resolved is None:                 # câu nối tiếp cần ngày rõ ràng
            phrase, resolved = make_date_phrase(anchor, rng)
        facts2["date_phrase"] = phrase
        gt2["pickup_date"] = resolved.isoformat()
    else:
        new_cargo = rng.choice([c for c in CARGO_TYPES
                                if c != base["ground_truth"].get("cargo_type")])
        gt2["cargo_type"] = facts2["cargo"] = new_cargo

    QuoteExtraction(**gt2)

    return {
        "_id": f"FU{index:04d}",
        "today": base["today"],
        "style": base["style"],
        "kind": "followup",
        "changed_field": field,
        "change_desc": FOLLOWUP_CHANGES[field],
        # lượt 1
        "facts": base["facts"],
        "must_not_mention": base["must_not_mention"],
        "ground_truth": base["ground_truth"],
        # lượt 2
        "facts2": facts2,
        "ground_truth2": gt2,
    }


def make_seed(index: int, rng: random.Random) -> dict:
    # Ngày "hôm nay" ngẫu nhiên -> model học CÁCH tính từ mốc, không học vẹt mốc
    anchor = date(2026, 1, 1) + timedelta(days=rng.randrange(360))

    patterns = [p for p, _ in MISSING_PATTERNS]
    weights = [w for _, w in MISSING_PATTERNS]
    missing = set(rng.choices(patterns, weights=weights)[0])

    facts: dict[str, str] = {}
    gt: dict[str, str | None] = {k: None for k in QuoteExtraction.model_fields}

    if "origin" not in missing:
        gt["origin"] = facts["origin"] = rng.choice(ORIGINS)
    if "destination" not in missing:
        gt["destination"] = facts["destination"] = rng.choice(DESTINATIONS)
    if "vehicle_type" not in missing:
        canonical = rng.choice(list(VEHICLE_PHRASES))
        gt["vehicle_type"] = canonical
        facts["vehicle_phrase"] = rng.choice(VEHICLE_PHRASES[canonical])

    if rng.random() < 0.55:
        gt["cargo_type"] = facts["cargo"] = rng.choice(CARGO_TYPES)

    if rng.random() < 0.70:
        phrase, resolved = make_date_phrase(anchor, rng)
        facts["date_phrase"] = phrase
        gt["pickup_date"] = resolved.isoformat() if resolved else None

    if rng.random() < 0.35:
        name, email = rng.choice(PERSONAS)
        gt["customer_name"] = facts["customer_name"] = name
        if rng.random() < 0.60:
            gt["customer_email"] = facts["customer_email"] = email

    QuoteExtraction(**gt)  # ground truth phải hợp lệ theo schema runtime (P4)

    return {
        "_id": f"EX{index:04d}",
        "today": anchor.isoformat(),
        "style": rng.choice(STYLES),
        "kind": "single",
        "facts": facts,
        "must_not_mention": sorted(missing),
        "ground_truth": gt,
    }


# Tỷ lệ seed đa lượt. 1/4 đủ dạy kỹ năng kế thừa ngữ cảnh mà không lấn át
# phân phối câu một lượt (vẫn là đa số ca dùng thật).
FOLLOWUP_RATIO = 0.25


def generate(n_train: int, n_eval: int, seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    total = n_train + n_eval
    seeds = [make_seed(i, rng) for i in range(total)]

    # Chỉ seed ĐỦ 3 trường bắt buộc mới làm được lượt nối tiếp — câu "thế xe 3
    # tấn thì sao?" chỉ có nghĩa khi lượt trước đã đủ thông tin.
    complete = [s for s in seeds if not s["must_not_mention"]]
    rng.shuffle(complete)
    for i, base in enumerate(complete[: int(total * FOLLOWUP_RATIO)]):
        seeds[seeds.index(base)] = make_followup_seed(base, i, rng)

    rng.shuffle(seeds)
    return seeds[:n_train], seeds[n_train:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=600, help="số seed train")
    parser.add_argument("--n-eval", type=int, default=100, help="số seed eval (benchmark)")
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()

    train, eval_ = generate(args.n, args.n_eval, args.seed)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in [("seeds_extraction_train.jsonl", train),
                       ("seeds_extraction_eval.jsonl", eval_)]:
        path = GENERATED_DIR / name
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        print(f"✓ {path} — {len(rows)} seed")

    n_missing = sum(1 for s in train + eval_ if s["must_not_mention"])
    n_ambiguous = sum(
        1 for s in train + eval_
        if "date_phrase" in s["facts"] and s["ground_truth"]["pickup_date"] is None
    )
    n_followup = sum(1 for s in train + eval_ if s.get("kind") == "followup")
    print(f"  Thiếu trường bắt buộc : {n_missing} (dạy nhánh hỏi-lại)")
    print(f"  Ngày mơ hồ -> null    : {n_ambiguous} (dạy kỷ luật không đoán)")
    print(f"  Câu nối tiếp 2 lượt   : {n_followup} (dạy kế thừa ngữ cảnh)")
    print("\nBước tiếp: python offline_training/reverse_generate.py")


if __name__ == "__main__":
    main()
