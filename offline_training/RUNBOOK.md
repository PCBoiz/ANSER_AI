# RUNBOOK — chạy fine-tune v3 trên Colab

Tài liệu tra cứu đi kèm [`ANSER_train_v3_colab.ipynb`](ANSER_train_v3_colab.ipynb).
Notebook để **chạy**; file này để **tra khi có sự cố** và để **đọc kết quả**.

---

## 0. Trước khi mở Colab

| Việc | Ai làm | Ghi chú |
|---|---|---|
| Thêm `DEEPSEEK_API_KEY` vào Colab Secrets | Bạn | 🔑 bên trái Colab → *Add new secret* → bật *Notebook access*. **Không dán vào notebook** (R2b) |
| Dọn Drive còn ≥ 8GB trống | Bạn | Cell 1.4 in dung lượng từng thư mục; xoá được: `_backups` (234MB), `anser-qwen-lora`, `anser-qwen-distill-awq` (model **v1**) |
| Chọn runtime **L4 GPU** | Bạn | *Runtime → Change runtime type* |

Không cần token GitHub: notebook lấy mã **thẳng từ Drive**.

### Sơ đồ thư mục trên Drive

```
MyDrive/
├─ ANSER_AI_Logistics/          ← thư mục bạn đã đẩy lên
│  ├─ AI_ANSER/                 ← mã nguồn (notebook đọc từ đây)
│  ├─ generated/                ← dữ liệu sinh (notebook TỰ TẠO, giữ qua các phiên)
│  ├─ anser-v3-lora/            ← LoRA sau khi train
│  ├─ anser-v3-awq/             ← model cuối, trỏ TEXT_MODEL_ID vào đây
│  └─ *_report.txt              ← báo cáo benchmark
└─ ANSER_data/                  ← có sẵn từ trước (model v1/v2)
```

**Mã nguồn được chép sang `/content` để chạy**, không chạy thẳng trên Drive:
Drive gắn qua FUSE, mỗi thao tác file mất hàng chục ms — import vài trăm file và
ghi checkpoint sẽ chậm tới mức không dùng được. Mọi thứ **cần giữ** (dữ liệu
sinh, model, báo cáo) vẫn ghi thẳng ra Drive.

**Sửa mã nguồn thì làm ở máy bạn rồi đẩy lại lên Drive**, chạy lại cell 1.2 là
bản mới được chép sang. Sửa trực tiếp trong `/content` sẽ mất khi hết phiên.

Chi phí: DeepSeek **< 1 USD** cho toàn bộ bước sinh dữ liệu. Colab Pro tính theo
giờ GPU — cả quy trình khoảng **3–4 giờ**.

---

## 1. Thứ tự chạy

```
Giai đoạn 1  cài đặt → sinh dữ liệu → preflight        (~25 phút)
Giai đoạn 2  train → gộp LoRA → lượng tử hoá AWQ       (~2-3 giờ)
             ⚠ RESTART RUNTIME
Giai đoạn 3  benchmark baseline + benchmark model mới  (~40 phút)
```

**Không bỏ qua preflight.** Nó bắt các lỗi mà nếu để lọt sẽ chỉ lộ ra sau 2 giờ
train: thiếu file, nhãn sai schema, prompt trong data lệch runtime, hết chỗ Drive.

Mọi bước sinh dữ liệu đều **resume**: đứt mạng giữa chừng thì chạy lại đúng cell
đó, nó bỏ qua phần đã xong.

---

## 2. Đọc kết quả benchmark

Đọc theo đúng thứ tự này — trên xuống dưới là từ quan trọng nhất:

### 2.1 `sẵn sàng báo giá` (ready_rate)

Tỷ lệ tin nhắn khách gửi mà model trích xuất đủ **3 trường bắt buộc**
(điểm lấy, điểm giao, loại xe) → ra được báo giá **không cần hỏi lại**.

Đây là chỉ số sát nghiệp vụ nhất: chủ DN đang lái xe, mỗi lần phải hỏi lại là
một lần quy trình đứt.

### 2.2 `câu nối tiếp` vs `câu một lượt`

Nếu câu nối tiếp thấp hơn hẳn → **hội thoại nhiều lượt chưa dùng được**, dù
điểm chung có đẹp. "Thế xe 3 tấn thì sao?" sẽ hỏi lại tuyến đường — đúng thứ
làm khách khó chịu nhất.

### 2.3 `false_fill` — lỗi nguy hiểm nhất

Model **đoán bừa** một trường mà tin nhắn không hề nêu. Tệ hơn `miss` (bỏ sót)
nhiều lần:

- `miss` → hệ thống hỏi lại → phiền nhưng **an toàn**
- `false_fill` → hệ thống tạo báo giá **sai tuyến trong im lặng** → gửi khách sai giá

Chỉ số này cao thì **không được đưa vào chạy thật**, kể cả khi ready_rate đẹp.

### 2.4 `n8n hợp lệ`

Dưới 90% thì nhánh "khách tự tạo quy trình" chưa giao được.

### 2.5 So với baseline

Luôn đọc kèm baseline. Ví dụ:

| Trường hợp | Ý nghĩa |
|---|---|
| baseline 45% → tuned 88% | Fine-tune có tác dụng rõ. Dùng model mới |
| baseline 84% → tuned 88% | Cải thiện nhỏ. Cân nhắc dùng thẳng model gốc, dành tiền cho hạ tầng — guided decoding đã gánh phần lớn |
| baseline 84% → tuned 71% | **Overfit hoặc data hỏng.** Xem mục 4 |

---

## 3. Bảng sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `CUDA out of memory` khi train | seq 8192 + mẫu dài | Đặt `MAX_SEQ_LEN=4096` rồi chạy lại cell 2.1. Preflight có cảnh báo trước nếu nhiều mẫu vượt ngân sách |
| `pip install autoawq` xung đột version | autoawq đòi `transformers` khác bản train | *Runtime → Restart*, chạy lại cell 1.2, rồi chạy thẳng cell 2.4 (không cài lại thư viện train) |
| autoawq không hỗ trợ kiến trúc Qwen3 | Bản autoawq cũ | Dùng `llm-compressor` (định dạng compressed-tensors). Khi đó **bỏ** `quantization="awq"` trong `config.py` để vLLM tự nhận |
| `Thiếu train_v3.jsonl` | Chưa chạy cell 1.6e | Chạy `build_dataset_v3.py` |
| Preflight báo `Chỉ N mẫu train` với N nhỏ | Chưa chạy 1.6b/1.6c (thiếu API key) | Kiểm tra cell 1.5 in ra `✓ Đã nạp DEEPSEEK_API_KEY` |
| Preflight báo `Catalog node ĐÃ ĐỔI` | `N8N_TEMPLATES_DIR` khác lúc dựng dataset | Chạy lại `build_dataset_v3.py`. **Không bỏ qua**: `CODER_SYSTEM` dựng từ catalog, lệch là model học prompt không tồn tại lúc serve |
| Preflight báo có secret | Dữ liệu nguồn dính credential | **Dừng.** Không train, không đẩy lên Drive. Gỡ secret khỏi nguồn rồi dựng lại |
| Mất phiên Colab giữa chừng | Colab ngắt do idle | Dữ liệu sinh nằm trên Drive nên **không mất tiền API**. LoRA đã sao lưu ở cell 2.2 → chạy lại từ 2.3. Nếu mất trước 2.2 thì phải train lại |
| Benchmark thoát mã 1 | Dưới ngưỡng | Xem mục 4 |
| `Không tìm thấy repo trong Drive` | Thư mục đẩy lên thiếu `offline_training/` hoặc `src/` | Kiểm tra trên Drive có đủ hai thư mục đó không. Cell tự quét theo file mốc nên đổi tên thư mục vẫn chạy |
| Sửa code mà Colab vẫn chạy bản cũ | Đang chạy bản chép ở `/content` | Đẩy bản mới lên Drive → chạy lại cell 1.2 |

---

## 4. Điểm dưới ngưỡng — chỉnh gì

| Chỉ số kém | Chỉnh |
|---|---|
| `false_fill` cao | Tăng tỷ lệ seed thiếu trường: sửa `MISSING_PATTERNS` trong [`make_extraction_seeds.py`](make_extraction_seeds.py), sinh lại dữ liệu |
| Câu nối tiếp kém | Tăng `FOLLOWUP_RATIO` (mặc định 0.25) trong cùng file |
| `pickup_date` sai nhiều | Kiểm tra tỷ lệ cụm ngày mơ hồ; `AMBIGUOUS_DATE_PHRASES` nên chiếm ~15% |
| n8n hợp lệ thấp | Đối chiếu vân tay catalog (preflight mục 3). Nếu khớp mà vẫn thấp: tăng số mẫu n8n bằng cách nới `MAX_NODES` trong [`make_n8n_pairs.py`](make_n8n_pairs.py) |
| Narration bịa số | Chốt chặn đã lọc lúc sinh data; điểm thấp ở benchmark nghĩa là model **học được thói quen bịa từ nguồn khác** — giảm tỷ lệ `v2_report` (`V2_MAX_SHARE`) |
| Mọi chỉ số kém hơn baseline | Overfit: `EPOCHS=1` hoặc `LORA_R=16` |

---

## 5. Sau khi xong

```bash
# Trên máy chạy Brain (KHÔNG phải Colab — xem ARCHITECTURE §4.4)
export TEXT_MODEL_ID=/đường/dẫn/anser-v3-awq
```

`config.py` đọc biến này; `vllm_config` đã đặt sẵn `quantization="awq"`.

**Colab tuyệt đối không phục vụ traffic thật** — điều khoản Colab cấm dùng làm
web service. Colab chỉ để train / quantize / đo.

### Giữ lại để so sánh lần sau

Cell 3.4 sao lưu `baseline_report.txt` và `tuned_report.txt` lên Drive. Lần
train sau, so với hai file này để biết thay đổi có thật sự cải thiện không —
đây chính là điều mà bug #6 (`ai_metrics_log`) sinh ra để giải quyết.
