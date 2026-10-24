# PHÂN VIỆC — Brain và Body, chu kỳ 01

**Chu kỳ:** Thứ Hai 26/10/2026 → Thứ Sáu 06/11/2026 (10 ngày làm việc)
**Lập ngày:** 24/10/2026
**Đọc cùng:** [SRS_CHU_KY_01.md](SRS_CHU_KY_01.md) cho chi tiết kỹ thuật phía Brain

---

## 1. Tài liệu này ở đâu trong bộ

| Tài liệu | Trả lời câu gì |
|---|---|
| [SRS_CHU_KY_01.md](SRS_CHU_KY_01.md) | Brain **làm gì**, nghiệm thu bằng lệnh nào |
| Bản bàn giao của Body | Body **làm gì**, do đội Body giữ |
| **File này** | **Ai làm việc nào, khi nào, và bốn chỗ hai bên chạm nhau** |

Nó **không chép lại** nội dung hai tài liệu kia. Yêu cầu kỹ thuật của Brain nằm ở SRS, và file này chỉ trỏ tới mã yêu cầu. Chép lại là tạo ra nguồn thứ hai cho cùng một thứ, đúng cái R4 cấm.

Theo [AGENTS.md §1](AGENTS.md), người làm Brain **không sửa repo Body**. Mọi việc gắn nhãn Body trong file này là **đề nghị**: đội Body đọc, phản hồi, rồi tự quyết cách làm.

---

## 2. Hiện trạng hai repo, đo ngày 24/10/2026

### Brain: `PCBoiz/ANSER_AI`

| | |
|---|---|
| Nhánh làm việc | `feat/workflow-format-and-deterministic-core` @ `645f4a1` |
| Test | 1003 passed · `ruff` sạch · `mypy` sạch |
| Nhánh chưa gộp | không còn |

### Body: ba nơi cùng lúc

| Nơi | Nhánh | Commit cuối | Nội dung |
|---|---|---|---|
| `Dgsonn/ANSER-v2` | `master` | `16ae83b` · **21/09** | bản chính |
| `Dgsonn/ANSER-v2` | `docs/onboarding-playbook` | `281b14d` · **22/10** | sổ tay cho người mới. `schema.ts` **trùng y hệt** `master` |
| `Dgsonn/ANSER-v2` | `chore/merge-feat-database-application` | `2964acf` · **22/10** | đội Body đang làm |
| **`PCBoiz/ANSER-v2-Brain`** | **`feat/brain-integration`** | **`7d19dc1` · 27/08** | **nhánh tích hợp Brain, chưa gộp lên bản chính** |

Bản sao cục bộ dùng để kiểm: `D:\ANSER_Logistics`, có cả hai remote.

---

## 3. Bốn thứ ROADMAP đánh dấu đã xong đang nằm ngoài sản phẩm

Nhánh `feat/brain-integration` đứng yên từ **27/08**, trong khi `master` của Body đi tiếp tới 21/09 rồi 22/10. Đo khoảng cách:

```
git rev-list --count origin/master..feat/brain-integration   ->  12   (nhánh có, bản chính chưa)
git rev-list --count feat/brain-integration..origin/master   ->   6   (bản chính có, nhánh chưa)
```

Trong 12 commit chưa lên bản chính có:

```
223d970  feat(ui): chi bao AI bat/tat o sidebar, va canh bao khi Brain khong kiem token
09ccbcb  feat(ui): trang huong dan cho ke toan, viet theo thu tu nguoi dung lam
3a57cbd  fix(brain): chat timeout doc duoc tu BRAIN_CHAT_TIMEOUT_MS, mac dinh giu 60s
d216f91  feat(nhap-excel): nut Nhap Excel cho danh muc MISA — xem truoc roi moi ghi
```

Bốn dòng trên [ROADMAP.md](ROADMAP.md) đánh **✅**:

> | Chỉ báo AI bật/tắt trên giao diện | ✅ chân sidebar, đỏ khi Brain không kiểm token |
> | Hướng dẫn cho người không phải kỹ thuật | ✅ trang **Hướng dẫn dùng** trong app |

