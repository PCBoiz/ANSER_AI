# offline_training — pipeline fine-tune v3 (Qwen3-8B, logistics-first)

Viết lại 27/07/2026 theo 3 quyết định của chủ dự án:
**(1)** model gốc = `Qwen/Qwen3-8B` (ARCHITECTURE §5), **(2)** dữ liệu v2 cũ
khôi phục từ Drive vào [`v2_sources/`](v2_sources/), **(3)** dataset v3
**không có `<think>`** — các nhánh JSON chạy guided_json không cho phép think,
còn Qwen3 đã có thinking mode gốc bật/tắt được từng request.

Guided decoding đã gánh phần **cú pháp** (JSON sai schema là bất khả thi),
nên fine-tune v3 chỉ dạy **ngữ nghĩa**: "xe năm tấn"→`"5T"`, đổi "thứ 3 tuần
sau" ra ngày đúng, kỷ luật *thiếu-thì-null*, chọn node n8n hợp lý, và văn
phong diễn giải số liệu do engine tính (P1 — model không bao giờ tự tính).

## Trình tự chạy

| # | Script | Cần gì | Ra gì |
|---|---|---|---|
| 0 | *(tay)* copy 5 file v2 từ Drive vào `v2_sources/` | Drive | `train_retail_base`, `module_a_clean`, `module_b`, `module_c`, `module_d` |
| 1 | `make_extraction_seeds.py` | — | ground truth trích xuất (tất định, nhãn đúng tuyệt đối) |
| 2 | `reverse_generate.py` | `DEEPSEEK_API_KEY` | teacher viết tin nhắn cho ground truth có sẵn + verify tất định |
| 3 | `make_narration_pairs.py` | `DEEPSEEK_API_KEY` | data diễn giải — **số từ `compute_quote`/`select_carrier` thật**, teacher chỉ viết lời, chốt chặn "không bịa số" |
| 4 | `make_n8n_pairs.py` | — | cặp yêu cầu→workflow từ 32 template Body + 4 logistics, lọc qua `validate_workflow()` |
| 5 | `build_dataset_v3.py` | — | `generated/train_v3.jsonl` + `eval_v3.jsonl` (gộp, lọc Make.com/think/secret, downsample v2) |
| 6 | `train_v3.py` | Colab GPU | LoRA r=32 trên Qwen3-8B — loss chỉ trên phần trả lời, eval theo epoch |
| 7 | `merge_and_quantize.py` | Colab GPU | gộp LoRA → AWQ 4-bit (calibration in-domain) → thư mục cho `TEXT_MODEL_ID` |
| 8 | `benchmark_v3.py` | Colab GPU + vllm | cổng chặn: extraction / n8n valid rate / không-bịa-số |

**Đo baseline trước khi tốn tiền API** (bước 1→4 không cần key, bước 8 chạy
được với model gốc): `python offline_training/benchmark_v3.py --model
Qwen/Qwen3-8B --no-gate`. Con số baseline quyết định fine-tune cần cứu bao
nhiêu điểm — và là mốc so sánh sau khi train.

Chi phí DeepSeek ước tính cho bước 2+3 (~800 call `deepseek-chat`, ~200
token/call): **dưới 1 USD**. Distill R1 đắt hơn chỉ dùng lại nếu cần thêm
data tư vấn — data tư vấn hiện lấy từ v2 convert lại.

## Quy tắc dữ liệu (bắt buộc)

- **P2**: seed gửi DeepSeek chỉ chứa dữ liệu **hư cấu hoặc công khai** (địa
  danh, tuyến đường). Tên nhà xe thật, bảng giá thật, biên thật của khách
  pilot **không bao giờ** được đưa vào seed/prompt gửi ra ngoài.
- **R2b**: `DEEPSEEK_API_KEY` chỉ nằm trong env / Colab Secrets.
  `build_dataset_v3.py` quét secret toàn bộ input — dính là dừng, không ghi file.
  5 file `v2_sources/` phải build pass (tức đã qua quét) **trước khi commit**.
- **P4**: system prompt / user format trong data lấy từ `src.core.prompts`
  và `workflow_schema` — không chép tay. Sửa prompt runtime = sinh lại dataset.
- **P1**: mọi con số trong data diễn giải phải truy ngược được về output engine
  (`narration_numbers_ok` chặn tự động).

## Ghi chú Colab

- `train_v3.py` tự nhận bf16 (L4/A100) hay fp16 (T4). Ghim version bằng
  `requirements_training.txt` — **đừng** cài bản mới nhất.
- `autoawq` cài riêng ở bước quantize (restart runtime nếu xung đột). Nếu
  autoawq không còn hỗ trợ kiến trúc mới, đường thay thế là `llm-compressor`
  (định dạng compressed-tensors — khi đó bỏ `quantization="awq"` trong
  `config.py` để vLLM tự nhận).
- Colab **chỉ** dùng cho train/quantize/benchmark — không phục vụ traffic
  thật (ARCHITECTURE §4.4).

## File cũ (giữ để tham khảo, KHÔNG chạy lại)

`training.py`, `day1_test_batch.py`, `day2_full_batch.py`, `merge_all.py`,
`train_v2.py`, `benchmark_integration.py` — pipeline v2 (Qwen2.5-7B, ép
`<think>`, loss trên cả prompt, đo hợp đồng JSON đã bỏ). Lý do thay thế ghi
trong docstring của `train_v3.py` và ARCHITECTURE §5.3. `seed_prompts.jsonl`
(400 seed retail) vẫn là input hợp lệ nếu cần distill thêm data tư vấn.
`legal_miner.py` (scrape pháp lý cho RAG) và `vlm_invoice_prompt.py` vẫn dùng.
