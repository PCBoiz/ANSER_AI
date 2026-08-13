# Phiên đo model trên Colab — runbook

**Mục tiêu:** có con số để trả lời một câu duy nhất — *bản fine-tune có hơn model
gốc không, và hơn đủ để đáng dùng không?*

Cổng này chưa từng được đưa ra. Không có `baseline.json` hay `tuned.json` nào
trong repo, và tám commit gần đây toàn là **sửa** công cụ đo chứ chưa lần nào
**dùng** nó.

> **Đừng thuê GPU trước khi có kết quả phiên này.** Trả tiền hằng tháng cho một
> lớp chưa đo bao giờ là cách nhanh nhất để tốn tiền vào thứ có thể không cần.

---

## Cần chuẩn bị

| Thứ | Ghi chú |
|---|---|
| Colab có **GPU L4** (hoặc A100) | T4 16GB không đủ cho Qwen3-8B AWQ |
| **`DEEPSEEK_API_KEY`** trong Colab Secrets | tên khoá đúng là `DEEPSEEK_API_KEY` |
| Drive đã có `ANSER_AI_Logistics/anser-v3-awq` | đã xác nhận là có |
| ~2 giờ | không phải train lại, chỉ sinh dữ liệu + đo |

Khoá API **không đi qua chat và không nằm trên máy làm việc** — dán thẳng vào
Colab Secrets, ô 10 tự đọc ra.

---

## Chạy ô nào

### Giai đoạn 1 — chuẩn bị và sinh dữ liệu (~35 phút)

| Ô | Việc | Ghi chú |
|---|---|---|
| 2 | kiểm GPU | thấy `L4` hoặc `A100` mới đi tiếp |
| 4 | gắn Drive + kéo mã nguồn | |
| 6 | cài thư viện | lâu nhất trong nhóm này |
| 8 | kiểm dung lượng Drive | |
| 10 | đọc khoá API | in ra `✓` là được |
| 12–18 | **sinh dữ liệu** | ô 13, 14, 15 gọi DeepSeek — tốn tiền |
| 20 | **preflight** | đọc kỹ, xem mục dưới |

### ⛔ Dừng ở ô 20 và đọc

Preflight in ra danh sách cảnh báo. Ba dòng cần thấy:

```
✓  train_v3.jsonl: <NGHÌN>+ mẫu        <- KHÔNG còn là 50
✓  eval_extraction.jsonl: ~100 ca
✓  eval_n8n.jsonl: 34 ca benchmark
```

Nếu `train_v3.jsonl` vẫn 50 mẫu thì **các ô sinh dữ liệu đã im lặng thất bại** —
gần như chắc chắn là khoá API. Chạy tiếp là đo trên hư không.

### Bỏ qua Giai đoạn 2 (ô 21–29)

Đó là train + gộp + lượng tử hoá. **Không chạy** — model AWQ đã có trên Drive.

### ⚠️ Restart runtime (ô 30)

Bắt buộc. vLLM không dùng chung tiến trình với thư viện train được.

### Giai đoạn 3 — đo (~50 phút)

| Ô | Việc | Thời gian |
|---|---|---|
| 32 | nạp lại đường dẫn sau restart | |
| 34 | **kiểm model AWQ đọc được** | 2 phút — đừng bỏ, nó chặn trước khi đốt 40 phút |
| 36 | **đo model GỐC** (baseline) | ~20 phút |
| 38 | **đo bản fine-tune** | ~20 phút |
| 40 | **so hai bản THEO CẶP** | 1 phút |

---

## Đọc kết quả — bốn cái bẫy

### 1. "✅ Qua mọi ngưỡng" có thể là câu nói suông

Benchmark giờ in **trước** kết luận hai mục:

```
⚠ KHÔNG ĐO ĐƯỢC (thiếu dữ liệu, không phải model đạt):
   narration — thiếu eval_narration.jsonl
⚠ ĐO ĐƯỢC NHƯNG KHÔNG KẾT LUẬN ĐƯỢC (mẫu quá ít, không dùng làm cổng):
   ...
```

