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
| BR-02 | Thêm đường chat cho `VLLMServerClient` | P0 | T5 29/10 | không |
| BR-03 | `engine.py` rẽ nhánh theo backend, kèm phép thử chứng minh thi hành | P0 | T2 02/11 | BR-02 |
| BR-04 | Dựng vLLM server trên Colab L4, đo ngân sách ngữ cảnh | P0 | T4 04/11 | BR-03 |
| BR-05 | Đo bản fine-tune, dựng bảng phân loại lỗi | P1 | T5 05/11 | BR-04 |
| BR-07 | Mở rộng cổng lint của CI | P2 | T6 06/11 | không |

**Tất cả do Thành làm**, một người. Nên `BR-02 → BR-03 → BR-04 → BR-05` là một chuỗi **nối tiếp**, không có ai chạy song song để bù khi một mắt xích trượt. Ước lượng công là 7 đến 9 ngày trên 10 ngày làm việc, tức biên dự phòng chỉ 1 đến 3 ngày.

**BR-06, bộ đo RAG, đã chuyển sang chu kỳ 02.** Nó cần khoảng 3 ngày và không nằm trên đường găng. Thà chở năm việc tới nơi còn hơn bảy việc dở dang.

### Body: đề nghị

| Mã | Việc | Ưu tiên | Người đề nghị | Hạn đề nghị |
|---|---|---|---|---|
| **BD-01** | **Gộp `feat/brain-integration` về `Dgsonn/ANSER-v2`** | **P0** | Sĩ chủ trì, Sơn cùng xử xung đột lược đồ | T6 30/10 |
| **BD-02** | **Chốt một bản `schema.ts` duy nhất** và báo cho Brain | **P0** | Sơn | T3 27/10 |
| BD-03 | Giữ phép thử hợp đồng đường dẫn chạy được, xem §6.4 | P1 | Nam | T2 02/11 |
| BD-04 | Đưa Body lên chỗ khách truy cập được | P1 | Nam | T6 06/11 |

> **Cột người là đề nghị theo hình dạng việc, không theo hiểu biết về năng lực từng người.** Đội Body đổi thoải mái, miễn mỗi việc có **đúng một người chịu trách nhiệm**. Lý do xếp như trên: BD-01 là việc nặng nhất và dính lược đồ nên ghép hai người; BD-02 nằm ở tầng DB nên để cùng người xử xung đột lược đồ; BD-03 và BD-04 độc lập nên một người chạy song song được.

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

| Ngày | Brain · Thành | Body · Sĩ, Sơn, Nam |
|---|---|---|
| **T2 26/10** | Dựng môi trường, ra 1003 passed. **BR-01** | **Sơn** lấy 6 commit của `master` về nhánh, xử xung đột `schema.ts`. **Nam** rà chỗ đặt cho BD-04 |
| **T3 27/10** | **BR-01 hạn.** Đọc `serving.py`, `engine.py`, chốt thiết kế rẽ nhánh backend | **BD-02 hạn 17h**, Sơn trả lời bốn câu về lược đồ |
| **T4 28/10** | **BR-02** | **Sĩ** gộp tiếp, chạy `pnpm lint` và `npx tsc --noEmit` |
| **T5 29/10** | **BR-02 hạn.** Bắt đầu **BR-03** | **Sĩ** mở PR ngược lên `Dgsonn/ANSER-v2` |
| **T6 30/10** | **BR-03** | **BD-01 hạn**, PR gộp xong |

### Tuần 2: Thứ Hai 02/11 đến Thứ Sáu 06/11

| Ngày | Brain · Thành | Body · Sĩ, Sơn, Nam |
|---|---|---|
| **T2 02/11** | **BR-03 hạn**, kèm phép thử chứng minh server nhận request | **BD-03 hạn**, Nam thống nhất cách báo khi `brain.ts` đổi |
| **T3 03/11** | **BR-04**, dựng vLLM server trên Colab L4 | Chỉ báo AI ba trạng thái (§6.2) · xử 503 (§6.3) |
| **T4 04/11** | **BR-04 hạn**, đo ba mức `max_model_len` với vision đang nạp | **Nam** chuẩn bị chỗ đặt cho BD-04 |
| **T5 05/11** | **BR-05 hạn**, phiên đo và bảng phân loại lỗi | BD-04 |
| **T6 06/11** | **BR-07** nếu còn ngày · viết biên bản | **BD-04 hạn** · cùng viết biên bản |

