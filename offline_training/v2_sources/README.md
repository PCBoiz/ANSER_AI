# v2_sources — 5 file nguồn tập train v2 khôi phục từ Drive

Copy 5 file sau từ Google Drive/Colab cũ vào đúng thư mục này
(quyết định 27/07/2026 — đóng bug #4 ARCHITECTURE §11: "không tái tạo được
tập train"):

- `train_retail_base.jsonl`
- `module_a_clean.jsonl`
- `module_b.jsonl`
- `module_c.jsonl`
- `module_d.jsonl`

Sau khi copy: chạy `python offline_training/build_dataset_v3.py` — script sẽ
convert (bỏ `<think>`, đổi system prompt về chuẩn runtime, loại Make.com/SQL
cũ, validate lại workflow) và **quét secret**; build pass thì mới commit 5
file này vào repo.