Có bất kỳ dòng nào trong hai mục đó thì dòng cuối đổi thành *"Qua mọi ngưỡng ĐO
ĐƯỢC"*. Một phiên bỏ qua ba trên bốn nhánh rồi in "qua mọi ngưỡng" là câu đúng
chữ mà sai hoàn toàn về nghĩa — và đó chính là câu người ta chụp màn hình gửi đi.

### 2. So hai con số trung bình là cách bỏ sót vùng thoái lui

Ô 40 so **theo cặp**, trên cùng bộ câu hỏi. Nó trả lời được câu mà hai con số
trung bình giấu kín: **bản mới làm hỏng câu nào mà bản gốc vốn trả lời đúng?**

`70% → 70%` hoàn toàn có thể là "hỏng 3, sửa 3" — ba tình huống khách từng dùng
được, nay không.

### 3. Khoảng tin cậy, không phải con số trần

`84.8%` trên n=27 có khoảng rộng khoảng 27 điểm. Hai lần chạy lệch nhau 5 điểm
gần như chắc chắn là nhiễu lấy mẫu chứ không phải model đổi.

Nhánh nào `n < 20` sẽ **không** được dùng làm cổng chặn, và nói rõ lý do.

### 4. `p-value` mới là thứ quyết định

Ô 40 in phép thử McNemar. Ví dụ có thật khi chạy thử: `55.6% → 74.1%` trông như
một thắng lợi rõ ràng, nhưng `p = 0.2266` và **3 ca bị làm hỏng**. Không phân
biệt được với tung đồng xu.

---

## Quyết định sau phiên đo

| Kết quả | Làm gì |
|---|---|
| Bản tinh chỉnh hơn rõ, `p < 0.05`, không ca nào bị hỏng | Dùng bản tinh chỉnh. Tính tiếp chuyện thuê GPU |
| Hơn nhưng `p` lớn, hoặc có ca bị hỏng | **Dùng model gốc.** Xem danh sách ca hỏng để biết dữ liệu train thiếu gì |
| Ngang nhau | **Dùng model gốc** — đỡ một bước trong quy trình, đỡ một chỗ hỏng |
| Kém hơn | Dùng model gốc. Đọc ca hỏng trước khi train lại |

**Ba trong bốn nhánh dẫn tới "dùng model gốc", và đó là kết quả tốt** — nó tiết
kiệm một vòng train, một chỗ có thể hỏng, và tiền GPU. Phiên đo này đáng giá kể
cả khi kết luận là "không cần fine-tune"; thứ không đáng là **không đo mà vẫn
dùng**.

---

## Gửi lại gì sau khi chạy

Ba file, nằm ở `/content/drive/MyDrive/ANSER_AI_Logistics/`:

* `baseline_report.txt`
* `tuned_report.txt`
* `baseline.json` + `tuned.json` — kết quả **từng câu**, để so lại sau này

Kèm ảnh chụp phần in của ô 40.

---

## Bộ eval n8n đã đổi (13/08/2026)

Bản cũ cắt 5 trên 32 template thật làm benchmark. `n=5` cho khoảng Wilson khoảng
**48%–100%** — model hoàn hảo và model đoán bừa cho ra hai con số không phân biệt
được. Mà muốn `n ≥ 20` thì tập train còn 12 mẫu. Không có cách chia nào cứu được
32 template.

Lối ra nằm ở chỗ chấm điểm: nó chạy `validate_workflow()` trên đầu ra chứ **không
so với đáp án mẫu**. Nên bộ eval chỉ cần **đề bài**, và đề bài thì viết mới được.

`make_n8n_eval.py` sinh **34 đề** theo đúng nghiệp vụ khách đang làm — kho, công
nợ, thuế, báo cáo, giá. Không cần API key. Kết quả: train **25 → 30**, eval
**5 → 34**.

> Bộ này đo **cấu trúc workflow hợp lệ**, KHÔNG đo workflow có làm đúng việc được
> yêu cầu hay không. Muốn đo phần đó phải có đáp án mẫu cho từng đề.
