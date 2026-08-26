# BÀN GIAO — Mảng vận tải của ANSER

**Viết ngày 25/08/2026.** Tài liệu này bàn giao toàn bộ phần **vận tải** (báo giá
cước, chọn nhà xe, đọc hoá đơn nhà xe, model trích xuất yêu cầu báo giá) cho
người tiếp quản, kèm danh sách việc để đưa nó thành sản phẩm bán được.

> **Đọc phần nào:** Phần A viết cho bất kỳ ai — nghiệp vụ, thị trường, vì sao có
> quyết định này. Phần B cho người viết mã. Phần C là những chỗ **chưa ai biết**,
> phải tự tìm. Phần D là danh sách việc.
>
> Nếu bạn không viết mã: đọc A → C → D, bỏ qua B.

---

# PHẦN A — Bối cảnh, cho mọi người đọc

## A.1 Sản phẩm này làm gì

Một **nhà môi giới vận tải** (forwarder) nhận yêu cầu từ chủ hàng, đi hỏi giá vài
nhà xe, cộng biên lợi nhuận rồi báo lại cho khách. Ba việc lặp đi lặp lại:

1. **Đọc yêu cầu** khách nhắn bằng lời thường → ra dữ liệu có cấu trúc
   (lấy hàng ở đâu, giao ở đâu, loại xe, loại hàng, ngày lấy).
2. **Tính giá báo khách** = giá nhà xe + điều chỉnh theo giá dầu + phụ phí + biên.
3. **Chọn nhà xe** trong số nhà xe đã chào giá, theo nhiều tiêu chí chứ không chỉ
   giá rẻ nhất.

Cộng thêm một việc phụ: **đọc hoá đơn nhà xe gửi về** (ảnh chụp) rồi đối chiếu
xem có tính đúng không.

## A.2 Vì sao mảng này bị hạ xuống nhánh phụ — và vì sao đó không phải thất bại

Khách hàng thí điểm số 1 (Hoàng Phát) nói thẳng ngày 13/08/2026:

> *"hiện tại công ty chú là **chuyên bán dầu**, chưa phải là công ty về vận tải"*

Toàn bộ kế hoạch cũ chặn ở một cánh cổng: **hiệu chỉnh công thức giá trên 15–20
báo giá lịch sử**. Khách không làm vận tải thì không có báo giá lịch sử nào, nên
cổng đó không bao giờ mở được. Trong khi đó phần **kế toán/sổ sách** — vốn không
nằm trong kế hoạch một dòng nào — lại chạy được trên dữ liệu thật và ra kết quả
khách kiểm tay được.

Nên đội gốc đổi hướng sang kế toán. **Mã vận tải không hỏng, không bị bỏ** — nó
chỉ chưa có ai để hiệu chỉnh. Giờ đã có khách vận tải thật đang chờ, nên nó được
tách ra giao cho người có thời gian đi tới cùng.

**Điều quan trọng nhất bạn thừa hưởng:** mã đã viết xong và có 82 test, nhưng
**chưa một con số nào được xác nhận bằng dữ liệu thật**. Bạn không tiếp quản một
sản phẩm đã chạy — bạn tiếp quản một bộ máy đã lắp mà chưa nổ.

## A.3 Thị trường — những gì tra được (25/08/2026)

**Cấu trúc giá cước.** Chi phí xăng dầu chiếm **35–40% tổng cước phí** đường bộ.
Con số này quan trọng: nó xác nhận tham số `fuel_sensitivity = 0.35` mặc định
trong mã không phải bịa. Nhưng 0.35 là *trung bình ngành* — tuyến ngắn nội thành
và tuyến dài Bắc–Nam có tỷ trọng khác nhau, và đó là thứ phải đo trên số thật.

