# BÁO CÁO BR-05 — Phiên đo bản fine-tune qua đường server, bảng phân loại lỗi

**Ngày đo:** Thứ Ba 27/10/2026 · **Phân tích:** 28/10/2026 · **Người làm:** Thành · **Đặc tả:** [SRS_CHU_KY_01.md §BR-05](SRS_CHU_KY_01.md)
**Mục đích (chủ dự án chốt 24/10):** *chẩn đoán* — xem bản fine-tune hổng chỗ nào để biết vòng cải tiến sau sửa gì. Không phải chấm điểm.

| | |
|---|---|
| Model | `anser-v3-awq`, phục vụ bằng `vllm serve` 0.11.2 trên Colab L4 (cấu hình đề xuất ở BR-04: `max_model_len` 32768, `gpu_memory_utilization` 0.55) |
| Đường đo | `--model 'openai:http://127.0.0.1:8001/v1#anser-v3'` — payload dựng bằng **chính `ChatRequest` của production** (`8042584`) |
| Bộ đề | `ANSER_AI_Logistics/generated` của phiên 15/08: extraction 98, n8n 34, narration 27, agentic 19 |
| Mã bộ đo | `c57e97b` (bốn nhánh đầu) và `5501779` (agentic, sau khi sửa khung đo — mục 4) |
| Dữ liệu thô | `br05_tuned.json`, `br05_tho.jsonl`, `br05_agentic.json`, `br05_agentic_tho.jsonl` — Drive `ANSER_AI_Logistics/br05_2710_0435/` |

---

## 1. Tóm tắt

1. **Ba dòng chốt chặn đều đạt** — `[chốt chặn] ràng buộc JSON: ✓ CHẠY`, lược đồ agentic dựng được 8/8 tool, trường bị cấm không sinh ra được. Treo #2 của TIEN_TRINH **đóng**.
2. **Lỗi lớn nhất của nhánh agentic không nằm ở model.** Bảng luật chọn tool (`tool_planner.py`) đẩy **6/6** câu cần `quote` sang `report`; grammar chỉ cho một tên tool, nên model — dù `thought` ghi đúng *"cần gọi công cụ 'quote'"* — bị ép gọi `report`. Nguyên nhân: luật `report` bắt chữ trần `lợi nhuận`, và thiết kế **thiếu đường** cho ý định "tính giá bán từ giá nhà xe đã có" (**mã**). Không sửa bằng train lại. **Đã sửa 28/10** bằng cách tách "báo giá" thành ba ý định — bảng luật 40% → 100%, điền tham số 60% → 100% (§6b).
3. **Extraction hổng ở kỷ luật null.** 63 trường bị điền khi đáng lẽ để trống; **~53 là lỗi model** (xưng hô thành tên, mặc định `dau_keo`/`Hà Nội`, chép điểm đến sang điểm đi), **~10 là nhãn bộ đề sai**. Thêm ~21 ca **tính sai ngày tương đối** — LLM đang làm phép tính ngày, trái R1.
4. **Narration có một ca bịa số nghiêm trọng:** `12.709.000` thành **`127.090.000 đồng`** (gấp 10) trong email báo giá cho khách. Và 12/27 câu cắt cụt vì viết quá dài, 2 trong đó lặp vòng.
5. **Bộ đo có bốn chỗ sai đã sửa trong phiên** (mục 4) và ba chỗ còn lệch (mục 5) — con số tổng ở mục 2 phải đọc kèm hai mục đó.

---

## 2. Điểm số, để đối chiếu — KHÔNG phải đầu ra chính

| Nhánh | BR-05 (27/10) | Phiên 15/08 | Ghi chú đọc số |
|---|---|---|---|
| extraction — sẵn sàng báo giá | **65,3%** [55,5–74,0] | 65,3% | ~10 ca trượt do nhãn sai (mục 3.2) → con số thật cao hơn |
| extraction — TB các trường | 84,8% | — | |
| n8n — hợp lệ | **85,3%** (29/34) [69,9–93,6] | 67,6% | khoảng tin cậy vắt qua ngưỡng 90% — chưa kết luận được |
| narration — đạt | **48%**; trên phần đo được **87%** | 44,4% | 12/27 cắt cụt; một ca "bịa số" là bộ chấm báo nhầm |
| bảng luật chọn tool (mã) | **40%** (6/15) | — | mã tất định, không có model |
| agentic — chịu gọi tool | **93,3%** | — | đo sau khi sửa khung đo (mục 4.3) |
| agentic — biết hỏi lại | 25% (n=4) | — | mẫu quá nhỏ |
| agentic — điền tham số | 60% (n=5) | 15,8% (chỉ số khác) | mẫu quá nhỏ; không so trực tiếp với 15/08 |

