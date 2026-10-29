# BIÊN BẢN CHU KỲ 01 — 26/10 đến 06/11/2026

**Viết:** 29/10/2026 · **Phần Brain:** Thành · **Phần Body:** Sĩ, Sơn, Nam (mục 10, chờ điền)
**Đặc tả:** [SRS_CHU_KY_01.md](SRS_CHU_KY_01.md) · **Phân việc:** [PHAN_VIEC_CHU_KY_01.md](PHAN_VIEC_CHU_KY_01.md)
**Nhánh:** `feat/workflow-format-and-deterministic-core` @ `fffbabd` — chưa mở PR, chưa merge `main`

Khuôn theo PHAN_VIEC mốc M2: **cái gì xong, cái gì trượt kèm lý do, cái gì đẩy sang chu kỳ 02.** Số liệu chi tiết nằm ở [BAO_CAO_BR04.md](BAO_CAO_BR04.md) và [BAO_CAO_BR05.md](BAO_CAO_BR05.md); biên bản này chỉ dẫn tới.

---

## 1. Tóm tắt

1. **Mục tiêu S2 đạt:** `/chat` chạy qua vLLM server thật trên Colab L4, có log server ghi nhận request của Brain, cùng vision đang nạp.
2. **Cả 6 việc Brain của chu kỳ xong phần mã** (BR-01 đến BR-05, BR-07); BR-06 đã chuyển chu kỳ 02 theo SRS. **Một nghiệm thu chưa làm được:** BR-07 cần CI chạy thật, mà CI của repo **chưa từng chạy** (mục 6).
3. **Đo bản fine-tune xong, kể cả so cặp với bản gốc:** giữ fine-tune — làm hỏng 8 câu, sửa 88 câu. Lỗi còn lại phần lớn là **dữ liệu huấn luyện**, đầu vào cho quyết định huấn luyện lại ở chu kỳ 02.
4. **Lộ ra và đã chặn hai lớp lỗi R1 mà chốt cũ không bắt:** model **chép sai đầu vào tool** rồi tool tính đúng trên số sai (Brain báo 5.500.000 thay vì 6.050.000), và model **suy biến** ra rác chữ Hán/lặp tới trần token. Cả hai nay có chốt tất định ở production.
5. **Không phát sinh chi phí mới** — Colab Pro sẵn có (NFR-02).

---

## 2. Việc Brain — trạng thái

| Việc | Ưu tiên · hạn | Trạng thái | Bằng chứng |
|---|---|---|---|
| **BR-01** `/tools/vat` từ chối trường lạ | P0 · 27/10 | **Xong** | `7214df1`, `553e396`; trả 422, không tính bằng 0 |
| **BR-02** Đường chat cho `VLLMServerClient` | P0 · 29/10 | **Xong** | `5f3e37b`; ba bất biến payload có test: chat template, `enable_thinking=False`, `repetition_penalty=1.0` khi bật grammar |
| **BR-03** `engine.py` rẽ theo backend | P0 · 02/11 | **Xong** | `8b69afb`; nghiệm thu trên Colab: log vLLM ghi `POST /v1/chat/completions 200` từ Brain |
| **BR-04** vLLM trên L4, ngân sách ctx | P0 · 04/11 | **Xong** (9/10 yêu cầu) | BAO_CAO_BR04; ctx **chốt 32768**, p95 **chốt hai ngưỡng**. Yêu cầu 8 chưa đo → chu kỳ 02 |
| **BR-05** Đo fine-tune, bảng phân loại lỗi | P1 · 05/11 | **Xong** (9/9 yêu cầu) | BAO_CAO_BR05 §3 (bảng phân loại), §6d (so cặp với bản gốc) |
| **BR-06** Bộ đo RAG | — | **Chuyển chu kỳ 02** | Quyết định trong SRS, không phải trượt |
| **BR-07** Mở rộng cổng lint CI | P2 · 06/11 | **Xong phần mã, nghiệm thu treo** | `31aafa1`: `ruff check src tests offline_training`, sạch trên Colab. Nhánh `ci/br07-nghiem-thu` đã đẩy (đỏ rồi xanh) nhưng **CI không chạy** — mục 6 |

---

## 3. Cổng ra chu kỳ (SRS §7)

