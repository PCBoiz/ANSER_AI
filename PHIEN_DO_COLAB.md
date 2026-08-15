# Phiên đo model trên Colab — runbook

**Mục tiêu:** có con số để trả lời một câu duy nhất — *bản fine-tune có hơn model
gốc không, và hơn đủ để đáng dùng không?*

> **Đừng thuê GPU trước khi có kết quả phiên này.** Trả tiền hằng tháng cho một
> lớp chưa đo bao giờ là cách nhanh nhất để tốn tiền vào thứ có thể không cần.

---

## Phiên 15/08/2026 đã chạy. Đây là phiên ĐO LẠI.

Lần chạy đầu tiên cho ra bốn file (`baseline.json`, `tuned.json`, hai
`*_report.txt`) và **ba lỗi nằm trong chính bộ đo và mã production**, không phải
trong model. Đã sửa xong; phiên này chạy lại để có con số dùng được.

### Đã tìm ra gì

| Lỗi | Ở đâu | Hậu quả lên số đo |
|---|---|---|
| `arguments_schema()` không đóng object | **production**, `agentic.py` | model vẫn viết được `sales` dù đã bị bỏ → 7/19 đầu ra agentic không đọc được thành JSON |
| trần token production **chặt hơn** benchmark | `agentic.py` 700, `manager.py` 1200, `coder.py` 1600 | tỷ lệ cắt cụt đo được **đẹp hơn** thứ khách nhận |
| `ket_qua_chay["n8n"] = result` gán biến còn sót | `benchmark_v3.py` | mục "n8n" trong JSON là **bản sao y của extraction** — cả nhánh mất dữ liệu so cặp |

Lỗi thứ nhất là nặng nhất vì nó **không phải chuyện đo**: `arguments_schema` chỉ
lọc `properties` mà không đặt `additionalProperties: False`, trong khi JSON
Schema mặc định *cho phép* trường lạ. Lớp phòng thủ mà docstring của nó mô tả
chưa từng tồn tại — ở benchmark lẫn ở máy khách. Bằng chứng là đầu ra thật:

```
{"tool": "report", "arguments": {"granularity": "half_year",
 "sales": [{"date": "2025-04-15", "revenue": 45000000, ...}],
 "margin": 10, "margin": 15, "margin": 20, "m
```

`sales` nằm đó dù đã bị bỏ, `margin` lặp ba lần — khoá trùng chỉ lọt được khi
object không bị đóng.

### Đã sửa gì

* `arguments_schema()` đóng tầng ngoài (`$defs` để mở — đó là dữ liệu khách khai thật)
* Trần token production nâng lên **1024 / 2048 / 2048**, và benchmark **import
  thẳng hằng số của production** thay vì viết số riêng — hai bên không lệch được nữa
* `max_model_len` 4096 → `TEXT_MAX_MODEL_LEN` (mặc định 8192): 2048 token đầu ra
  trên cửa sổ 4096 thì phần đầu vào bị cắt **im lặng**
* Nhánh n8n tách thành `score_n8n()` trả `per_row`/`row_ids` như mọi nhánh khác
* `kiem_ket_qua()` chặn trước lúc ghi JSON: hai nhánh không được trùng danh sách mã câu

881 test xanh trên máy.

### Kết quả lần đầu, để đối chiếu

| Nhánh | Gốc | Tinh chỉnh | p |
|---|---|---|---|
| extraction | 0,0% | **65,3%** | ~0 |
| narration | 88,9% | 55,6% | 0,0117 |
| agentic | 52,6% | 15,8% | 0,0391 |
| n8n | 58,8% | 64,7% | *(không so được)* |

Con số cần nhìn lại sau khi sửa là **agentic** — phần lớn thất bại của nó đến từ
lỗi lược đồ. narration thì đừng kỳ vọng đổi nhiều: trần 2048 đã là trần cũ của
benchmark, tám câu cắt cụt là model viết dài thật.

---

## Cần chuẩn bị

| Thứ | Ghi chú |
|---|---|
| Colab có **GPU L4** (hoặc A100) | T4 16GB không đủ cho Qwen3-8B AWQ |
| Drive đã có `ANSER_AI_Logistics/anser-v3-awq` | đã xác nhận là có |
| Drive đã có `ANSER_AI_Logistics/generated` | dữ liệu phiên 15/08 — **đo lại thì dùng lại, không sinh mới** |
| **`DEEPSEEK_API_KEY`** trong Colab Secrets | chỉ cần khi sinh dữ liệu mới. Tên khoá đúng là `DEEPSEEK_API_KEY` |
| ~1 giờ khi đo lại | ~2 giờ nếu phải sinh lại dữ liệu |