So 15/08 chỉ để định hướng: bộ đo đã đổi nhiều chỗ (payload, grammar, cách chấm agentic). So theo cặp với model gốc (yêu cầu 9, mức NÊN) **chưa làm**.

---

## 3. Bảng phân loại lỗi (yêu cầu 5–7)

Nguyên nhân quy về một trong ba: **dữ liệu** (huấn luyện hoặc bộ đề), **lược đồ/prompt**, **mã** (mã production hoặc mã khung đo). Số ca đếm trên nguyên văn đầu ra (`br05_tho.jsonl`) đối chiếu nhãn bộ đề; số đếm của script phân tích khớp đúng từng con số với log bộ đo.

### 3.1. agentic (n=19)

| Loại lỗi | Số ca | Ví dụ nguyên văn | Nguyên nhân |
|---|---|---|---|
| **Bảng luật chọn sai tool**, model bị ép gọi `report` | **6** (mọi câu cần `quote`) | AG0014 — `"thought": "…Tôi sẽ gọi công cụ 'quote'…"`, `"tool": "report"` | **mã** — luật `report` bắt chữ trần `lợi nhuận`, và thiết kế thiếu đường cho ý định "tính giá bán từ giá nhà xe". **Đã sửa 28/10, xem §6b** |
| Luật `carrier_selection` không khớp câu chào giá; model tự chọn sai tool hoặc hỏi lại | 3 | AG0003 — đáp án `carrier_selection`, model gọi `quote` | **mã** (luật chỉ bắt "nhà xe nào", "so sánh nhà xe"…) + model |
| Bịa tên trường trong `pricing_rule` | 2 | AG0003 — `"pricing_rule": {"discount_rate": 8, "credit_days": 30}` → 3 lỗi `QuoteRequest` | **lược đồ** — `arguments_schema` chỉ đóng tầng ngoài, `$defs` để mở |
| Điền `0` cho giá dầu chưa biết | 2 | AG0003, AG0013 — `"current_fuel_price": 0` | **lược đồ/prompt** — giá dầu phải do hệ thống cấp (AGENTS §3.1c); "chưa biết" ≠ 0 |
| Thiếu dữ kiện mà vẫn gọi tool thay vì hỏi lại | 3 | AG0010 — hỏi về biên lợi nhuận và giá dầu, luật bắt `report` vì chữ "lợi nhuận", model gọi `report` thay vì `hoi_lai` | AG0010, AG0018: **mã** (kế hoạch sai) + model; AG0009: **model** (kế hoạch `report` đúng, lẽ ra phải hỏi lại) |

`thought` **không đáng tin**: nhiều ca ghi *"không cần gọi công cụ"* rồi vẫn gọi. Không dùng làm bằng chứng.

### 3.2. extraction (n=98)

| Loại lỗi | Số ca | Ví dụ nguyên văn | Nguyên nhân |
|---|---|---|---|
| **Xưng hô thành tên khách** | 16 | EX0063 *"Chú ơi báo giá giúp tôi…"* → `customer_name: "chú"`; EX0501 *"Admin oi…"* → `"admin"`; FU0040 *"A Huy oi"* (người nhận tin) → `"anh Huy"` | **dữ liệu huấn luyện** — nhãn gộp xưng hô với tên (*"anh Tuấn"*, *"chị Mai"* đứng đầu tập train) |
| **Mặc định loại xe** khi câu không nhắc | 13 | EX0228 *"…từ Đông Anh lên Việt Trì, hàng linh kiện điện tử…"* → `vehicle_type: "dau_keo"` (11/13 là `dau_keo`) | **dữ liệu huấn luyện** — kỷ luật null yếu. Tập train có 174/600 mẫu để trống loại xe và 97/600 mẫu `dau_keo`, nên model đã thấy cả hai; vì sao nó nghiêng hẳn về `dau_keo` khi câu không nhắc xe thì chưa rõ |
| **Điểm đi bịa hoặc chép từ điểm đến** | 14 | EX0098 *"giao tại Đà Nẵng"* → `origin: "Đà Nẵng"`; EX0664 → `"Hải An"` (từ tên miền email `haianexpress`); 8 ca mặc định `"Hà Nội"` | **dữ liệu huấn luyện** |
| Động từ hoặc xe thành loại hàng | 7 | EX0054 → `cargo_type: "lấy hàng"`; EX0551 → `"xe cont"` | **dữ liệu huấn luyện** |
| **Tính sai ngày tương đối** | 21 | EX0577 *"ngày kia"*, hôm nay 25/02 → `2026-02-26` (đúng `02-27`); EX0248 *"thứ 7 tuần sau"*, hôm nay 01/10 → `10-17` (đúng `10-10`) | **lược đồ/prompt** — bắt LLM tự cộng ngày là trái R1. Bóc cụm ngày bằng mã tất định, model chỉ trích cụm từ |
| Câu nối tiếp lấy sai xe/điểm đến | ~10 | FU0063 nhãn `1.5T` → model `5T` | dữ liệu huấn luyện (hội thoại nhiều lượt) |
| **Nhãn bộ đề sai** — câu có nhắc mà nhãn ghi `null` | **10** | EX0034 *"…ship **về HP**"* nhãn `destination: null`; EX0063 *"giao ngày **t3**"* nhãn `pickup_date: null` (model trả `09-08`, đúng) | **dữ liệu bộ đề** — DeepSeek sinh ngược để lộ trường phải giấu |
| Chấm quá chặt: cùng nghĩa khác chữ | ~6 | `"Sân bay Nội Bài"` vs `"Nội Bài"`; `"gạo"` vs `"gạo đóng bao"` | **mã khung đo** — so chuỗi tuyệt đối sau bỏ dấu |