**Giá dầu đổi mỗi 7 ngày.** Theo Nghị định 80/2023/NĐ-CP, giá bán lẻ xăng dầu
điều chỉnh **chiều thứ Năm hằng tuần**, khoảng **52 kỳ/năm** (rút từ 15 ngày
xuống 10 rồi xuống 7). Hệ quả trực tiếp cho sản phẩm: **một báo giá phát hành
thứ Hai có thể sai vào 15:00 thứ Năm.** Báo giá phải có hạn hiệu lực, và hệ thống
phải biết mình đang dùng giá dầu của kỳ nào.

**Chi phí chưa nằm trong bảng giá.** Các bảng giá công bố thường chưa gồm: phí
bảo hiểm, phí dừng đỗ, bốc xếp, chứng từ, chờ giờ. Đây chính là chỗ `Surcharge`
trong mã sinh ra để xử lý — và cũng là chỗ hay tranh cãi với khách nhất.

## A.4 Ai đang làm gì trên thị trường này

| Bên | Họ giải bài toán gì | Có đụng ANSER không |
|---|---|---|
| **Logivan** | Sàn ghép chủ hàng với **xe rỗng chiều về**. Hai ứng dụng: Chủ Hàng / Chủ Xe. Kinh tế chia sẻ. | Không — họ *ghép* xe, không *báo giá* thay nhà môi giới |
| **Abivin** | Tối ưu lộ trình (VRP) cho hàng trăm xe, hàng nghìn đơn, bằng thuật toán | Không — họ giải bài toán *đi đường nào*, không phải *báo bao nhiêu tiền* |

Cả hai đều quảng cáo tiết kiệm ~30% chi phí logistics.

**Chỗ trống ANSER đứng:** không bên nào làm **báo giá cho nhà môi giới** — tính
giá bán ra từ giá vốn nhà xe, có biên, có điều chỉnh nhiên liệu, có phụ phí, và
giải thích được vì sao ra con số đó. Đó là công việc hằng ngày của forwarder mà
hiện họ làm bằng Excel và trí nhớ.

Đây là điểm mạnh, nhưng cũng là cảnh báo: thị trường ngách hơn nhiều so với sàn
vận tải. Số khách tiềm năng ít hơn, nhưng mỗi khách gắn bó hơn.

## A.5 Quy định phải biết

| Văn bản | Nội dung | Ý nghĩa với sản phẩm |
|---|---|---|
| **NĐ 158/2024/NĐ-CP** | Phân loại các hình thức kinh doanh vận tải hàng hoá đường bộ | Xác định khách của bạn thuộc loại nào — điều kiện kinh doanh khác nhau |
| **Giấy vận tải** | Phải phát cho tài xế **trước khi xe chạy**. Giấy hoặc điện tử (khuyến khích điện tử). Tối thiểu phải có: tên đơn vị vận tải, biển số xe, tên chủ hàng, hành trình, số hợp đồng, loại hàng, khối lượng | **Đây là cơ hội sản phẩm rõ nhất.** Danh sách trường trên gần trùng với dữ liệu hệ thống đã có sau khi chốt báo giá — sinh giấy vận tải điện tử gần như miễn phí |
| **NĐ 70/2025/NĐ-CP** | Thời điểm lập hoá đơn điện tử và nội dung bắt buộc | Ảnh hưởng phần đối chiếu hoá đơn nhà xe |

> Ba văn bản này tra ngày 25/08/2026. **Kiểm lại trước khi dựa vào** — quy định
> vận tải đổi thường xuyên, và tài liệu này sẽ cũ đi.

---

# PHẦN B — Bàn giao kỹ thuật

## B.1 Bản đồ mã

Toàn bộ nằm ở repo Brain (`PCBoiz/ANSER_AI`), nhánh
`feat/workflow-format-and-deterministic-core`. Body (Next.js) **hầu như không có
gì** cho vận tải ngoài màn hình đọc tài liệu — nghĩa là **chưa có giao diện báo
giá nào cả**.