Khoá API **không đi qua chat và không nằm trên máy làm việc** — dán thẳng vào
Colab Secrets, ô 10 tự đọc ra. Colab Secrets **không tự thành biến môi trường**,
và mất sau mỗi lần Restart runtime — nên ô 10 phải chạy lại sau ô 30.

---

## Chạy ô nào

### 🔁 Đo lại thì BỎ QUA ô 12–18 — dữ liệu còn nguyên trên Drive

Ô 4 trỏ `ANSER_GENERATED_DIR` vào
`/content/drive/MyDrive/ANSER_AI_Logistics/generated`, nên bộ dữ liệu sinh hôm
15/08 **không mất theo runtime**. Chạy lại ô 13, 14, 15 là gọi DeepSeek lần nữa
để nhận đúng dữ liệu đang có — mất tiền và mất 35 phút, đổi lại không gì cả.

Ô 20 (preflight) vẫn chạy: nó xác nhận dữ liệu trên Drive còn đủ. Thấy ba dòng
`✓` ở mục dưới là đi thẳng sang Giai đoạn 3.

> Lần này **phải kéo lại mã nguồn** (ô 4) — ba lỗi vừa sửa nằm trong repo, không
> nằm trong notebook. Ô 4 clone thẳng từ GitHub nên chỉ cần chạy nó là đủ, miễn
> là bản sửa **đã push**.

### Giai đoạn 1 — chuẩn bị (~10 phút khi đo lại, ~35 phút khi chạy mới)

| Ô | Việc | Ghi chú |
|---|---|---|
| 2 | kiểm GPU | thấy `L4` hoặc `A100` mới đi tiếp |
| 4 | gắn Drive + kéo mã nguồn | **bắt buộc** — mang bản sửa về |
| 6 | cài thư viện | lâu nhất trong nhóm này |
| 8 | kiểm dung lượng Drive | |
| 10 | đọc khoá API | đo lại thì không cần, nhưng chạy cũng không hại |
| 12–18 | sinh dữ liệu | **bỏ khi đo lại.** Ô 13, 14, 15 gọi DeepSeek — tốn tiền |
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

## Đọc kết quả — năm cái bẫy

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

### 5. Một con số "kém" có thể là mã hỏng, không phải model kém

Ba lần liên tiếp bộ đo cho ra số xấu vì lý do không nằm ở model:

* `tool_rate = 0.0` — bộ chấm đọc `row["tool"]` trong khi file ghi `expected_tool`
* extraction và agentic gần bằng 0 — guided decoding im lặng không áp dụng
* agentic 15,8% — `arguments_schema` không đóng object *(15/08)*

Trước khi kết luận "model kém", đọc ba dòng này trong báo cáo: **`⚠ ... đầu ra
KHÔNG đọc được thành JSON`**, **`⚠ ... CẮT CỤT`**, và **`[chốt chặn]`**. Tỷ lệ
JSON hỏng ≥ 30% gần như luôn là mã, không phải model.

Riêng nhánh `bảng luật chọn tool` thì **không bao giờ** là model — đó là
`tool_planner.py`, mã tất định. Nó giống nhau ở mọi lần chạy, và sai thì sửa
bằng một dòng regex.

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

### Cân theo nhánh nào ĐANG DÙNG, không theo nhánh nào điểm cao

Đây là chỗ dễ đọc sai nhất sau phiên 15/08.

`extraction` là **bóc tách yêu cầu báo giá vận tải** — `origin`, `destination`,
`vehicle_type`. Nó thắng áp đảo (0% → 65,3%, sửa 64 câu, hỏng 0). Nhưng vận tải
vừa được hạ xuống nhánh phụ, còn lõi kế toán mà Hoàng Phát đang dùng
(`partner_audit`, `vat_catalog_audit`, `inventory_audit`, `period_diff`) là
**Python tất định, không có model nào tham gia**.

Model chỉ còn hai việc trong luồng kế toán: **diễn giải kết quả** (narration) và
**gọi tool** (agentic). Nên khi cân, cho hai nhánh đó nặng hơn hẳn — một bản
fine-tune thắng extraction mà thua narration là thắng ở chỗ khách không chạm tới.

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