| Mục | Trạng thái |
|---|---|
| `/chat` qua vLLM server, có phép thử chứng minh server **nhận** request (BR-03) | **Đạt** — log vLLM ghi 2 request của Brain cho câu hoá đơn (BR-04 §5.2) |
| Ba bẫy §3.3 có phép thử riêng và xanh (BR-02) | **Đạt** — cộng **bẫy thứ tư** tìm ra trong BR-04: xgrammar bỏ qua khoá đứng cạnh `oneOf`, grammar agentic không thi hành trên server; sửa `82e9e9c`, test bằng xgrammar thật |
| Ngân sách ctx đo trên L4, ≥ 3 mức, **với vision đang nạp**; quyết định vào ARCHITECTURE (BR-04) | **Đạt** — 8192/16384/32768 đều dựng được, KV 36.176 token ở gmu 0,55, VRAM đỉnh 21,1 GB; chốt 32768 và `ANSER_TEXT_MAX_CONCURRENT=4` |
| Bảng ARCHITECTURE §5.1 sửa (vision bf16 7,5 GB) (BR-04) | **Đạt** — đo 7.874 MiB |
| Bảng phân loại lỗi fine-tune theo nhánh, số ca, ví dụ nguyên văn, quy về ba nguyên nhân (BR-05) | **Đạt** — BAO_CAO_BR05 §3 |
| `/tools/vat` trả 422 cho trường lạ (BR-01) | **Đạt** |
| `pytest -q` xanh và `ruff` sạch trên đúng mã đã đo | **Đạt, kèm ghi chú** — `fffbabd` trên Colab: **1163 passed, 4 skipped**; ruff **All checks passed** trên cả `src tests offline_training`. Phiên so cặp chạy ở `31aafa1`; các commit sau đó thêm chốt suy biến, biến env và test, không đổi đường đo trừ `per_row` của bảng hệ thống. **CI không xác nhận được** (mục 6) — xanh là do chạy tay |
| Biên bản ghi treo 1 và 2, chi phí thật, danh sách sang chu kỳ 02 | **Đạt** — mục 4, 5, 7 của biên bản này |

---

## 4. Việc treo của TIEN_TRINH

| Treo | Trạng thái |
|---|---|
| **#1** `render_tools()` từng quảng cáo trường hệ thống tự bơm | **Đề xuất đóng, chờ chủ dự án** — sau khi sửa bảng luật (BR-05 §6b), agentic: chịu gọi tool 100%, điền tham số đúng kiểu 100% (n=9), không ca agentic nào cắt cụt ở cả ba lần đo 28–29/10. Lý do chưa tự đóng: n=9 nhỏ, và lỗi gốc (mảng `lines` dài tràn trần) không còn câu nào trong bộ đề tái hiện |
| **#2** Đo lại sau khi có `providers.py` | **Đóng 27/10** — `[chốt chặn] ràng buộc JSON: ✓ CHẠY` |
| **#3** Ba phần hạ tầng khai báo mà chưa nối | Không thuộc chu kỳ này |
| **#4** RAG chưa có thước đo | Đi cùng BR-06 → chu kỳ 02 |
| **#5** Model chép thiếu đầu vào cho tool (mở 26/10) | **Đóng 28/10** — xem mục 5.1 |

---

## 5. Phát hiện ngoài kế hoạch, đã xử lý

### 5.1. Model chép sai đầu vào tool — chốt đầu vào (`src/core/doc_dau_vao.py`)

Câu hoá đơn 5.000.000 + 500.000, model gửi cho `vat` **một** dòng; Brain trả lời "tổng thực tế 5.500.000đ" kèm "kết quả từ công cụ VAT" — sai mà trông có nguồn. Chủ dự án chốt làm cả hai cách, theo trường hợp:

| Đã làm | Ghi chú |
|---|---|
| **B** — hoá đơn dán có cấu trúc thì mã bóc dòng hàng, ghi đè model; câu liệt kê ≥ 2 lời chào giá thì mã dựng `carriers`/`offers` | `carrier_selection` trước đó luôn hỏi lại vì "chưa có nguồn" |
| **A** hai chiều — số tiền trong câu phải có trong tham số (thiếu), số tiền trong tham số phải có trong câu (bịa) | đọc cả số bằng chữ ("năm triệu rưỡi") và nói tắt ("12tr5") |
| Giá đã gồm VAT hay chưa: câu không nói thì **hỏi lại**; lượt trả lời được ghép với hoá đơn lượt trước | chủ dự án chốt; tool `vat` có thêm chế độ giá đã gồm thuế |
| Tham số chính sách giá câu không nói tới (`fuel_sensitivity`, `min_margin_amount`, `fuel_baseline_price`) thì **mã xoá**, tool dùng mặc định | model điền `fuel_sensitivity` 0,05 thay 0,35 ở 2/2 câu — chốt số tiền không bắt được |
| Một hàm `chot_dau_vao` dùng chung cho production và benchmark | đo đúng thứ chạy thật (R4) |

