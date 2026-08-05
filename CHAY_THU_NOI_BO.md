# Chạy thử nội bộ — bản 05/08/2026

Tài liệu này để **chạy được**, không phải để đọc. Mỗi bước có cách biết mình đã
làm đúng, và cuối mỗi phần là những gì **sẽ không chạy** kèm lý do — vì phần
lớn thời gian của một buổi chạy thử bị đốt vào việc điều tra những thứ vốn đã
được biết là chưa xong.

---

## 0. Điều nên biết trước khi bắt đầu

Dữ liệu thật của Hoàng Phát chưa về. Nghĩa là:

| Chạy được ngay | Chưa chạy được | Vì sao |
|---|---|---|
| Soi lỗi sổ sách tồn kho | | có bộ dữ liệu mẫu |
| Tính lại VAT hoá đơn | | tham số nằm trong câu hỏi |
| Sinh workflow n8n | | không cần dữ liệu khách |
| Định tuyến câu hỏi | | |
| Chốt chặn neo số liệu | | |
| Nạp + tra tài liệu nội bộ | | nạp tay được |
| | Báo cáo lãi lỗ **qua chat** | `SaasAPI.get_report_lines` chưa có nguồn |
| | Báo giá vận tải | chưa cấu hình `N8N_QUOTE_WEBHOOK_URL` |
| | Dự báo đặt hàng lại | chưa có lịch sử bán theo kỳ |
| | Xếp hạng nhà xe | chưa có danh sách nhà xe + giá chào |
| | Đọc ảnh hoá đơn cước | chưa tải model VLM |

Bốn dòng cuối **trả lời đúng như thiết kế**: một câu tiếng Việt nói rõ thiếu gì
và cần làm gì. Đó không phải lỗi cần điều tra.

> Đây cũng là lý do đừng đánh giá "hệ thống trả lời kém" trong buổi này. Phần
> lớn câu hỏi nghiệp vụ sẽ dừng ở "chưa có dữ liệu" — thứ cần đánh giá là nó
> **nói thật** hay **bịa ra một câu trả lời nghe hợp lý**.

---

## 1. Đo lại model (Colab, ~40 phút)

Số trong hai báo cáo cũ không còn mô tả đúng hệ này: chúng đo trên khung đã hỏng
và trên kiến trúc "model tự chọn tool" đã bỏ.

```bash
# Colab, sau khi Restart runtime và chạy cell 1.2 -> 3.1 -> 3.1b
!cd /content/ANSER_AI && git pull
!cd /content/ANSER_AI && python offline_training/benchmark_v3.py \
    --model $AWQ_DIR --report /content/tuned_report.txt
```

**Biết mình đang chạy đúng bản mới:** trong phút đầu phải thấy hai dòng chốt chặn

```
[chốt chặn] ràng buộc JSON: ✓ CHẠY
[chốt chặn] lược đồ agentic (6 tool): ✓ dựng được
```

và một mục **hoàn toàn mới**, chạy trước khi model được gọi:

```
[bảng luật chọn tool] n=27   — mã tất định, không có model
  chọn đúng tool   xx.x%
  có kế hoạch      xx.x%
```

**Đọc kết quả:**

- `bảng luật` thấp → sửa regex trong `src/core/tool_planner.py`. Đây là mã tất
  định; **không huấn luyện lại vì con số này**.
- `biết hỏi lại` thấp → nguy hiểm nhất. Model gọi tool với tham số nó tự nghĩ ra.
- `điền tham số` thấp → chấm bằng đúng pydantic của endpoint, nên thấp ở đây
  nghĩa là production sẽ trả 422 thật.
- Không còn chỉ tiêu "model chọn đúng tool" — enum trong grammar chỉ có một tên,
  model không sinh nổi tên khác. Giữ lại chỉ tiêu đó là tự chấm điểm cho một
  ràng buộc cú pháp.

Nếu vẫn còn `⚠ n/27 đầu ra CẮT CỤT` thì báo lại — lẽ ra đã hết, vì `arguments`
nay bỏ hẳn những trường hệ thống tự bơm vào.

---

## 2. Dựng dữ liệu mẫu (máy bạn, 5 giây)

```bash
python sample_data/make_sample_data.py
```

Ra `sample_data/ton_kho_mau.xlsx`: 11 mã dầu nhờn, kỳ 01/01–30/06/2026, trong đó
**7 mã có lỗi gieo sẵn**. Đây là đề bài có đáp án — bộ soi phải tìm ra đúng 7 mã
đó và **không gắn cờ mã nào khác**:

| Mã | Lỗi gieo |
|---|---|
| `DN-TL-200` | tồn kho âm |
| `KM-4T-08` | có số lượng nhưng không ghi nhận giá trị |
| `DN-BR-18` | sổ không cân đối (ĐK + Nhập − Xuất ≠ CK) |
| `LC-COOL-200` | tồn đủ bán ~7 năm |
| `DN-CAT-20` | không xuất đơn vị nào suốt kỳ |
| `DN-GL5-18` | giá vốn hàng tồn cao hơn hàng đã bán |
| `MO-EP2-15` | giá nhập tăng 20% |

Đối chiếu tự động bằng `pytest tests/test_sample_data.py`.

---

## 3. Brain trên Colab

```bash
!cd /content/ANSER_AI && pip install -q -r requirements.txt
!cd /content/ANSER_AI && uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &
```