### 3.3. narration (n=27)

| Loại lỗi | Số ca | Ví dụ nguyên văn | Nguyên nhân |
|---|---|---|---|
| Viết quá dài, cắt cụt ở trần 2048 token | 10 | NA0026 — 13.877 ký tự; nhóm `report` 0% vì cắt hết | **dữ liệu huấn luyện / prompt** (độ dài đầu ra) |
| Lặp vòng tới trần | 2 | NA0010 — *"…mãi mãi mãi mãi…"* (một cụm lặp 297 lần), dù đã phạt lặp 1,25 | dữ liệu huấn luyện |
| **Bịa số** | 1 | NA0006 — xem 3.3.1 | dữ liệu huấn luyện |
| "Bịa số" do bộ chấm báo nhầm | 1 | NA0001 — ngữ cảnh `10250000`, model viết *"10.25 triệu đồng"* | **mã khung đo** — đổi cách viết số bị coi là bịa |
| **Model tự tính** mà bộ chấm bỏ sót | ≥1 | NA0001 — *"…một khoản tiền lớn **gấp khoảng 1.2 lần** so với…"* | **mã khung đo** (chỉ soi số ≥ 4 chữ số) — vi phạm R1 thật |

#### 3.3.1. Soi riêng bịa số (yêu cầu 6)

| Ca | Model viết | Đúng lẽ ra | Ngữ cảnh | Mức nghiêm trọng |
|---|---|---|---|---|
| NA0006 `[customer]` | **127.090.000 đồng** | **12.709.000 đồng** | email báo giá gửi khách | **Cao** — sai gấp 10, gửi thẳng cho khách, giọng chắc chắn |
| NA0001 `[carrier]` | *"gấp khoảng 1.2 lần"* | không được có — tỷ lệ phải ra từ tool | so sánh hai nhà xe | Trung bình — số tự tính, gần đúng (10,25 / 8,6 ≈ 1,19) |

Cả hai là lỗi R1. Ca NA0006 cho thấy: kể cả khi mọi con số có sẵn trong ngữ cảnh, model vẫn **chép sai** — chốt neo số liệu (`guard_answer`) phải chạy trên narration ở production, không chỉ ở bộ đo.

### 3.4. n8n (n=34)

| Loại lỗi | Số ca | Ví dụ nguyên văn | Nguyên nhân |
|---|---|---|---|
| `connections` trỏ tới node không tồn tại | 4 | `connections["Gửi chủ doanh nghiệp"]` trỏ tới `"noOp"` | **lược đồ** — grammar không ép được tham chiếu chéo giữa tên node và `connections` |
| Trùng tên node | 1 | hai node cùng tên `"Trả kết quả"` | **lược đồ** (như trên) |

`validate_workflow()` bắt được cả 5 — production không gửi workflow hỏng cho khách, nhưng người dùng nhận lỗi thay vì workflow.

### 3.5. bảng luật chọn tool (mã, n=15 chấm được)