**Kết quả trên vLLM thật:** câu hoá đơn ra **6.050.000, chênh 450.000** (đúng). Benchmark qua chốt: **an toàn 100%, lọt 0** với cả bản gốc lẫn fine-tune; trả lời ngay 44,4% (gốc) và 100% (fine-tune).

### 5.2. Model suy biến — chốt suy biến (`grounding.kiem_suy_bien`)

6–13/27 câu diễn giải của bản fine-tune hết ý thì trôi sang chữ Hán hoặc kê từ tiếng Anh, rồi lặp tới trần 2048 token. Đo `repetition_penalty` 1,25 / 1,1 / 1,0: hạ phạt giảm suy biến nhưng không hết và bịa số tăng — **gốc ở dữ liệu huấn luyện**. Chủ dự án chốt giữ 1,25, thêm chốt: câu có chữ Hán hoặc 100 ký tự cuối lặp nguyên văn thì thay câu an toàn. Chốt số liệu không bắt được loại này vì rác không có số.

### 5.3. Các quyết định chủ dự án đã chốt trong chu kỳ

| Ngày | Quyết định |
|---|---|
| 28/10 | `TEXT_MAX_MODEL_LEN` 32768 |
| 28/10 | "Báo giá" tách ba ý định: xin báo giá → n8n; tính giá bán → `quote`; so lời chào → `carrier_selection` |
| 28/10 | Chép sai đầu vào: làm cả A và B theo trường hợp; `carrier_selection` đọc lời chào từ câu |
| 28/10 | Giá không nói gồm VAT chưa → hỏi lại |
| 28/10 | p95 hai ngưỡng: ≤ 60 ms/token (`P95_MS_MOI_TOKEN`) và ≤ 5.000 ms tổng (`P95_NGUONG_MS`) |
| 28/10 | Tham số chính sách giá model bịa → mã xoá, dùng mặc định |
| 29/10 | Suy biến: giữ `repetition_penalty` 1,25, thêm chốt |

---

## 6. Rủi ro lớn nhất: CI của repo chưa từng chạy

GitHub Actions của `PCBoiz/ANSER_AI`: **136 lượt, 0 lượt xanh**. Mọi job kết thúc với *"The job was not started because your account is locked due to a billing issue"* — từ lượt cũ nhất đã soi (14/05/2026) tới nay. Khoá ở tài khoản **chủ repo `PCBoiz`**, không phải tài khoản người đẩy mã.

Hệ quả:

- **Không có cổng tự động nào đang hoạt động** — pytest, ruff, mypy, dataset preflight chỉ chạy khi có người chạy tay trên Colab.
- Các chỗ trong tài liệu cũ nói "CI xanh" **không có lượt chạy nào chứng minh**.
- Nghiệm thu BR-07 ("lỗi mới PHẢI làm CI đỏ") **không thực hiện được**.

**Cần chủ repo:** gỡ khoá ở *Settings → Billing and plans*, rồi *Re-run jobs* hai lượt trên nhánh `ci/br07-nghiem-thu` (mong đợi: đỏ ở bước Ruff, rồi xanh).

**Nếu không gỡ được** — ba hướng, cần chọn: (a) chạy CI trên fork công khai của người làm (Actions miễn phí cho repo công khai, tài khoản không bị khoá); (b) nghiệm thu bằng ruff chạy tay, ghi là lệch so với SRS; (c) thêm cấu hình pre-commit chạy ruff ở máy dev — bổ trợ, không thay được CI.

---

## 7. Đẩy sang chu kỳ 02

### 7.1. Theo kế hoạch

| Việc | Ghi chú |
|---|---|
| **BR-06** bộ đo RAG | SRS chuyển từ đầu chu kỳ |
| **BR-04 yêu cầu 8** — ctx đủ cho kế hoạch 3 tool + RAG, đo bằng ca thật | cần RAG có thước đo trước; đi cùng BR-06 |
| Huấn luyện lại model | SRS: không làm chu kỳ này; bảng phân loại lỗi là đầu vào |

