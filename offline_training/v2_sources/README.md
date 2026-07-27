# v2_sources — tập train v2 khôi phục từ Drive (27/07/2026)

Khôi phục từ `ANSER_data` trên Google Drive — **đóng bug #4** ARCHITECTURE §11.5
("không tái tạo được tập train ⇒ single point of failure"). Đã qua
`build_dataset_v3.py` (quét secret sạch) trước khi commit.

| File | Dòng | Nội dung | Số phận trong v3 |
|---|---|---|---|
| `train_final.jsonl` | 487 | Tư vấn bán lẻ distill R1 (`<think>` + văn dài) | 79 → nhánh chat ngắn, **403 → nhánh REPORT** (văn dài) |
| `module_c.jsonl` | 190 | Workflow n8n dạng **export gốc** `{name, nodes, connections}` | **130 giữ** (bọc lại thành envelope `create_workflow`, node `code`→`noOp`) |
| `module_b.jsonl` | 250 | Text-to-SQL `{"action":"query_db","sql":...}` | 0 — hợp đồng `query_db` không còn trong runtime |
| `distillation_v2_test.jsonl` | 20 | Mẫu thử distill vòng 2 | 2 giữ |

Tên gọi trong `merge_all.py` cũ (`train_retail_base`, `module_a_clean`,
`module_d`) **không tồn tại trên Drive** — bản backup thật chỉ có 4 file trên,
`train_final.jsonl` chính là kết quả đã merge của các module đó.

Thư mục cũng có sẵn (không copy vào đây): 3 model đã train
(`anser-retail-v2-lora` 323MB, `anser-retail-v2-awq` 1.1GB, `anser-qwen-lora`
646MB) — dùng để so sánh với v3 nếu cần, nhưng weights không vào git.