| File | Dòng | Làm gì | Tin được tới đâu |
|---|---|---|---|
| `src/core/pricing.py` | 162 | Tính giá báo khách từ giá nhà xe | Logic có test, **hệ số chưa hiệu chỉnh** |
| `src/core/carrier_selection.py` | 386 | Xếp hạng nhà xe theo 6 tiêu chí có trọng số | Thuật toán chạy đúng, **trọng số do ta tự đặt** |
| `src/core/calibration.py` | 603 | Chạy lại công thức trên báo giá lịch sử, đo sai lệch | Công cụ sẵn sàng, **chưa có dữ liệu để chạy** |
| `src/core/freight_invoice.py` | 169 | Đối chiếu hoá đơn nhà xe | **Chưa có hoá đơn thật nào** |
| `src/core/grounding.py` | 140 | Chặn model bịa số — mọi số ≥4 chữ số phải có trong ngữ cảnh | Chạy tốt, dùng chung cả kế toán |
| `src/core/schemas.py` | 96 | `QuoteExtraction`: origin, destination, vehicle_type, cargo_type, pickup_date, customer_name, customer_email | Ổn định |

**Test:** `test_pricing_and_tools.py` (16), `test_calibration.py` (36),
`test_freight_invoice.py` (20), `test_ocr_freight_route.py` (10) = **82 test**.

## B.2 Ba module lõi, chi tiết

### `pricing.compute_quote()`

```
giá khách =  giá nhà xe
           + điều chỉnh nhiên liệu   (theo chênh lệch giá dầu so với giá gốc)
           + phụ phí                  (cố định hoặc %)
           + biên lợi nhuận           (% trên CHI PHÍ ĐÃ HIỆU CHỈNH, có sàn tuyệt đối)
           → làm tròn lên bội số
```

`PricingRule` gồm: `base_margin_pct` (bắt buộc), `fuel_sensitivity` (mặc định
**0.35** — chú thích trong mã ghi *"tỷ trọng nhiên liệu trong chi phí"*, trùng
đúng con số 35–40% của thị trường ở mục A.3), `fuel_baseline_price`,
`min_margin_amount`, `surcharges[]`.

Trả về **hai khối**: `quote` (đưa khách) và `internal` (nội bộ, có biên). Tách
hai khối là cố ý — gửi nhầm khối `internal` cho khách là lộ biên lợi nhuận. Model
được phép diễn giải từ `internal` cho **chủ doanh nghiệp**, nhưng nội dung gửi
**khách cuối** chỉ được lấy từ `quote`.

> ⚠️ Chú thích trong mã ghi rõ: bảng chứa `PricingRule` (`pricing_rules`) là
> **bảng nhạy cảm nhất hệ thống**. Nó là biên lợi nhuận của khách. Rò rỉ bảng
> này ra ngoài là mất khách, không phải mất dữ liệu.

### `carrier_selection` — 6 tiêu chí

| Tiêu chí | Trọng số | Vì sao có mặt |
|---|---|---|
| `price` | 0,30 | giá chào cho tuyến này |
| `proximity` | 0,20 | bãi xe gần điểm lấy hàng → ít chạy rỗng, dễ điều xe gấp |
| `credit` | 0,20 | số ngày công nợ → ảnh hưởng thẳng dòng tiền |
| `reliability` | 0,15 | tỷ lệ giao đúng hẹn, tính từ lịch sử |
| `discount` | 0,10 | % ưu đãi thường xuyên |
| `tenure` | 0,05 | số năm hợp tác |

Ngưỡng chuẩn hoá: `MAX_USEFUL_DISTANCE_KM = 60`, `CREDIT_DAYS = 45`,
`DISCOUNT_PCT = 20`, `TENURE_YEARS = 10`.

**Mọi con số trong hai bảng trên là do đội gốc đặt ra, không ai xác nhận.** Kết
quả trả về có `breakdown` truy vết từng tiêu chí — dùng nó để ngồi với khách và
hỏi "chỗ này chấm thế đúng chưa".

### `calibration.replay_pricing()`

Đây là **cánh cổng chưa bao giờ mở**. Đưa vào danh sách `HistoricalQuote`:

```python
HistoricalQuote(
    quote_id, carrier_cost, actual_price,   # actual_price = giá khách THẬT SỰ thu
    date, route, vehicle_type,
    fuel_price,                              # giá dầu ngày báo giá
    surcharges, note,
)
```