> **Hạn phía Brain lùi so với bản trước**, vì bản trước giả định hai người chạy song song. Một người thì `BR-02 → BR-03 → BR-04` phải nối tiếp, và dồn cả ba vào tuần 1 là đặt một hạn không ai giữ được.

---

## 8. Hai mốc đồng bộ

Hai đội ngồi với nhau đúng hai lần. Ngoài hai buổi này thì làm việc độc lập.

**M1, Thứ Sáu 30/10 cuối ngày, 30 phút.** Mỗi bên trả lời đúng một câu:

| Bên | Câu hỏi |
|---|---|
| Brain | `VLLMServerClient` đã có đường chat chưa, và ba phép thử payload đã xanh chưa? Tức `chat_template_kwargs`, `guided_json`, và `repetition_penalty == 1.0` khi bật grammar. Đây là mốc giữa đường: một người thì BR-03 chưa thể xong trong tuần 1 |
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

## 10. Bốn quyết định của chủ dự án, chốt ngày 24/10/2026

| # | Câu hỏi | Quyết định | Đổi gì trong tài liệu này |
|---|---|---|---|
| 1 | `feat/brain-integration` có gộp về `Dgsonn/ANSER-v2` không | **Có, gộp sớm nếu cần** | BD-01 giữ P0, hạn T6 30/10. Bốn tính năng ROADMAP đánh dấu đã xong sẽ về đúng sản phẩm |
| 2 | Ai nhận phần Brain | **Thành**, một người, cả hai luồng | Chuỗi BR-02 → BR-03 → BR-04 → BR-05 thành nối tiếp. **BR-06 sang chu kỳ 02.** Hạn Brain lùi, xem §7 |
| 3 | Đội Body tuần này gồm ai | **Sĩ, Sơn, Nam** | §5 có cột người đề nghị theo hình dạng việc |
| 4 | Nếu ctx 32k không vừa thì hạ ctx hay đẩy vision sang tiến trình riêng | **Hạ ctx**, vì cần dựng được môi trường giả lập production để thử Brain | Phương án tách tiến trình `vllm-vision` rời khỏi bàn trong chu kỳ này. Xem [SRS §BR-04](SRS_CHU_KY_01.md) yêu cầu 7 đến 10 |

### 10.1. Hai thứ còn để ngỏ

| # | Câu hỏi | Khi nào cần trả lời |
|---|---|---|
| 1 | **Ctx chốt ở mức nào**, và `ANSER_TEXT_MAX_CONCURRENT` theo đó là bao nhiêu | Khi BR-04 có số đo, dự kiến T4 04/11 |
| 2 | **Môi trường giả lập production đặt ở đâu** khi rời Colab | Chu kỳ 02. Colab không phục vụ traffic thật được |

### 10.2. Một hệ quả của quyết định 2 cần nói thẳng

Brain có **một người** và đường găng là một chuỗi bốn việc nối tiếp, biên dự phòng 1 đến 3 ngày. Body có **ba người** cho bốn việc phần lớn chạy song song được.

Nghĩa là rủi ro trượt tập trung gần hết ở phía Brain, và nó không giảm được bằng cách thêm người vào giữa chu kỳ: `BR-02 → BR-03` là tri thức nối tiếp, người thứ hai vào lúc này sẽ làm chậm người thứ nhất trước khi giúp được.

Cách giảm rủi ro thật sự nằm ở chỗ khác: **cắt phạm vi sớm**. BR-06 đã cắt. Nếu M1 ngày 30/10 không đạt thì cắt tiếp BR-07, và nếu BR-04 trượt sang tuần sau thì BR-05 lùi sang chu kỳ 02 thay vì ép cả hai vào hai ngày cuối.

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