Dấu ✅ đó đúng với **nhánh**, và chưa đúng với **sản phẩm**. Ai cài Body từ `Dgsonn/ANSER-v2` hôm nay sẽ không có chỉ báo AI, không có trang hướng dẫn, và `BRAIN_CHAT_TIMEOUT_MS` không đọc được.

Đây lại đúng hình dạng lỗi mà dự án đã dính bốn lần: **một thứ trông như đã có, mà chưa nối**. Lần này nó không nằm trong mã, nó nằm giữa hai repo.

**Và nó giải thích chỗ mập mờ về lược đồ.** Có **hai bản `schema.ts` khác nhau**:

| Nhánh | Blob của `frontend/src/server/db/schema.ts` |
|---|---|
| `origin/master` | `6c56f6b` |
| `origin/docs/onboarding-playbook` | `6c56f6b`, trùng `master` |
| `feat/brain-integration` | **`b87c85c`**, khác, kèm migration `0013` và `0014` |

Lược đồ 13 bảng mà [SRS §BR-03](SRS_CHU_KY_01.md) dựa vào là bản của **`master`**. Nếu nhánh tích hợp mới là bản đúng thì BR-03 đang nhắm sai đích. Đó là việc BD-02 dưới đây.

---

## 4. Mục tiêu hai tuần

| Bên | Mục tiêu một câu |
|---|---|
| **Brain** | `/chat` chạy qua vLLM server với Qwen3-8B trên L4, và đo được ngân sách ngữ cảnh. Nửa đầu của S2 |
| **Body** | Đưa nhánh tích hợp Brain về bản chính, và chốt một lược đồ duy nhất |

**Hai mục tiêu này độc lập nhau**, nên hai đội chạy song song và không chờ nhau, trừ bốn điểm chạm ở §6.

---

## 5. Bảng phân việc

### Brain: chi tiết ở [SRS_CHU_KY_01.md](SRS_CHU_KY_01.md)

| Mã | Việc | Ưu tiên | Hạn | Phụ thuộc |
|---|---|---|---|---|
| BR-01 | `/tools/vat` từ chối trường lạ thay vì tính bằng 0 | P0 | T3 27/10 | không |
| BR-02 | Thêm đường chat cho `VLLMServerClient` | P0 | T4 28/10 | không |
| BR-03 | `engine.py` rẽ nhánh theo backend, kèm phép thử chứng minh thi hành | P0 | T5 29/10 | BR-02 |
| BR-04 | Dựng vLLM server trên Colab L4, đo ngân sách ngữ cảnh | P0 | T6 30/10 | BR-03 |
| BR-05 | Đo bản fine-tune, dựng bảng phân loại lỗi | P1 | T4 04/11 | BR-04 |
| BR-06 | Bộ đo RAG | P1 | T5 05/11 | không |
| BR-07 | Mở rộng cổng lint của CI | P2 | T6 06/11 | không |

### Body: đề nghị

| Mã | Việc | Ưu tiên | Hạn đề nghị |
|---|---|---|---|
| **BD-01** | **Gộp `feat/brain-integration` về `Dgsonn/ANSER-v2`** | **P0** | T6 30/10 |
| **BD-02** | **Chốt một bản `schema.ts` duy nhất** và báo cho Brain | **P0** | T3 27/10 |
| BD-03 | Giữ phép thử hợp đồng đường dẫn chạy được, xem §6.4 | P1 | T2 02/11 |
| BD-04 | Đưa Body lên chỗ khách truy cập được | P1 | T6 06/11 |

#### BD-01. Gộp nhánh tích hợp về bản chính

12 commit chưa lên, 6 commit chưa lấy về. Càng để lâu càng khó gộp, và khoảng cách đã là tám tuần.

Thứ tự đề nghị: lấy 6 commit của `master` về nhánh trước, giải quyết xung đột ở `schema.ts` và hai migration `0013`, `0014`, rồi mới mở PR ngược lên. Làm ngược chiều thì xung đột rơi vào PR và khó soát hơn.