Rồi mở một đường hầm để máy bạn gọi vào (ngrok hoặc cloudflared).

**Env bên Brain** — bạn tự đặt:

| Biến | Dùng làm gì |
|---|---|
| `TEXT_MODEL_ID` | đường dẫn model AWQ |
| `API_AUTH_TOKEN` | token Body phải gửi kèm |
| `KB_WORKSPACE_ID` | phạm vi kho tri thức, **để trống = `default`** |

**Kiểm sống:** `GET /health` phải trả `text` sẵn sàng. Nếu `kb_error` có nội dung
thì phần tài liệu sẽ 503 — cài thêm `chromadb sentence-transformers rank_bm25
underthesea`.

---

## 4. Body trên máy bạn

`frontend/.env.local`:

| Biến | Giá trị |
|---|---|
| `BRAIN_URL` | địa chỉ đường hầm ở bước 3 |
| `BRAIN_API_TOKEN` | **đúng** `API_AUTH_TOKEN` bên Brain |
| `BRAIN_KB_WORKSPACE` | **đúng** `KB_WORKSPACE_ID` bên Brain (để trống cả hai là an toàn nhất) |

> Hai biến cuối lệch nhau là hỏng câm: tài liệu nạp lên vẫn hiện đủ trong danh
> sách, chat vẫn trả lời trôi chảy, chỉ là không bao giờ đọc tới file nào. Brain
> có ghi cảnh báo gọi đích danh cả hai biến — nếu thấy dòng đó trong log thì
> chính là chuyện này.

```bash
cd frontend && npm run dev
```

---

## 5. Kịch bản chạy thử

Làm theo thứ tự. Cột bên phải là **thứ phải thấy** — khác đi thì ghi lại.

### 5.1. Soi lỗi sổ sách (không cần model)

| Làm | Phải thấy |
|---|---|
| Tải `ton_kho_mau.xlsx` lên mục Tồn kho | 11 mã, 8 phát hiện trên 7 mã |
| Xem một phát hiện | có bằng chứng số để đối chiếu tay, không chỉ có nhãn |
| Tải lại đúng file đó | báo nội dung không đổi, không nhân đôi |
| Tải một file .xlsx hỏng | thông báo tiếng Việt nói cần làm gì, **không phải 500** |

### 5.2. Tài liệu nội bộ (RAG)

| Làm | Phải thấy |
|---|---|
| Tải một `.docx` hợp đồng bất kỳ lên mục Tài liệu | số đoạn > 0 |
| Tải một PDF **scan** (ảnh chụp) | **cảnh báo đọc được rất ít chữ** kèm cách xử lý |
| Hỏi chat một câu có trong tài liệu đó | trả lời **kèm tên file nguồn** |
| Hỏi "chính sách công nợ bên mình thế nào" khi chưa nạp gì | nói chưa có tài liệu, **không đi tra web** |
| Hỏi "nghị định 72 quy định thuế suất bao nhiêu" | được phép tra web |

Bốn và năm là cùng một tình huống "không tìm thấy" nhưng phải ra hai hành vi
khác nhau. Đây là chỗ đáng xem nhất trong cả buổi.

### 5.3. Chốt chặn neo số liệu

| Làm | Phải thấy |
|---|---|
| Hỏi một câu có dữ liệu, rồi soi câu trả lời | mọi số ≥ 4 chữ số phải có trong dữ liệu gốc |
| Nếu model bịa số | câu trả lời bị **thay bằng câu an toàn**, log ghi `Chặn câu trả lời` |

Không dựng được ca bịa số theo ý muốn thì bỏ qua — chốt chặn này đã có test.

### 5.4. Câu nhiều bước

| Làm | Phải thấy |
|---|---|
| "quý này lãi hay lỗ, mặt hàng nào lãi nhất" | *"chưa nối được dữ liệu bán hàng…"* |
| Log Brain | `Agentic: kế hoạch tool tất định ['report']` |

Đúng là câu trả lời "chưa có dữ liệu". Thứ cần xác nhận là nó **đi vào vòng
agentic và dừng lại đúng chỗ**, thay vì để model tự nghĩ ra doanh thu.

### 5.5. Sinh workflow n8n

| Làm | Phải thấy |
|---|---|
| "mỗi sáng 8h gửi tôi tổng doanh thu hôm qua qua Discord" | JSON workflow hợp lệ |
| Nhập JSON đó vào n8n | import được, không lỗi cấu trúc |
| "tạo tự động hoá" (cụt ngủn) | **hỏi lại** 3 điểm, không đoán bừa |

---

## 6. Ghi chép

Với mỗi sai lệch, ghi đúng ba thứ: **câu đã gõ**, **thứ nhận được**, **thứ
mong đợi**. Kèm `request_id` trong log Brain nếu có.

Phân biệt giúp ba loại — cách xử lý khác hẳn nhau:

1. **Chưa có dữ liệu** → đợi Hoàng Phát, không phải lỗi
2. **Sai cấu hình** → env lệch, thiếu thư viện, đường hầm chết
3. **Model trả lời kém** → loại duy nhất cần đến dữ liệu huấn luyện

Nhầm loại 2 thành loại 3 là đi train lại một model vốn không có vấn đề gì — đã
xảy ra một lần với buổi đo 04/08.