Nó chạy lại công thức trên từng dòng, tính **MAPE** (sai lệch phần trăm trung
bình) và phân vị sai lệch. Có MAPE rồi mới biết công thức đáng tin tới đâu.

**Không có 15–20 dòng này thì mọi thứ khác chỉ là giả định.**

## B.3 Model và đường huấn luyện

**Kết luận đã đo, đừng đo lại từ đầu.** Hai phiên Colab đầy đủ (15/08/2026), so
theo cặp bằng McNemar:

| Nhánh | Model gốc | Bản fine-tune | Hỏng | Sửa | p |
|---|---|---|---|---|---|
| **extraction** *(chính là việc của vận tải)* | 0,0% | **65,3%** | 0 | 64 | ~0 |
| n8n | 50,0% | 67,6% | 6 | 12 | 0,2379 |
| narration | 85,2% | 44,4% | 11 | 0 | 0,0010 |
| agentic | 52,6% | 15,8% | 8 | 1 | 0,0391 |

**Đọc kỹ dòng đầu.** Model gốc **không làm được một câu nào** — nó bỏ trống
`origin` 80/98 lần. Bản fine-tune sửa 64 câu, làm hỏng 0. Đây là kết quả mạnh
nhất cả bộ, và nó **nằm đúng ở nhánh của bạn**.

Đội gốc kết luận "dùng model gốc" vì họ chuyển sang kế toán, nơi extraction không
được dùng. **Với bạn thì ngược lại: bản fine-tune là thứ đáng dùng.**

Cần lấy về:
- Model AWQ trên Drive: `ANSER_AI_Logistics/anser-v3-awq` (bản 01/08/2026)
- Notebook: `offline_training/ANSER_train_v3_colab.ipynb`
- Bộ sinh dữ liệu: `make_extraction_seeds.py`, `reverse_generate.py`
- Bộ đo: `benchmark_v3.py` + `providers.py` + `compare_runs.py`
- Runbook: `PHIEN_DO_COLAB.md`

**Lưu ý:** bản AWQ đo được là bản 01/08, **train trên dữ liệu cũ hơn** tập 1.482
mẫu sinh ngày 15/08. Train lại nhiều khả năng còn hơn nữa.

## B.4 Nguyên tắc kiến trúc — giữ nguyên, đừng thương lượng

Bốn nguyên tắc này là thứ làm sản phẩm đáng tin. Bỏ cái nào cũng được, nhưng
biết mình đang bỏ gì:

**P1 — Số tài chính ra từ mã tất định, không từ model.** Model được làm đúng hai
việc: đọc lời người dùng thành cấu trúc, và diễn giải kết quả thành câu. Nó
**không** được tính tiền. Đã có sự cố thật (23/08/2026): model tự nhẩm
`5.000.000 + 500.000` rồi so trong đầu — và ra **đúng**. Đó mới là chỗ nguy, vì
lần sau sai cũng không có gì báo.

**P2 — Dữ liệu khách không rời khỏi chỗ nó cần ở.** File tải lên xử lý trong bộ
nhớ, không ghi ra đĩa.

**P4 — Một nguồn sự thật.** Cùng một con số không được khai ở hai chỗ. Đã dính
lỗi này ba lần: `API_TOKEN` vs `API_AUTH_TOKEN` (Brain mở toang), trần token
production ≠ trần benchmark (số đo đẹp hơn thực tế), `max_model_len` khai ba nơi
ba số.

**"Chưa biết" khác "bằng 0".** `None` là chưa biết, `0` là biết và bằng không.
Gộp hai thứ này là cách tạo ra báo cáo sai mà nghe rất xuôi tai.

## B.5 Tách repo — mang gì theo

Bạn tách repo riêng. Ngoài 6 file lõi, **phải mang theo lớp nền** — nếu không
mã vận tải không chạy:

| Mang theo | Vì sao |
|---|---|
| `src/core/findings.py` | Hình dạng chung của mọi phát hiện. Giao diện chỉ cần một component để hiện |
| `src/core/tool_planner.py` | Bảng luật chọn tool tất định |
| `src/agents/agentic.py` | Vòng suy nghĩ–hành động, kèm `arguments_schema` và `bat_buoc_tool` |
| `src/core/grounding.py` | Chặn bịa số |
| `src/api/` | Khung FastAPI, **kèm `auth_guard`** — xem cảnh báo dưới |
| `tests/` hạ tầng | 82 test vận tải + khung chung |
| `AGENTS.md` | Nguyên tắc P1–P4 viết đầy đủ |

> ⚠️ **Bắt buộc mang theo bản vá xác thực ngày 15/08/2026.** Trước đó
> `GET /tools` và `GET /api/v1/task/{id}` **không kiểm token** — cái sau trả về
> câu trả lời đầy đủ của AI (tên khách, mã số thuế, số tiền). Bản vá đưa
> `auth_guard` thành dependency cấp router để endpoint mới không thể quên, kèm
> `tests/test_auth_bao_phu.py` hỏi toàn bộ bảng route. Chép mã cũ mà bỏ bản vá
> này là dựng lại đúng lỗ hổng đó.

**Đánh đổi của việc tách repo:** sạch sẽ, nhưng từ hôm tách hai bản trôi xa nhau.
Sửa lỗi ở lớp nền phải chép tay sang. Cân nhắc định kỳ đồng bộ lớp nền.

---

# PHẦN C — Những gì chưa ai biết, bạn phải tự tìm

Đây là phần quan trọng nhất tài liệu này. Mỗi mục là một câu hỏi **chưa có câu
trả lời**, kèm cách đi tìm.

## C.1 Công thức giá có đúng không? *(chặn mọi thứ khác)*

`pricing.py` chạy đúng như đã viết. Nhưng **chưa ai kiểm nó có ra giá giống giá
người thật báo hay không.**

**Cách trả lời:** xin khách 15–20 báo giá đã chốt trong 6 tháng gần đây, mỗi dòng
cần: giá nhà xe báo, giá thật sự thu của khách, ngày, tuyến, loại xe, giá dầu hôm
đó, phụ phí. Đổ vào `calibration.replay_pricing()`. **MAPE dưới 10%** là công
thức dùng được; trên 25% là mô hình sai bản chất, không phải sai tham số.

**Cạm bẫy:** hỏi "giá báo khách" sẽ nhận về giá *dự tính*. Phải hỏi **giá thật sự
thu** — hai con số này khác nhau, và chênh lệch giữa chúng chính là thứ cần học.

## C.2 Khách tính cước theo đơn vị nào?

Mã hiện giả định giá theo **chuyến**. Nhưng thực tế Việt Nam có ít nhất bốn cách:
theo chuyến, theo tấn, theo km, theo khối (m³). Có nhà xe tính theo tấn cho hàng
nặng và theo khối cho hàng cồng kềnh, lấy giá nào cao hơn.

**Cách trả lời:** ngồi xem khách báo giá 5 lần liên tiếp. Đừng hỏi, hãy nhìn.

## C.3 Sáu trọng số chọn nhà xe có phản ánh cách khách nghĩ không?

`price 0,30 / proximity 0,20 / credit 0,20 / reliability 0,15 / discount 0,10 /
tenure 0,05` — con số do đội gốc đặt.

**Cách trả lời:** lấy 10 tình huống khách **đã chọn nhà xe trong quá khứ**, chạy
`carrier_selection` trên cùng dữ liệu, xem nó chọn trùng bao nhiêu ca.
`calibration.py` đã có sẵn `CarrierChoiceCase` cho đúng việc này.

Nếu trùng dưới 6/10, đừng vội chỉnh trọng số — hỏi khách vì sao họ chọn. Rất có
thể có **một tiêu chí thứ bảy** không nằm trong mã (quan hệ cá nhân, nhà xe có
loại thùng phù hợp, nhà xe chịu ứng trước).

## C.4 Giá dầu lấy ở đâu, cập nhật thế nào?