**Nghiệm thu:** cài Body sạch từ `Dgsonn/ANSER-v2`, chạy lên, thấy chỉ báo AI ở chân sidebar và trang Hướng dẫn dùng.

#### BD-02. Chốt một bản lược đồ duy nhất

Brain cần biết bản nào là bản đúng để sửa `SCHEMA MAP`. Hiện có hai bản khác nhau, xem §3.

**Cần trả lời bốn câu:**
1. Nhánh nào giữ lược đồ đúng cho chu kỳ này?
2. Migration `0013` và `0014` có lên bản chính không?
3. Hoá đơn có `sales_invoices.warehouse_id = NULL` là hợp lệ, hay là dữ liệu lỗi? Cột này **nullable**, nên câu `WHERE warehouse_id = :ws` sẽ âm thầm bỏ qua chúng.
4. Khi lược đồ đổi tiếp, báo cho Brain bằng đường nào?

**Nghiệm thu:** một tin nhắn hoặc PR mô tả có đủ bốn câu trả lời, trước 17h Thứ Ba 27/10.

#### BD-03. Giữ phép thử hợp đồng đường dẫn chạy được

`tests/test_body_contract.py` của Brain đọc **thẳng** `frontend/src/server/brain.ts` để kiểm mọi đường dẫn Body gọi đều có thật bên Brain. Hiện `brain.ts` gọi 11 đường:

```
/chat  /health  /knowledge/documents  /ocr/freight
/tools/inventory-audit   /tools/inventory-import
/tools/partner-audit     /tools/partner-import
/tools/period-diff       /tools/product-import     /tools/report
```

Phép thử này **chỉ chạy khi có bản sao Body trên đĩa**, qua biến `ANSER_BODY_DIR`, mặc định trỏ vào `../ANSER_Logistics` cạnh repo Brain. Không có thì nó `skip`, và trên CI thì nó luôn skip.

Đây là thứ **duy nhất** canh việc Brain đổi tên đường dẫn mà Body không biết. Triệu chứng khi nó không chạy: khách bấm nút rồi nhận 404, trong khi test hai bên đều xanh.

**Đề nghị:** đội Body báo cho Brain khi `brain.ts` thêm hoặc đổi đường dẫn. Dài hạn, hai bên cân nhắc đưa danh sách đường dẫn vào một file nhỏ mà cả hai repo cùng đọc.

#### BD-04. Đưa Body lên chỗ khách truy cập được

Ô đỏ duy nhất còn lại của Giai đoạn B trong [ROADMAP.md](ROADMAP.md). Nó **không chặn** chu kỳ này và cũng **chưa chết**.

Điều đáng biết khi tới lúc làm: lớp sinh ra giá trị của Brain **không cần GPU**. Kiểm ngày 24/10 với `RUNTIME_PROFILE=minimal`, Brain phục vụ toàn bộ `/tools/*` trên máy CPU trong khi `/health` trả `engine_ready: false`, và `/tools/inventory-audit` vẫn ra phát hiện kèm `money_impact`. Nghĩa là Body đi lên trước được, phần hỏi đáp AI nối sau.

Xếp P1 và hạn cuối chu kỳ vì BD-01 quan trọng hơn: đưa một bản thiếu chỉ báo AI và thiếu trang hướng dẫn lên cho khách thì lợi bất cập hại.

---

## 6. Bốn chỗ hai bên chạm nhau

Ngoài bốn chỗ này, hai đội không chờ nhau.

### 6.1. Lược đồ canon

**Ai cần:** Brain, cho BR-03 và cho việc viết `get_report_lines`.
**Ai cấp:** Body, qua BD-02.
**Hạn:** Thứ Ba 27/10.
**Nếu trễ:** BR-03 đã nằm ở mục ngoài phạm vi của SRS chu kỳ này, nên trễ không làm vỡ lịch Brain. Nó chỉ làm việc đó lùi tiếp sang chu kỳ 02.

### 6.2. Hợp đồng `/health`