### 7.2. Đầu vào cho vòng huấn luyện lại (lỗi do **dữ liệu**, BAO_CAO_BR05)

| Lỗi | Quy mô | Nguồn |
|---|---|---|
| Narration không biết dừng → suy biến tới trần token | 6–13/27 câu | §6d |
| Chép sai dấu ngăn nghìn → số lệch ×10 (12.709.000 → 127.090.000) | lặp lại ở mọi mức phạt | §3, §6d |
| Extraction điền bừa trường đáng để trống (xưng hô thành tên, mặc định `dau_keo`/`Hà Nội`) | ~53 ca | §3 |
| Extraction tự tính ngày tương đối — LLM làm phép tính, trái R1 | ~21 ca | §3 |
| Workflow n8n trỏ tới node `noOp` không khai | 2/4 ca n8n trượt | §6d |
| Bộ đề: ~10 nhãn extraction sai; nhãn "phải hỏi lại" của AG0009 có thể tranh cãi | — | §3, §6b |

### 7.3. Hở đã biết của các chốt mới

| Hở | Hệ quả |
|---|---|
| Kê từ tiếng Anh mà chưa kịp lặp thì chốt suy biến chưa bắt | rác có thể lọt |
| Model bỏ giá dầu lúc chốt bảng giá → vẫn phải hỏi lại khách (AG0015) | khách mất một lượt; sửa bằng bộ bóc riêng cho câu tính giá |
| Cách A có thể hỏi lại thừa khi câu nhắc số tiền không phải đầu vào | khách mất một lượt |
| `carrier_selection` chỉ xếp theo giá / chiết khấu / công nợ có trong câu | tiêu chí khác tool tự bỏ |
| Hoá đơn không nói gồm VAT chưa luôn tốn thêm một lượt | theo quyết định 28/10 |

### 7.4. Khung đo

| Việc | Ghi chú |
|---|---|
| Câu không có kế hoạch tool vẫn bị chấm qua vòng agentic, trong khi production đưa sang nhánh router | là lý do "biết hỏi lại" kẹt 25% — BAO_CAO_BR05 §6b |
| Kết quả dao động ±1 ca giữa các lần chạy dù `temperature=0` | batching vLLM; cần đo nhiều lần hoặc tăng bộ đề |

---

## 8. Chi phí thật (NFR-02)

| Khoản | Số |
|---|---|
| Hạ tầng mới | **0đ** — Colab Pro sẵn có, không thuê GPU |
| GPU dùng | Colab L4, nhiều phiên 26–29/10 (BR-04, BR-05 ba lần đo, so cặp, đo phạt lặp). Không ghi số giờ chính xác |
| Model tải thêm | `Qwen/Qwen3-8B-AWQ` (HF, miễn phí) cho so cặp |

---

## 9. Việc còn mở, cần quyết trước khi khép chu kỳ

| # | Việc | Ai |
|---|---|---|
| 1 | Gỡ khoá thanh toán GitHub, hoặc chọn hướng (a)/(b)/(c) ở mục 6 | chủ repo `PCBoiz` / chủ dự án |
| 2 | Đóng treo #1 hay đo thêm (mục 4) | chủ dự án |
| 3 | Thư mục `docs/ban-in/BR05` (dữ liệu đo, chưa vào git): chuyển lên Drive hay `.gitignore` | chủ dự án |
| 4 | Dựng lại bản PDF `docs/ban-in` cho BAO_CAO_BR04, BAO_CAO_BR05, biên bản này | chủ dự án quyết, Thành làm |
| 5 | Mở PR cho nhánh làm việc để review (không merge `main`) | chủ dự án |
| 6 | Sửa câu "không tự tạo notebook" trong SO_TAY và AGENTS — lỗi AI sinh, Colab được phép | Thành |
| 7 | Xoá nhánh `ci/br07-nghiem-thu` sau khi nghiệm thu xong | Thành |

---

## 10. Phần Body (đội Body điền)

| Việc | Người | Trạng thái | Ghi chú |
|---|---|---|---|
| BD-01 Gộp `feat/brain-integration` về `Dgsonn/ANSER-v2` | Sĩ, Sơn | | |
| BD-02 Chốt một bản `schema.ts` duy nhất và báo Brain | Sơn | | |
| BD-03 Giữ phép thử hợp đồng đường dẫn chạy được | Nam | | |
| BD-04 Đưa Body lên chỗ khách truy cập được | Nam | | |