Mã nhận `fuel_baseline_price` và `current_fuel_price` như tham số — **không có
đường nạp giá dầu tự động**. Mà giá đổi mỗi thứ Năm.

**Cách trả lời:** nguồn công bố là Petrolimex và cổng Bộ Công Thương
(moit.gov.vn). Quyết định: nạp tự động hằng tuần, hay để người dùng nhập tay?
Tự động thì phải xử lý chuyện nguồn đổi giao diện. Nhập tay thì phải nhắc.

> **Đừng đưa giá dầu vào kho tri thức RAG.** Đội gốc đã ghi rõ lý do: giá đổi
> hằng tuần, embedding cũ nằm lại và vẫn bị truy hồi ra. Giá dầu là dữ liệu
> realtime, phải đi đường tra cứu tất định.

## C.5 Đọc hoá đơn nhà xe chính xác tới đâu?

`freight_invoice.py` + đường OCR đã viết xong. **Chưa có một hoá đơn thật nào để
đo.** Không biết model đọc đúng bao nhiêu phần trăm số tiền trên tờ giấy nhàu.

**Cách trả lời:** xin 20–30 ảnh hoá đơn nhà xe thật, gõ tay đáp án đúng, rồi đo.
Trước khi đo thì **không được nói với khách rằng tính năng này dùng được**.

## C.6 Model trích xuất có chịu được cách khách nhắn thật không?

65,3% đo trên dữ liệu **sinh ra**, không phải tin nhắn thật. Người thật viết tắt,
sai chính tả, nhắn nhiều tin rời rạc, gửi ảnh kèm chữ.

**Cách trả lời:** xin 50–100 tin nhắn thật (Zalo là chủ yếu), gõ tay đáp án, đo
lại. Con số sẽ thấp hơn 65,3%, và khoảng cách đó chính là việc phải làm.

## C.7 Bảng luật chọn tool đang 40% trên bộ eval vận tải

Chín ca hỏng đều là `quote` và `carrier_selection`:

```
AG0001: kế hoạch ['report'], đúng phải có 'quote'
AG0003: không luật nào khớp (cần 'carrier_selection')
```

Đây là **mã tất định** (`tool_planner.py`), sai thì sửa bằng regex chứ không phải
huấn luyện lại. Đội gốc để nguyên vì họ không dùng nhánh này nữa. **Với bạn thì
đây là việc phải làm sớm** — 40% nghĩa là cứ 5 câu hỏi báo giá thì 3 câu đi nhầm
đường.

## C.8 Chưa có giao diện nào cho vận tải

Body có màn hình Dòng tiền, Cảnh báo sổ sách, Sản phẩm, Kho, Bán hàng — **không
có màn hình báo giá**. Toàn bộ mã vận tải hiện chỉ gọi được qua API.

**Cách trả lời:** đây không phải câu hỏi nghiên cứu, đây là việc phải làm. Xem
D.4.

---

# PHẦN D — Danh sách việc

Xếp theo nguyên tắc đội gốc dùng và nó đã tự chứng minh nhiều lần:
**việc nào sớm phát hiện được sai lầm đắt tiền nhất thì làm trước.**

Vì **đã có khách thật đang chờ**, ba việc đầu đều là đi lấy dữ liệu của họ —
không phải viết mã.

## Nhóm 1 — Mở cánh cổng chưa bao giờ mở *(làm trước hết)*

| # | Việc | Cần gì | Xong thì biết được |
|---|---|---|---|
| **1** | **Xin 15–20 báo giá đã chốt** rồi chạy `calibration.replay_pricing()` | Một buổi ngồi với khách | Công thức giá sai bao nhiêu %. **Đây là số quyết định mọi thứ sau** |
| **2** | **Xin 10 tình huống chọn nhà xe** trong quá khứ, chạy `CarrierChoiceCase` | Cùng buổi trên | 6 trọng số có đúng cách khách nghĩ không |
| **3** | **Xem khách báo giá 5 lần**, ghi lại đơn vị tính | Nửa ngày quan sát | Cước theo chuyến / tấn / km / khối |