Brain đổi `/health` ở BR-03: thêm trường khai backend đang dùng, và `engine_ready` có thêm nghĩa "tắt theo thiết kế" khi chạy `RUNTIME_PROFILE=minimal`.

`brain.ts` đang đọc năm trường, khoá bởi `test_health_co_du_truong_body_doc`:

```
status · degraded · engine_ready · vision_ready · load
```

**Cam kết của Brain:** năm trường đó **PHẢI giữ nguyên tên và kiểu** trong cả chu kỳ. Brain chỉ **thêm** trường, không đổi và không bớt.

**Đề nghị với Body:** phân biệt ba trạng thái thay vì hai, vì "AI tắt theo thiết kế" khác "AI hỏng". Hiện `feat/brain-integration` đã có chỉ báo hai trạng thái ở `223d970`. Trạng thái thứ ba cần thêm là `runtime_profile == "minimal"`.

### 6.3. Mã 503 và `Retry-After`

Khi `/chat` đi qua vLLM server, Brain có thêm một đường trả lời: **503 kèm header `Retry-After`** khi hàng đợi đầy hoặc server model chưa sẵn sàng. Đây là câu trả lời hợp lệ "đang bận, quay lại sau", không phải lỗi máy chủ.

**Đề nghị với Body:** `brain.ts` xử 503 bằng cách đọc `Retry-After` rồi hỏi lại, và hiện một câu tiếng Việt nói rõ hệ thống đang bận. Trả về lỗi chung chung sẽ khiến người dùng bấm lại liên tục và làm tình hình tệ thêm.

`BRAIN_CHAT_TIMEOUT_MS` đã có từ `3a57cbd`, nhưng commit đó nằm trong 12 commit chưa gộp. Nên BD-01 cũng là điều kiện để phần này dùng được.

### 6.4. Phép thử hợp đồng đường dẫn

Xem BD-03. Brain giữ phép thử, Body báo khi `brain.ts` đổi.

---

## 7. Lịch hai tuần

### Tuần 1: Thứ Hai 26/10 đến Thứ Sáu 30/10

| Ngày | Brain | Body |
|---|---|---|
| **T2 26/10** | Chốt ai nhận luồng nào (SRS §6.1). Đọc `serving.py`, `engine.py` | Lấy 6 commit của `master` về `feat/brain-integration`, xử xung đột `schema.ts` |
| **T3 27/10** | BR-01 · BR-02 | **BD-02 hạn 17h**, trả lời bốn câu về lược đồ |
| **T4 28/10** | **BR-02 hạn.** Bắt đầu BR-03 | Gộp tiếp, chạy `pnpm lint` và `npx tsc --noEmit` |
| **T5 29/10** | **BR-03 hạn**, phép thử chứng minh server nhận request | Mở PR ngược lên `Dgsonn/ANSER-v2` |
| **T6 30/10** | **BR-04 hạn**, dựng server trên L4, đo ngân sách ngữ cảnh | **BD-01 hạn**, PR gộp xong |

### Tuần 2: Thứ Hai 02/11 đến Thứ Sáu 06/11

| Ngày | Brain | Body |
|---|---|---|
| **T2 02/11** | Chạy lại BR-04 một mình, xác nhận làm được không cần hỏi ai | **BD-03**, thống nhất cách báo khi `brain.ts` đổi |
| **T3 03/11** | BR-06 dựng bộ câu hỏi và nhãn | Chỉ báo AI ba trạng thái (§6.2) · xử 503 (§6.3) |
| **T4 04/11** | **BR-05 hạn**, phiên đo và bảng phân loại lỗi | BD-04 chuẩn bị chỗ đặt |
| **T5 05/11** | **BR-06 hạn**, báo cáo chỉ số RAG | BD-04 |
| **T6 06/11** | BR-07 · viết biên bản chu kỳ | **BD-04 hạn** · cùng viết biên bản |

---

## 8. Hai mốc đồng bộ

Hai đội ngồi với nhau đúng hai lần. Ngoài hai buổi này thì làm việc độc lập.