| Loại lỗi | Số ca | Ví dụ | Nguyên nhân |
|---|---|---|---|
| Câu báo giá vận tải bị bắt thành `report` | 6 | AG0001 *"Nhà xe vừa chào 12.500.000 đồng…, biên lợi nhuận họ tính 8%"* → `["report"]` | **mã** — luật `report` có chữ trần `lợi nhuận` ([`tool_planner.py:157`](src/core/tool_planner.py#L157)). Bảng luật không có luật `quote`, vì thiết kế cũ dồn mọi câu "báo giá" về LOGISTICS → n8n — kể cả câu đã có sẵn giá nhà xe. **Đã sửa 28/10 (§6b)** |
| Luật `carrier_selection` không khớp | 3 | AG0002 *"…Đại An chào 9.400.000 đồng chiết khấu 5%…"* | **mã** — luật chỉ bắt "nhà xe nào", "chọn/so sánh nhà xe"; câu liệt kê nhiều lời chào giá không khớp |

---

## 4. Lỗi khung đo tìm ra và đã sửa trong phiên

| # | Lỗi | Hậu quả nếu không sửa | Sửa |
|---|---|---|---|
| 4.1 | `payload_openai` tự dựng payload, thiếu `enable_thinking=False` và `repetition_penalty` | narration đo ở thinking BẬT, phạt lặp 1,0 — khác thứ khách nhận | `8042584` — dùng chính `ChatRequest` |
| 4.2 | Một request quá giờ làm đổ cả phiên; JSON chỉ ghi ở cuối; không lưu nguyên văn | mất sạch kết quả bốn nhánh; không có ví dụ cho bảng này | `c57e97b` — `timeout` thành lý do dừng riêng, ghi JSON sau mỗi nhánh, `--tho` |
| 4.3 | Nhánh agentic để ngỏ `answer`, trong khi production khoá (`bat_buoc_tool=True`) | "không gọi tool dù đủ dữ kiện" 6/19 ca — đo cái cửa khách không đi qua. Sau sửa: chịu gọi tool 60% → **93,3%** | `5501779` |
| 4.4 | `ChatRequest` cảnh báo hạ `repetition_penalty` cho một con số không ai đặt | log ngập hơn trăm dòng, production in ở mọi bước agentic | `c57e97b` |

## 5. Khung đo còn lệch — chưa sửa

1. **Bộ chấm agentic không đo việc chọn tool.** AG0001 và AG0004 được chấm *đạt* dù gọi `report` cho câu cần `quote`. Điểm agentic **đẹp hơn** thực tế.
2. **Bộ chấm narration chỉ soi số ≥ 4 chữ số** — bỏ sót phép tính tỷ lệ của model (NA0001), và **báo nhầm** khi model đổi cách viết số (`10250000` → "10.25 triệu").
3. **~10 nhãn sai trong `eval_extraction.jsonl`** và chấm chuỗi tuyệt đối — sẵn sàng báo giá 65,3% là cận dưới.

---

## 6. Gợi ý cho vòng cải tiến sau — xếp theo rẻ tới đắt

Đây là **đầu vào** cho quyết định, không phải quyết định (SRS BR-05: "Không huấn luyện lại model trong chu kỳ này").

| Việc | Loại | Kéo lên chỗ nào | Công ước lượng |
|---|---|---|---|
| Chốt câu báo giá đi nhánh nào (LOGISTICS/n8n hay agentic `quote`), rồi sửa theo: bỏ chữ trần `lợi nhuận` khỏi luật `report`, mở rộng luật `carrier_selection`, và sửa `eval_agent.jsonl` cho khớp thiết kế | mã + bộ đề | agentic, bảng luật | ~nửa ngày, sau khi chốt |
| Bóc ngày tương đối bằng mã tất định; model chỉ trích cụm từ ("ngày kia") | lược đồ + mã | extraction `pickup_date` (~21 ca) | ~1 ngày |
| Đóng `$defs` của `pricing_rule`; `current_fuel_price` do hệ thống cấp | lược đồ | agentic điền tham số | ~nửa ngày |
| Chốt neo số liệu (`guard_answer`) trên narration ở production | mã | bịa số (NA0006) | kiểm xem đã chạy chưa |
| Sửa bộ chấm (mục 5) + sửa 10 nhãn bộ đề | mã khung đo + dữ liệu bộ đề | độ tin của mọi phiên đo sau | ~1 ngày |
| Dữ liệu huấn luyện: tách xưng hô khỏi tên; thêm ca để trống trường; giới hạn độ dài narration | dữ liệu huấn luyện | extraction null (~53 ca), narration cắt cụt | thuộc quyết định huấn luyện lại |

**Kết luận chẩn đoán:** phần lớn lỗi *rẻ nhất để sửa* nằm ở **mã và lược đồ**, không ở model. Nên sửa các dòng "mã" và "lược đồ" trước rồi đo lại, *sau đó* mới quyết có huấn luyện lại không — đúng bài học ba lần trước của dự án: con số xấu đến từ mã trước khi đến từ model.

---

## 6b. Đo lại sau khi tách "báo giá" thành ba ý định (28/10/2026)

Chủ dự án chốt giữ cả hai đường, tách theo ý định bằng luật từ khoá (`b4091f7`): khách xin báo giá → LOGISTICS/n8n; **tính giá bán từ giá nhà xe + biên** → agentic `quote`; **so ≥ 2 lời chào giá** → agentic `carrier_selection`. Luật `report` và luật REPORT của router thôi bắt "**biên** lợi nhuận". Đo lại riêng bảng luật và agentic (`4911302`; ba nhánh kia không đổi mã):

| Chỉ số | BR-05 (27/10) | Sau tách ý định |
|---|---|---|
| Bảng luật chọn đúng tool | 40% (6/15) | **100% (15/15)** |
| Agentic — chịu gọi tool khi đủ dữ kiện | 93,3% | **100%** |
| Agentic — điền tham số đúng kiểu | 60% (n=5) | **100% (n=9)** |
| Agentic — biết hỏi lại khi thiếu dữ kiện | 25% (n=4) | 25% (n=4) |

Đọc số:

- **Luật được viết SAU khi thấy bộ đề**, nên 15/15 là cận trên. Đối trọng: 13 câu viết mới không lấy từ bộ đề (gồm ca không được khớp, câu không dấu) đều đúng, và 249 chuỗi trong 4 file test chỉ đổi kế hoạch ở 1 câu chú thích — đúng hướng.
- **Tham số `quote` đúng kiểu ở cả 6 câu** khi được đưa đúng tool. Hai ca bịa `pricing_rule.discount_rate` ở §3.1 phần lớn là hệ quả của việc bị đưa sai tool.
- **"Biết hỏi lại" 25% không phải lỗi model ở đường production.** AG0010, AG0018 (có biên, chưa có giá nhà xe) cố ý không có kế hoạch — và production chỉ vào vòng agentic khi CÓ kế hoạch, nên hai câu này không tới đó. Bộ đo vẫn cho model tự chọn giữa 8 tool; nó chọn `quote`, tức sẽ phải bịa giá nhà xe — đáng ghi nhận, nhưng đó là đường không tồn tại. AG0009 gọi `report` khi "chưa có số liệu": ở production `report` lấy số liệu hệ thống và tự báo thiếu, nên hành vi chấp nhận được; nhãn "phải hỏi lại" có thể tranh cãi.
- **Khung đo còn lệch thêm một chỗ:** câu không có kế hoạch được chấm qua vòng agentic với lược đồ tự do, trong khi production đưa chúng sang nhánh router. Sửa: bộ đo bỏ qua (hoặc chấm riêng) các câu không có kế hoạch.
- **Khoảng trống còn mở:** `carrier_selection` định tuyến đúng nhưng vẫn lấy nhà xe/lời chào từ hệ thống (chưa có nguồn), không đọc lời chào trong câu — người dùng nhận câu hỏi lại danh sách nhà xe. Có test ghi nhận (`test_so_chao_gia_vao_carrier_selection_va_noi_ro_con_thieu_gi`). Bóc lời chào từ câu là việc riêng.

Dữ liệu thô: Drive `ANSER_AI_Logistics/br05b_*`.

---

## 7. Đối chiếu yêu cầu BR-05

| # | Yêu cầu | Trạng thái |
|---|---|---|
| 1 | Chạy `benchmark_v3.py` trên `anser-v3-awq` qua đường server | **Đạt** |
| 2 | Đọc ba dòng cảnh báo khung đo trước điểm số | **Đạt** — mục 1, 4, 5 |
| 3 | `smoke_test_guided()` báo ràng buộc đang thi hành | **Đạt** — `[chốt chặn] ràng buộc JSON: ✓ CHẠY` |
| 4 | Dùng chung hằng số trần token | **Đạt** — `tran_token()` import `MAX_*_TOKENS` của production |
| 5 | Bảng phân loại lỗi theo nhánh, số ca, ví dụ nguyên văn | **Đạt** — mục 3 |
| 6 | Soi riêng bịa số | **Đạt** — mục 3.3.1 |
| 7 | Quy mỗi loại về dữ liệu / lược đồ-prompt / mã khung đo | **Đạt** — mục 3 |
| 8 | Cập nhật TIEN_TRINH: treo #1, #2 | **Đạt** — treo #2 đóng; treo #1 *chưa đóng được* (agentic bị lỗi bảng luật che) |
| 9 | (NÊN) So cặp với model gốc | **Chưa làm** — tốn thêm ~30 phút GPU |
