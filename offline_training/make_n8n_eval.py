"""
offline_training/make_n8n_eval.py — sinh bộ eval n8n ĐỦ LỚN để kết luận được.

VẤN ĐỀ CỦA BẢN CŨ
-----------------
`make_n8n_pairs.py` cắt 5 template khỏi 32 template thật để làm eval, còn lại 25
cho train. Cả hai đầu đều quá nhỏ:

* n=5 cho khoảng Wilson ~48%–100%. Model hoàn hảo và model tung đồng xu cho ra
  hai con số không phân biệt được. Cổng chặn trên đó là may rủi đội lốt quyết định.
* Muốn n đủ để chặn (≥20) thì tập train còn 12 mẫu — huấn luyện trên 12 mẫu
  không nói lên điều gì. Không có cách chia nào cứu được 32 template.

VÌ SAO VẪN THOÁT ĐƯỢC
---------------------
Đọc kỹ chỗ chấm điểm trong `benchmark_v3.py`: trường `answer` của mỗi dòng eval
**không bao giờ được dùng**. Điểm số là `validate_workflow(model_output)` — một
bộ kiểm CẤU TRÚC, không so với đáp án mẫu nào cả.

Nghĩa là bộ eval n8n chỉ cần ĐỀ BÀI, không cần lời giải. Và đề bài thì viết mới
được, không phải cắt khỏi tập train. Đó là toàn bộ lối ra.

ĐO ĐƯỢC GÌ, KHÔNG ĐO ĐƯỢC GÌ
----------------------------
Đo được: model có sinh ra JSON workflow **hợp lệ về cấu trúc** không — đúng loại
node, đủ tham số bắt buộc, nối dây không gãy, không bịa node ngoài catalog.

KHÔNG đo được: workflow đó có làm ĐÚNG VIỆC được yêu cầu không. Một workflow hợp
lệ hoàn toàn có thể gửi báo cáo sai người. Muốn đo phần đó phải có đáp án mẫu cho
từng đề — công việc khác hẳn, và tốn hơn nhiều.

Ba mươi tư đề dưới đây viết theo đúng nghiệp vụ khách đang làm: phân phối dầu
nhớt, kho, công nợ, thuế. Đề sát việc thật thì đo được thứ sát việc thật.

CHẠY (không cần API key, không cần GPU)
--------------------------------------
    python -m offline_training.make_n8n_eval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offline_training.dgen_common import GENERATED_DIR

# (mã, mô tả ngắn, các bước)
DE_BAI: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("kho_canh_bao_ton_thap", "cảnh báo hàng sắp hết mỗi 4 tiếng",
     ("Mỗi 4 tiếng", "Lấy hàng tồn thấp", "Có hàng nào dưới ngưỡng?",
      "Dựng nội dung cảnh báo", "Gửi Discord")),
    ("kho_ton_am_hang_ngay", "phát hiện tồn kho âm hằng ngày",
     ("Mỗi ngày 7h", "Truy vấn tồn âm", "Có dòng nào âm?", "Dựng bảng tóm tắt",
      "Gửi Discord cho kế toán")),
    ("kho_hang_chet_hang_thang", "báo hàng không xuất trong 90 ngày",
     ("Mỗi tháng ngày 1", "Lấy hàng chết", "Tính tổng vốn đọng",
      "Dựng báo cáo", "Gửi email chủ doanh nghiệp")),
    ("kho_nhap_kho_ghi_so", "ghi phiếu nhập kho từ webhook",
     ("Nhận phiếu nhập", "Kiểm tra token ANSER", "Hợp lệ?",
      "Ghi vào hệ thống", "Trả 201", "Trả 401")),
    ("kho_dieu_chuyen_hai_kho", "điều chuyển hàng giữa hai kho",
     ("Nhận yêu cầu điều chuyển", "Kiểm tồn kho nguồn", "Đủ hàng?",
      "Ghi xuất kho nguồn", "Ghi nhập kho đích", "Báo kết quả")),
    ("kho_kiem_ke_dinh_ky", "nhắc kiểm kê kho định kỳ",
     ("Mỗi quý", "Lấy danh sách kho", "Dựng danh sách cần kiểm", "Gửi nhắc việc")),
    ("kho_canh_bao_gia_nhap_vot", "cảnh báo giá nhập tăng bất thường",
     ("Mỗi ngày", "Lấy giá nhập mới", "So với giá kỳ trước",
      "Tăng quá 10%?", "Dựng cảnh báo", "Gửi Discord")),
    ("kho_dong_bo_ton_misa", "đồng bộ tồn kho từ file MISA",
     ("Nhận file tồn kho", "Gọi ANSER nạp bảng", "Đọc được sạch?",
      "Ghi kết quả kiểm", "Báo lỗi đọc file")),

    ("no_nhac_cong_no_qua_han", "nhắc khách nợ quá hạn",
     ("Mỗi thứ Hai 8h", "Lấy công nợ quá hạn", "Có khách nào quá hạn?",
      "Dựng tin nhắn từng khách", "Gửi Zalo", "Ghi nhật ký đã nhắc")),
    ("no_bao_cao_tap_trung", "báo cáo tập trung công nợ hằng tuần",
     ("Mỗi tuần", "Lấy số dư từng khách", "Tính tỷ lệ ba khách lớn nhất",
      "Vượt 50%?", "Dựng cảnh báo", "Gửi chủ doanh nghiệp")),
    ("no_so_du_nguoc_dau", "phát hiện công nợ ngược dấu",
     ("Mỗi ngày", "Lấy số dư âm", "Có dòng nào âm?", "Dựng danh sách",
      "Gửi kế toán")),
    ("no_doi_chieu_ncc", "đối chiếu công nợ nhà cung cấp hằng tháng",
     ("Mỗi tháng", "Lấy công nợ phải trả", "Dựng bảng đối chiếu",
      "Gửi email từng nhà cung cấp")),
    ("no_nhac_thanh_toan_sap_den_han", "nhắc hoá đơn sắp đến hạn",
     ("Mỗi ngày 9h", "Lấy hoá đơn đến hạn trong 3 ngày", "Có hoá đơn nào?",
      "Dựng nhắc việc", "Gửi Discord")),
    ("no_ghi_nhan_thanh_toan", "ghi nhận khách thanh toán",
     ("Nhận thông báo chuyển khoản", "Xác thực token", "Khớp khách hàng",
      "Khớp được?", "Ghi giảm công nợ", "Trả 200", "Trả 404")),

    ("thue_soat_co_thue_danh_muc", "soát cờ thuế suất danh mục hàng hoá",
     ("Mỗi tháng", "Lấy danh mục hàng hoá", "Gọi ANSER đối chiếu thuế suất",
      "Có mã sai diện?", "Dựng danh sách cần sửa", "Gửi kế toán")),
    ("thue_nhac_ky_khai_thue", "nhắc hạn nộp tờ khai thuế",
     ("Mỗi tháng ngày 15", "Dựng nội dung nhắc", "Gửi Discord")),
    ("thue_kiem_mst_khach_moi", "kiểm mã số thuế khách hàng mới",
     ("Nhận khách hàng mới", "Gọi ANSER kiểm mã số thuế", "Hợp lệ?",
      "Ghi vào danh mục", "Trả lỗi mã số thuế")),
    ("thue_bao_cao_gtgt_thang", "tổng hợp thuế GTGT đầu ra theo tháng",
     ("Mỗi tháng", "Lấy hoá đơn bán ra", "Tổng hợp theo thuế suất",
      "Dựng báo cáo", "Gửi email kế toán")),

    ("bc_lai_lo_hang_ngay", "báo cáo lãi lỗ cuối ngày",
     ("Mỗi ngày 20h", "Lấy dòng bán và chi phí", "Gọi ANSER dựng báo cáo",
      "Dựng nội dung", "Gửi Discord")),
    ("bc_top_mat_hang_tuan", "xếp hạng mặt hàng theo lãi hằng tuần",
     ("Mỗi tuần", "Lấy doanh thu theo mã hàng", "Xếp hạng theo lãi gộp",
      "Dựng bảng", "Gửi chủ doanh nghiệp")),
    ("bc_so_sanh_ky_truoc", "so doanh thu tháng này với tháng trước",
     ("Mỗi tháng", "Lấy doanh thu hai kỳ", "Tính chênh lệch",
      "Giảm quá 15%?", "Dựng cảnh báo", "Gửi chủ doanh nghiệp")),
    ("bc_dong_tien_tuan", "báo cáo dòng tiền hằng tuần",
     ("Mỗi tuần", "Lấy phải thu phải trả tồn kho", "Tính vốn lưu động kẹt",
      "Dựng báo cáo", "Gửi email")),
    ("bc_xuat_excel_gui_email", "xuất báo cáo Excel gửi email hằng tháng",
     ("Mỗi tháng", "Lấy số liệu kỳ", "Dựng file", "Gửi email kèm tệp")),

    ("hd_ocr_hoa_don_nha_xe", "đọc hoá đơn nhà xe từ ảnh",
     ("Nhận ảnh hoá đơn", "Gọi ANSER đọc hoá đơn", "Số học khớp?",
      "Ghi vào sổ", "Đưa vào hàng chờ duyệt tay")),
    ("hd_kiem_tong_hoa_don", "kiểm tổng tiền hoá đơn trước khi ghi sổ",
     ("Nhận hoá đơn", "Gọi ANSER tính lại tổng", "Lệch quá dung sai?",
      "Ghi sổ", "Báo lệch cho kế toán")),
    ("hd_luu_tru_hoa_don", "lưu trữ hoá đơn theo tháng",
     ("Mỗi ngày", "Lấy hoá đơn mới", "Ghi vào Google Sheets", "Báo số lượng đã lưu")),

    ("gia_dong_bo_gia_dau", "cào giá dầu và cập nhật bảng giá",
     ("Mỗi ngày 6h", "Gọi trang giá", "Tách giá từ HTML", "Giá đổi quá 3%?",
      "Ghi bảng giá mới", "Báo Discord")),
    ("gia_canh_bao_bien_mong", "cảnh báo mặt hàng biên lợi nhuận mỏng",
     ("Mỗi tuần", "Lấy giá vốn và giá bán", "Tính biên từng mã",
      "Biên dưới ngưỡng?", "Dựng danh sách", "Gửi chủ doanh nghiệp")),
    ("gia_cap_nhat_bang_gia_khach", "cập nhật bảng giá cho nhóm khách",
     ("Nhận yêu cầu đổi giá", "Xác thực quyền", "Được phép?",
      "Ghi bảng giá", "Thông báo đã đổi", "Trả 403")),

    ("kh_chao_khach_moi", "gửi lời chào khách hàng mới",
     ("Nhận khách hàng mới", "Dựng nội dung chào", "Gửi Zalo",
      "Ghi nhật ký đã gửi")),
    ("kh_khach_lau_khong_mua", "phát hiện khách lâu không mua hàng",
     ("Mỗi tháng", "Lấy lần mua gần nhất từng khách", "Quá 90 ngày?",
      "Dựng danh sách", "Gửi bộ phận bán hàng")),
    ("kh_sinh_nhat_khach", "chúc mừng sinh nhật khách hàng",
     ("Mỗi ngày 8h", "Lấy khách sinh nhật hôm nay", "Có ai không?",
      "Dựng lời chúc", "Gửi Zalo")),

    ("ht_sao_luu_du_lieu", "sao lưu dữ liệu hằng đêm",
     ("Mỗi ngày 2h", "Gọi API sao lưu", "Thành công?", "Ghi nhật ký",
      "Báo lỗi Discord")),
    ("ht_kiem_suc_khoe_he_thong", "kiểm tra sức khoẻ hệ thống mỗi giờ",
     ("Mỗi giờ", "Gọi /health của Brain", "Có lỗi?", "Gửi cảnh báo Discord")),
)


def dung_dong(ma: str, mo_ta: str, buoc: tuple[str, ...]) -> dict:
    return {
        "_id": f"n8n_eval_{ma}",
        "task": (f'Dựng workflow n8n "{ma}" ({mo_ta}) gồm các bước: '
                 + ", ".join(buoc) + "."),
        "plan": "[PLAN]\n" + "\n".join(f"{i}. {b}" for i, b in enumerate(buoc, 1)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sinh bộ eval n8n (không cần API key)")
    p.add_argument("--ra", default=str(GENERATED_DIR / "eval_n8n.jsonl"))
    a = p.parse_args(argv)

    ma_trung = [m for m, _, _ in DE_BAI if [x for x, _, _ in DE_BAI].count(m) > 1]
    if ma_trung:
        print(f"Mã đề trùng: {sorted(set(ma_trung))}")
        return 1

    ra = Path(a.ra)
    ra.parent.mkdir(parents=True, exist_ok=True)
    with open(ra, "w", encoding="utf-8") as f:
        for ma, mo_ta, buoc in DE_BAI:
            f.write(json.dumps(dung_dong(ma, mo_ta, buoc), ensure_ascii=False) + "\n")

    print(f"✓ {ra} — {len(DE_BAI)} đề")
    print(f"  n={len(DE_BAI)} đủ để làm cổng chặn (ngưỡng tối thiểu 20).")
    print("  Lưu ý: bộ này đo CẤU TRÚC workflow hợp lệ, KHÔNG đo workflow có làm")
    print("  đúng việc được yêu cầu hay không.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