**M1, Thứ Sáu 30/10 cuối ngày, 30 phút.** Mỗi bên trả lời đúng một câu:

| Bên | Câu hỏi |
|---|---|
| Brain | Một câu hỏi thật có đi trọn vòng từ `/chat` qua `VLLM_BASE_URL` tới vLLM server trên L4 và quay về không, và log server có ghi nhận request đó không? |
| Body | Cài Body sạch từ `Dgsonn/ANSER-v2` có thấy chỉ báo AI và trang Hướng dẫn dùng không? |

Bên nào không đạt thì **dừng việc P1 và P2 của bên đó**, dồn vào đường găng.

**M2, Thứ Sáu 06/11.** Biên bản chu kỳ, viết chung một file. Ghi ba thứ: cái gì xong, cái gì trượt kèm lý do, cái gì đẩy sang chu kỳ 02.

---

## 9. Cái gì không làm trong chu kỳ này

| Việc | Vì sao hoãn |
|---|---|
| Brain sửa `SCHEMA MAP` và viết `get_report_lines` | Chờ BD-02. Không nằm trên đường găng của S2, lấy làm việc đệm nếu BR-05 hoặc BR-06 xong sớm |
| Nối Redis cho `TASK_REGISTRY`, nối `vllm-vision` qua HTTP, dựng Cloudflare Tunnel | Nửa sau của S2, sang chu kỳ 02 |
| Mảng vận tải | Chặn bởi khách. Hoàng Phát chưa làm vận tải |
| Huấn luyện lại model | Bảng phân loại lỗi của BR-05 là đầu vào cho quyết định này |
| Tìm kế toán rà sổ | Chủ dự án chốt 24/10: tính sau |
| Body đổi lược đồ theo yêu cầu của Brain | Chu kỳ này Brain thích nghi theo Body, không ngược lại |

---

## 10. Chủ dự án cần quyết

| # | Câu hỏi | Chặn gì | Hạn |
|---|---|---|---|
| 1 | **`feat/brain-integration` có gộp về `Dgsonn/ANSER-v2` không, hay Body đi tiếp trên bản chính và bỏ nhánh đó?** | BD-01, tức bốn tính năng ROADMAP đang đánh ✅ | T2 26/10 |
| 2 | Ai nhận luồng A và luồng B bên Brain | Lịch tuần 1 của Brain | T2 26/10 |
| 3 | Đội Body có người làm trong hai tuần này không, và là ai | Toàn bộ cột Body | T2 26/10 |
| 4 | Nếu BR-04 cho thấy ctx 32k không vừa: hạ ctx, hay đẩy vision sang tiến trình riêng | Quyết định kiến trúc cuối tuần 1 | khi có số đo, T6 30/10 |

Câu 1 là câu đáng quyết nhất. Nếu bỏ nhánh tích hợp thì bốn tính năng kia phải làm lại, và ROADMAP phải sửa dấu ✅ thành ❌ để không ai tin nhầm lần nữa.

---

## 11. Tham chiếu

| Cần gì | Đọc đâu |
|---|---|
| Yêu cầu kỹ thuật Brain, nghiệm thu từng việc | [SRS_CHU_KY_01.md](SRS_CHU_KY_01.md) |
| Dựng môi trường Brain, hiểu mã, từ điển thuật ngữ | [SO_TAY_NGUOI_MOI.md](SO_TAY_NGUOI_MOI.md) |
| Bảy việc dài hạn của Brain | [GIAO_VIEC_BRAIN.md](GIAO_VIEC_BRAIN.md) |
| Đang ở đâu, cái gì đã chắc | [TIEN_TRINH_BRAIN.md](TIEN_TRINH_BRAIN.md) |
| Ranh giới hai repo, năm ràng buộc | [AGENTS.md](AGENTS.md) |
| Cổng ra từng giai đoạn | [ROADMAP.md](ROADMAP.md) |
| Hợp đồng API, đọc thẳng `brain.ts` | `tests/test_body_contract.py` |