> Ba việc này **không viết một dòng mã nào** và chúng quyết định toàn bộ phần
> còn lại. Làm ngược thứ tự là nguy cơ viết ba tháng cho một công thức sai bản chất.

## Nhóm 2 — Làm cho dùng được hằng ngày

| # | Việc | Ghi chú |
|---|---|---|
| **4** | **Dựng màn hình báo giá** ở Body | Hiện chưa có gì. Nhập yêu cầu → ra giá → có nút gửi khách. Tách rõ khối `quote` và `internal` |
| **5** | **Nối giá dầu tự động** | Petrolimex / moit.gov.vn, cập nhật chiều thứ Năm. Báo giá phải có **hạn hiệu lực** |
| **6** | **Sửa bảng luật chọn tool** từ 40% lên | Regex trong `tool_planner.py`. Xem C.7 |
| **7** | **Sinh giấy vận tải điện tử** | Theo NĐ 158/2024. Dữ liệu gần như đã có sau khi chốt báo giá — xem A.5. **Đây có thể là tính năng bán được nhất** |

## Nhóm 3 — Đo những thứ chưa ai đo

| # | Việc | Ghi chú |
|---|---|---|
| **8** | **Đo trích xuất trên tin nhắn thật** | 50–100 tin Zalo, gõ tay đáp án. Xem C.6 |
| **9** | **Đo đọc hoá đơn nhà xe** | 20–30 ảnh thật. Xem C.5. Chưa đo thì đừng bán |
| **10** | **Train lại model** trên tập 1.482 mẫu | Bản đang có là 01/08, train trên dữ liệu cũ hơn. Chỉ làm **sau** khi việc 8 cho biết khoảng cách thật |

## Nhóm 4 — Nền móng, làm song song được

| # | Việc | Ghi chú |
|---|---|---|
| **11** | **Tách repo**, mang đủ lớp nền | Xem B.5. **Nhớ bản vá xác thực 15/08** |
| **12** | **Dựng bộ eval vận tải** như đội gốc làm cho kế toán | Gieo lỗi vào dữ liệu thật, đo bắt được / báo oan. Không có bộ đo thì không biết hôm nay có khác hôm qua không |
| **13** | **Thêm `.gitattributes`** | Kết dòng Windows↔Linux đang gây xung đột giả hàng trăm dòng mỗi lần gộp |

## Nếu chỉ làm được ba việc

1. **Việc 1** — xin báo giá lịch sử, chạy hiệu chỉnh. Không có nó thì mọi thứ
   khác xây trên cát.
2. **Việc 4** — dựng màn hình báo giá. Không có nó thì khách không chạm được vào
   sản phẩm.
3. **Việc 7** — giấy vận tải điện tử. Quy định bắt buộc, dữ liệu đã có sẵn, và
   không đối thủ nào trong bảng A.4 làm.

---

## Phụ lục — Bài học đắt nhất của đội gốc

Ba lỗi nghiêm trọng nhất tìm được trong hai tháng đều cùng một hình dạng:
**hai thứ đúng riêng lẻ, sai khi ghép, và không có gì phát ra tín hiệu.**

- `docker-compose.yml` đặt `API_TOKEN`, mã đọc `API_AUTH_TOKEN` → Brain triển
  khai theo README **không kiểm token nào** mà vẫn mở ra Internet
- `arguments_schema()` lọc trường khỏi lược đồ nhưng không đóng object → lớp
  phòng thủ nó mô tả **chưa từng tồn tại**
- Trần token production chặt hơn trần benchmark → mọi tỷ lệ đo được **đẹp hơn**
  thứ khách nhận

Không test đơn vị nào bắt được cả ba. Cả ba lộ ra khi **chạy thật qua HTTP** hoặc
khi **đọc tay đầu ra**.

Bài học cụ thể: đừng tin một lớp phòng thủ chỉ vì đã viết nó. Viết một phép thử
chứng minh nó **thi hành**, không chỉ **tồn tại**.
