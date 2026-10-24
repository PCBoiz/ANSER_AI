# SRS — Đặc tả yêu cầu phần mềm, chu kỳ 01

**Chu kỳ:** Thứ Hai 26/10/2026 → Thứ Sáu 06/11/2026 (10 ngày làm việc)
**Lập ngày:** 24/10/2026 · **Mốc mã nguồn:** `feat/workflow-format-and-deterministic-core` @ `3a96ea8`
**Phạm vi:** repo Brain (`PCBoiz/ANSER_AI`) và repo Body (`Dgsonn/ANSER-v2`)
**Trạng thái:** bản thảo, chờ chủ dự án chốt §8.3

---

## 1. Về tài liệu này

### 1.1. Nó là gì, và không là gì

Đây là **đặc tả cho người viết mã**, không phải bản mô tả nghiệp vụ gửi khách. Mỗi yêu cầu trong §4 và §5 có một tiêu chí nghiệm thu **chạy được bằng một lệnh**. Yêu cầu nào không kiểm được bằng lệnh thì nó chưa phải yêu cầu, nó là một mong muốn, và nó không được nằm trong tài liệu này.

Nó cũng không thay [SO_TAY_NGUOI_MOI.md](SO_TAY_NGUOI_MOI.md) (dựng môi trường, hiểu mã) hay [GIAO_VIEC_BRAIN.md](GIAO_VIEC_BRAIN.md) (bảy việc dài hạn kèm bối cảnh). Tài liệu này cắt ra **đúng phần làm trong hai tuần tới**, gán người và hạn.

### 1.2. Mẫu một yêu cầu, dùng lại cho chu kỳ sau

Chu kỳ 02 viết theo đúng khuôn này. Sáu mục, không thêm không bớt:

```
### <MÃ>. <tên ngắn, động từ trước>
**Ưu tiên** P0|P1|P2 · **Người làm** <vai> · **Hạn** <thứ, ngày> · **Phụ thuộc** <mã hoặc "không">

**Vì sao**        một đoạn. Nêu hậu quả cụ thể nếu không làm, tốt nhất là một
                  sự cố đã xảy ra. Không có hậu quả cụ thể thì xem lại yêu cầu.

**Yêu cầu**       dùng PHẢI / NÊN / CÓ THỂ. Mỗi câu một mệnh đề kiểm được.

**Nghiệm thu**    lệnh chạy được, kèm đầu ra mong đợi. Người khác chạy phải ra
                  cùng kết quả mà không cần hỏi gì thêm.

**Ngoài yêu cầu**  nói rõ cái gì KHÔNG thuộc phạm vi, để tránh phình việc.
```

Mục **Ngoài yêu cầu** là mục hay bị bỏ nhất và cũng là mục cứu nhiều thời gian nhất.

### 1.3. Quy ước mã và mức ưu tiên

| Tiền tố | Nghĩa |
|---|---|
| `BR-` | Yêu cầu thuộc repo Brain |
| `BD-` | Yêu cầu thuộc repo Body. **Đây là đề xuất đặc tả**, xem §2.1 |
| `CH-` | Yêu cầu cần cả hai bên cùng làm mới nghiệm thu được |
| `NFR-` | Yêu cầu phi chức năng, áp cho mọi yêu cầu chức năng |

| Mức | Nghĩa |
|---|---|
| **P0** | Không xong thì cổng ra chu kỳ (§7) không mở. Trượt P0 là trượt cả chu kỳ |
| **P1** | Cần cho chu kỳ, nhưng trượt thì vẫn mở được cổng với ghi chú |
| **P2** | Làm nếu còn thời gian. Trượt thì đẩy sang chu kỳ 02, không cần giải trình |

### 1.4. Từ khoá mức bắt buộc

**PHẢI** là điều kiện nghiệm thu, thiếu nó thì yêu cầu chưa xong. **NÊN** là khuyến nghị mạnh, bỏ qua thì phải ghi lý do vào PR. **CÓ THỂ** là tuỳ chọn, không ai phải giải trình.

---

## 2. Bối cảnh

### 2.1. Hai thành phần và ranh giới sửa đổi

| | **Brain** | **Body** |
|---|---|---|
| Repo | `PCBoiz/ANSER_AI` | `Dgsonn/ANSER-v2` |
| Công nghệ | Python, FastAPI | Next.js, Neon Postgres, Drizzle |
| Vai trò | Năng lực AI và lõi tính toán tất định, phục vụ qua HTTP | Giao diện, đăng nhập, dữ liệu nghiệp vụ |

Theo [AGENTS.md §1](AGENTS.md), người làm Brain **không được sửa repo Body**. Vì vậy mọi yêu cầu `BD-` trong tài liệu này là **bản đặc tả đề xuất**: đội Body đọc, phản hồi, rồi tự quyết cách làm. Chúng nằm chung một tài liệu vì chúng chặn nhau, và tách ra hai tài liệu là cách chắc chắn để hai bên hiểu khác nhau về cùng một hợp đồng.

### 2.2. Vì sao chu kỳ này tồn tại

[ROADMAP.md](ROADMAP.md) đặt cổng ra Giai đoạn B như sau:

> *Kế toán của Hoàng Phát tự tải file lên, tự đọc kết quả, **không cần ai ngồi cạnh**.*

Bảng trạng thái của chính ROADMAP cho thấy mọi ô khác đã xanh, trừ một ô:

| Việc | Trạng thái |
|---|---|
| Hai màn hình Dòng tiền + Cảnh báo sổ sách | ✅ 20/20 ca |
| Nạp file qua giao diện | ✅ 4 loại file MISA |
| Chạy trên máy mình | ✅ Brain 8000 + Body 3100 |
| Xác thực chặn đúng | ✅ quét 24 endpoint |
| Hướng dẫn cho người không phải kỹ thuật | ✅ |
| **Đưa lên chỗ khách truy cập được** | ❌ **chưa** |

Toàn bộ tài liệu kỹ thuật hiện có, kể cả sổ tay người mới viết tuần trước, hướng dẫn **chạy trên máy mình**. Đó là mô tả đúng hiện trạng, và hiện trạng đó là vấn đề: sáu phép kiểm sổ sách đã tìm ra 5.596.500đ giá vốn không ghi và 157/160 mã sai diện thuế trên dữ liệu thật của khách, nhưng khách **không có đường nào để tự chạy chúng**.

**Mục tiêu chu kỳ 01: đóng đúng ô đỏ đó.**

### 2.3. Đòn bẩy kỹ thuật làm mục tiêu này khả thi trong hai tuần

Lớp sinh ra giá trị **không cần GPU và không cần model**. Kiểm ngày 24/10/2026 bằng `RUNTIME_PROFILE=minimal`:

```
GET  /health              -> {"status":"ok","runtime_profile":"minimal",
                              "auth_enabled":true,"engine_ready":false}
GET  /tools   (no token)  -> 401
GET  /tools   (token)     -> 200
POST /tools/inventory-audit -> 2 phát hiện, money_impact 1.218.356đ
```

Nghĩa là Brain triển khai được lên **một máy CPU rẻ tiền**, phục vụ toàn bộ `/tools/*`, trong khi nhánh `/chat` cần model thì tạm tắt theo thiết kế. Không phải chờ thuê GPU, không phải chờ nối vLLM server.

### 2.4. Hiện trạng đo được, mốc `3a96ea8`

| Hạng mục | Lệnh | Kết quả |
|---|---|---|
| Bộ test | `ENV=LOCAL pytest -q` | 1003 passed |
| Lint | `ruff check src tests offline_training` | sạch |
| Kiểu tĩnh | `mypy` theo danh sách CI | sạch |
| Secret toàn lịch sử git | `git log --all -S` 5 mẫu | sạch, mọi khớp là fixture |

### 2.5. Ràng buộc bất biến

Năm ràng buộc R1–R5 ở [AGENTS.md](AGENTS.md) áp cho mọi yêu cầu dưới đây, không có ngoại lệ. Bản rút gọn: LLM không tính toán; dữ liệu khách không tới LLM bên thứ ba; hạ tầng ≤ 5.000.000đ/tháng; một khái niệm một nguồn; không hardcode phần cứng.

---

## 3. Giao diện ngoài

### 3.1. Actor

| Actor | Làm gì trong chu kỳ này |
|---|---|
| **Kế toán Hoàng Phát** | Đăng nhập, tải file MISA, đọc phát hiện. Đây là người mà cổng ra §7 đo |
| **Chủ doanh nghiệp** | Xem dòng tiền và cảnh báo sổ sách |
| **Đội Brain / Body** | Vận hành, đọc log, sửa |
| **n8n** | Gọi `/tools/*` theo lịch. Ngoài phạm vi chu kỳ này |

### 3.2. Hợp đồng HTTP Body ↔ Brain

Đang có và **không được đổi** trong chu kỳ này, trừ phần §4 nêu rõ:

| Đường | Dùng cho | Xác thực |
|---|---|---|
| `GET /health` | Body hiển thị chỉ báo AI | **Không** cần token, cố ý |
| `GET /tools` | manifest | `X-API-Token` |
| `POST /tools/*` | lớp tất định | `X-API-Token` |
| `POST /chat` | hỏi đáp AI | `X-API-Token` + `X-User-Id` + `X-Store-Id` |
| `GET /api/v1/task/{id}` | lấy kết quả | `X-API-Token` + `X-User-Id` (kiểm chủ sở hữu) |

`tests/test_body_contract.py` đọc thẳng `brain.ts` của Body để khoá hợp đồng này.

### 3.3. Ba hồ sơ chạy của Brain

Biến `RUNTIME_PROFILE`, đọc ở [`dependencies.py:20`](src/api/dependencies.py#L20):

| Giá trị | Nạp gì | Dùng ở đâu trong chu kỳ này |
|---|---|---|
| `full` (mặc định) | text + vision + RAG | máy dev, Colab |
| `text-only` | text + RAG, tắt vision | chưa dùng |
| **`minimal`** | **không nạp model nào** | **môi trường khách truy cập** |

---

## 4. Yêu cầu chức năng

### BR-01. `/tools/vat` phải từ chối trường lạ thay vì tính bằng 0

**Ưu tiên** P0 · **Người làm** Brain-1 · **Hạn** Thứ Ba 27/10 · **Phụ thuộc** không

**Vì sao.** `VatRequest.items` khai là `list[dict]` ([`tools.py:152`](src/api/routes/tools.py#L152)) nên pydantic không kiểm gì bên trong. Đo ngày 24/10/2026 trên chính endpoint đang chạy:

| Gửi vào | `calculated_total` | Tool kết luận |
|---|---|---|
| `{"price": 500000, "qty": 10}` | 5.400.000 | hợp lệ, lệch 0 |
| đổi `price` thành `unit_price` | **0** | **lệch 5.400.000đ, không hợp lệ** |
| tên trường tiếng Việt | **0** | lệch 5.400.000đ, `warnings: None` |

Gõ sai một chữ thì tool phát ra một lời buộc tội sổ sách chính xác tới từng đồng, và sai, không kèm cảnh báo nào. Đây là tool mà **model tự điền tham số** từ câu người dùng (`vat` không nằm trong `SYSTEM_DATA_FIELDS`), nên nguồn sai không phải giả định. Vi phạm trực tiếp AGENTS §4.1 quy tắc 5: *tool tự validate đầu vào, không tin tham số model điền*.

**Yêu cầu.**
1. `items` PHẢI dùng một model pydantic có kiểu, không dùng `dict` trần. Trường: `name: str`, `price: float`, `qty: float`, `is_reduced_vat: Optional[bool]`.
2. Model đó PHẢI đặt `extra="forbid"`. Trường lạ PHẢI làm request trả **422 kèm tên trường**, không được tính tiếp.
3. `price` và `qty` PHẢI là bắt buộc. Thiếu PHẢI trả 422, không được mặc định 0.
4. Lược đồ mới PHẢI hiện ra ở `GET /tools` để `agentic.py::arguments_schema` ràng buộc được model lúc sinh.
5. NÊN rà các endpoint `/tools/*` khác tìm `list[dict]` hoặc `dict` trần và ghi lại kết quả rà, kể cả khi không sửa trong chu kỳ này.

**Nghiệm thu.**
```bash
# a) đúng trường -> 200, lệch 0
curl -s -X POST localhost:8000/tools/vat -H "X-API-Token: $T" -H "Content-Type: application/json" \
  -d '{"items":[{"name":"X","price":500000,"qty":10,"is_reduced_vat":true}],"stated_total":5400000}'
#    -> "difference": 0, "is_valid": true

# b) sai tên trường -> 422, KHÔNG phải 200 kèm lệch 5.4 triệu
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/tools/vat -H "X-API-Token: $T" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"name":"X","unit_price":500000,"qty":10}],"stated_total":5400000}'
#    -> 422
```
Kèm test hồi quy trong `tests/test_pricing_and_tools.py` phủ cả ba ca ở bảng trên. `pytest -q` PHẢI vẫn xanh.

**Ngoài yêu cầu.** Không đổi công thức tính VAT. Không đụng `vat_catalog_audit`. Không sửa các tool khác trong chu kỳ này, chỉ rà và ghi lại.

---

### BR-02. Đóng gói Brain hồ sơ `minimal`, chạy được không GPU

**Ưu tiên** P0 · **Người làm** Brain-2 · **Hạn** Thứ Năm 29/10 · **Phụ thuộc** BD-01 (chốt chỗ đặt)

**Vì sao.** Đây là đường găng của cả chu kỳ. `deploy/Dockerfile` ghi *"KHÔNG có CUDA, image ~1GB"* rồi `pip install -r requirements.txt`, mà file đó ghim `vllm>=0.10.2,<0.12` và `torch>=2.4.0`. Nên image thật sẽ kéo về vllm và wheel CUDA, phản lại chú thích của chính nó, và không dựng nổi trên một máy CPU rẻ tiền. `deploy/docker-compose.yml` **chưa từng được chạy** (ghi ở đầu file).

**Yêu cầu.**
1. PHẢI tách `requirements.txt` thành hai: phần Brain chạy CPU, và phần GPU hoặc huấn luyện. Danh sách CPU lấy từ `.github/workflows/ci.yml`, vốn đã chứng minh là đủ cho 1003 test.
2. `deploy/Dockerfile` PHẢI chỉ cài phần CPU. Image dựng xong PHẢI **không chứa** `torch` bản CUDA và không chứa `vllm`.
3. Container chạy `RUNTIME_PROFILE=minimal` PHẢI phục vụ được `GET /health` và toàn bộ `POST /tools/*`.
4. `POST /chat` ở hồ sơ `minimal` PHẢI trả **503** kèm một câu tiếng Việt nói rõ tính năng hỏi đáp đang tắt, không trả 500 và không trả stack trace.
5. `GET /health` PHẢI trả `runtime_profile: "minimal"` và `auth_enabled: true`.
6. Khối `environment:` của service `brain` trong compose PHẢI đặt `RUNTIME_PROFILE`. Giá trị `ENV: SERVER` hiện tại PHẢI được hiểu tường minh hoặc gỡ bỏ, vì mã chỉ rẽ nhánh ở `== "LOCAL"` ([`engine.py:181`](src/core/engine.py#L181)).
7. `tests/test_deploy_config.py` PHẢI cập nhật theo: biến nào nối rồi thì ra khỏi `CHUA_NOI`, biến nào còn treo thì ở lại kèm lý do.

**Nghiệm thu.** Trên máy đích, không GPU:
```bash
docker compose up -d brain
curl -s localhost:8000/health | grep -q '"runtime_profile": *"minimal"'
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/tools              # 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Token: $T" localhost:8000/tools  # 200
curl -s -X POST localhost:8000/tools/inventory-import -H "X-API-Token: $T" \
     -F "file=@sample_data/ton_kho_mau.xlsx"                               # 8 phát hiện / 7 mã
docker image inspect anser-brain --format '{{.Size}}'                      # ghi lại con số
```
Ghi lại vào PR: kích thước image, thời gian khởi động nguội, và RAM lúc nghỉ.

**Ngoài yêu cầu.** Không nối `VLLMServerClient`. Không nối Redis. Không dựng `vllm-text` hay `vllm-vision`. Ba việc đó ở §9.

---

### BR-03. `SCHEMA MAP` khớp lược đồ Body, và mở đường lấy dòng bán hàng

**Ưu tiên** P1 · **Người làm** Brain-2 cặp với Brain-1 · **Hạn** Thứ Sáu 30/10 · **Phụ thuộc** BD-03

**Vì sao.** 4 trên 8 định danh trong `SCHEMA MAP` ([`saas_api.py:22-33`](src/core/saas_api.py#L22-L33)) không khớp Body. Triệu chứng với người dùng: hỏi *"còn bao nhiêu dầu AW46"* nhận về *"Lỗi hệ thống khi tìm sản phẩm"*, trông y hệt sự cố database. Lược đồ thật 13 bảng đã chép vào [GIAO_VIEC_BRAIN.md](GIAO_VIEC_BRAIN.md) V3.

Quan trọng hơn: `sales_invoice_items` có `unit_cost`, `quantity`, `line_total`. Nghĩa là `SaasAPI.get_report_lines`, hàm mà `chat.py` kiểm `getattr` rồi trả *"Tôi chưa nối được với dữ liệu bán hàng"*, nay **viết được**, kèm giá vốn từng dòng. Đó chính là thứ `reporting.py` phải tự thú là chỉ phủ 62% doanh thu.

**Yêu cầu.**
1. Bốn định danh PHẢI sửa: `stock_quantity`→`stock`, `workspace_id`→`warehouse_id`, `sales`→`sales_invoices`, `amount`→`total`. Mọi định danh PHẢI ở trong đúng khối `SCHEMA MAP`, không rải vào SQL.
2. PHẢI quyết cách xử `sales_invoices.warehouse_id IS NULL` và ghi lý do ngay tại chỗ. Cột này nullable, nên `WHERE warehouse_id = :ws` sẽ **âm thầm bỏ** mọi hoá đơn chưa gán kho.
3. `products.stock` là `numeric(14,3)`. Ép kiểu PHẢI giữ phần lẻ.
4. PHẢI viết `SaasAPI.get_report_lines`, trả đúng hình dạng `rp.SaleLine` và `rp.ExpenseLine` mà `_build_report_context` đang chờ.
5. PHẢI cập nhật cả ba nơi theo R4: `prompts.py::DB_SCHEMA`, `offline_training/db_schema.txt`, SQL trong `saas_api.py`.
6. PHẢI thêm phép thử hợp đồng đối chiếu `SCHEMA MAP` với một bản chụp lược đồ Body đã commit. Chủ dự án cho biết ERD *"đã chốt nhưng chưa hoàn thiện, còn giai đoạn thử nghiệm"*, nên thứ cần là một phép thử **kêu to lúc nó đổi**, không phải một lần sửa đúng.

**Nghiệm thu.** Trỏ vào một nhánh dev của Neon có dữ liệu mẫu:
```
"doanh thu hôm nay"      -> số thật, nhãn ghi HÔM NAY
"tháng này bán bao nhiêu"-> số của tháng này
"tháng trước"            -> nói thẳng chưa lấy được, mời hỏi lại 3 kỳ đang hỗ trợ
"quý này lãi hay lỗ"     -> ra số thật, KHÔNG còn câu "chưa nối được dữ liệu bán hàng"
```
Vế thứ ba quan trọng ngang hai vế đầu: trả một con số cho câu hỏi sai kỳ là lỗi không có triệu chứng.

**Ngoài yêu cầu.** Không sửa repo Body. Không làm tuổi nợ 30/60/90 trong chu kỳ này.

---

### BR-04. Mở rộng cổng lint của CI

**Ưu tiên** P2 · **Người làm** Brain-1 · **Hạn** Thứ Ba 03/11 · **Phụ thuộc** không

**Vì sao.** CI chỉ chạy `ruff` trên chín file viết tay, nên nó không nhìn thấy tám lỗi đã sửa ngày 22/10. Trong tám lỗi đó có một lỗi `F821` làm ô 4.2 của notebook Colab ném `NameError` giữa phiên đo, sau khi đã nạp xong model.

**Yêu cầu.** `.github/workflows/ci.yml` PHẢI chạy `ruff check src tests offline_training`. Lỗi mới PHẢI làm CI đỏ.

**Nghiệm thu.** Thêm tạm một biến tên `l` vào một file bất kỳ trong `src/`, đẩy lên nhánh phụ, CI PHẢI đỏ. Gỡ ra, CI PHẢI xanh.

**Ngoài yêu cầu.** Không mở rộng `mypy` trong chu kỳ này, vì diện lỗi của nó rộng hơn nhiều và sẽ chiếm trọn thời gian.

---

### BD-01. Body có địa chỉ mà kế toán Hoàng Phát truy cập được

**Ưu tiên** P0 · **Người làm** Đội Body · **Hạn** Thứ Tư 28/10 · **Phụ thuộc** quyết định §8.3 câu 1

**Vì sao.** Đây là ô đỏ duy nhất còn lại của Giai đoạn B. Mọi thứ khác trong chu kỳ này phục vụ nó.

**Yêu cầu.**
1. Body PHẢI chạy ở một địa chỉ ổn định mà khách mở bằng trình duyệt, có HTTPS.
2. PHẢI trỏ vào một nhánh Neon **không phải production** cho tới khi qua CH-02.
3. Biến `BRAIN_URL` PHẢI trỏ vào Brain của BR-02, không trỏ vào `localhost` của máy ai.
4. `BRAIN_API_TOKEN` của Body PHẢI khớp `API_AUTH_TOKEN` của Brain. Lệch hai biến này là sự cố 13/08/2026 lặp lại.
5. `BRAIN_KB_WORKSPACE` PHẢI khớp `KB_WORKSPACE_ID` của Brain. Để trống cả hai là an toàn nhất, vì cùng mặc định `default`.
6. Đăng nhập PHẢI bật. Không mở ẩn danh ra Internet.

**Nghiệm thu.** Từ một máy không phải máy dựng, không dùng VPN: mở địa chỉ, đăng nhập, vào màn hình Tồn kho, tải `ton_kho_mau.xlsx`, thấy 8 phát hiện trên 7 mã.

**Ngoài yêu cầu.** Chưa cần tên miền riêng của khách. Chưa cần sao lưu tự động.

---

### BD-02. Hiển thị đúng **ba** trạng thái AI, không phải hai

**Ưu tiên** P1 · **Người làm** Đội Body · **Hạn** Thứ Hai 02/11 · **Phụ thuộc** BR-02

**Vì sao.** Sau BR-02, Brain chạy hồ sơ `minimal` sẽ có `engine_ready: false` một cách **cố ý**. Nếu giao diện chỉ phân biệt "AI bật" và "AI hỏng" thì khách sẽ thấy một dải đỏ báo hỏng trong khi hệ thống đang chạy đúng thiết kế, và lần sau có hỏng thật thì không ai tin dải đỏ đó nữa.

`GET /health` đã trả sẵn `runtime_profile`. Đội Body cần xác nhận `brain.ts` có đọc trường này chưa.

**Yêu cầu.** Giao diện PHẢI phân biệt ba trạng thái:

| `/health` trả | Hiển thị |
|---|---|
| `runtime_profile: "minimal"` | "Hỏi đáp AI đang tắt. Các phép kiểm sổ sách vẫn chạy." Màu trung tính |
| `degraded: true` hoặc `engine_error` khác null ở hồ sơ `full` | cảnh báo đỏ, đây là hỏng thật |
| `auth_enabled: false` | **đỏ, mức cao nhất.** Brain đang không kiểm token |

**Nghiệm thu.** Dựng ba tình huống bằng cách đổi biến môi trường của Brain rồi tải lại trang, chụp màn hình cả ba, đính vào PR.

**Ngoài yêu cầu.** Không đổi gì ở luồng chat.

---

### BD-03. Xác nhận lược đồ và cung cấp bản chụp để Brain khoá hợp đồng

**Ưu tiên** P1 · **Người làm** Đội Body · **Hạn** Thứ Ba 27/10 · **Phụ thuộc** không

**Vì sao.** BR-03 chặn ở đây. Brain đọc được `schema.ts` trên nhánh `docs/onboarding-playbook`, nhưng chủ dự án cho biết ERD còn một giai đoạn thử nghiệm, nên Brain cần biết nhánh nào là nguồn và khi nào nó đổi.

**Yêu cầu.**
1. Đội Body PHẢI xác nhận nhánh nào là nguồn lược đồ cho chu kỳ này.
2. PHẢI xác nhận bốn ánh xạ: `products.stock`, `products.warehouse_id`, `sales_invoices.total`, `sales_invoices.warehouse_id`.
3. PHẢI trả lời: hoá đơn có `warehouse_id = NULL` là hợp lệ hay là dữ liệu lỗi. Câu trả lời quyết định yêu cầu số 2 của BR-03.
4. NÊN báo trước cho Brain khi lược đồ đổi, trước khi migration chạy lên nhánh dùng chung.

**Nghiệm thu.** Một tin nhắn hoặc một PR mô tả, có bốn câu trả lời trên, trước 17h Thứ Ba 27/10.

**Ngoài yêu cầu.** Chưa cần đổi lược đồ. Chu kỳ này Brain thích nghi theo Body, không ngược lại.

---

### CH-01. Quét xác thực trên môi trường đã triển khai, qua HTTPS thật

**Ưu tiên** P0 · **Người làm** Brain-1 cùng Đội Body · **Hạn** Thứ Ba 03/11 · **Phụ thuộc** BR-02, BD-01

**Vì sao.** Ba lỗ bảo mật ngày 15/08/2026 chỉ lộ ra khi quét **từng endpoint qua HTTP thật**, không phải TestClient. Một trong ba là `GET /api/v1/task/{id}` trả nguyên câu trả lời của AI gồm tên khách, mã số thuế, số công nợ, không kiểm gì cả. Lần này hệ thống mở ra Internet thật, nên phải quét lại trên đúng môi trường đó.

**Yêu cầu.**
1. PHẢI chạy `pytest tests/test_auth_bao_phu.py` trỏ vào địa chỉ đã triển khai, không phải `localhost`.
2. Mọi endpoint trừ `/health` PHẢI trả **401** khi không có token và khi token sai. Không được trả 422.
3. `GET /health` PHẢI trả `auth_enabled: true`.
4. `GET /api/v1/task/{id}` với `X-User-Id` của người khác PHẢI trả **404**, không phải 403.
5. PHẢI chạy `pytest tests/test_body_contract.py -k duong_dan`.

**Nghiệm thu.** Dán toàn bộ đầu ra của hai lệnh vào PR, kèm địa chỉ đã quét và thời điểm.

**Ngoài yêu cầu.** Không làm kiểm thử xâm nhập. Không thêm giới hạn tần suất trong chu kỳ này.

---

### CH-02. Buổi chạy thử với kế toán thật, trên môi trường thật

**Ưu tiên** P0 · **Người làm** Chủ dự án chủ trì, Brain-1 và Đội Body quan sát · **Hạn** Thứ Năm 05/11 · **Phụ thuộc** mọi P0 ở trên

**Vì sao.** Đây là cổng ra của chu kỳ, và là thứ duy nhất trả lời được câu *"khách có tự dùng được không"*. ROADMAP viết: *"đưa hướng dẫn + đường truy cập cho họ, rồi **ngồi im xem chỗ nào họ khựng lại**"*.

**Yêu cầu.**
1. Kế toán PHẢI tự đăng nhập, tự tải file MISA thật của họ, tự đọc kết quả. Không ai được thao tác hộ.
2. Người quan sát PHẢI ghi lại **mọi chỗ người dùng dừng quá 10 giây**, kèm câu hỏi họ nói ra.
3. PHẢI ghi ba loại riêng biệt: *chưa có dữ liệu*, *sai cấu hình*, *sản phẩm khó dùng*. Nhầm loại hai thành loại ba là đi sửa giao diện cho một lỗi biến môi trường.
4. Kết quả PHẢI viết thành một mục trong [ROADMAP.md](ROADMAP.md) trong cùng tuần.

**Nghiệm thu.** Kế toán hoàn thành trọn vòng tải file và đọc kết quả, không cần ai can thiệp. Nếu không đạt, biên bản PHẢI nêu đích danh chỗ hỏng, và đó là đầu vào của chu kỳ 02.

**Ngoài yêu cầu.** Không nhắm tính năng hỏi đáp AI. Chu kỳ này đo lớp sổ sách.

---

## 5. Yêu cầu phi chức năng

Áp cho mọi yêu cầu ở §4.

| Mã | Yêu cầu | Nghiệm thu |
|---|---|---|
| **NFR-01** | **Bảo mật.** `API_AUTH_TOKEN` PHẢI khác rỗng ở mọi môi trường ngoài máy dev. Không secret nào trong repo. Không commit `.env` | `/health` trả `auth_enabled: true`; quét secret 5 mẫu trên lịch sử trước mỗi lần push |
| **NFR-02** | **Chi phí.** Hạ tầng chu kỳ này PHẢI ≤ 500.000đ/tháng, tức 10% trần R3. PR nào tăng chi phí PHẢI ghi con số VNĐ/tháng | Ghi chi phí thật vào biên bản cuối chu kỳ |
| **NFR-03** | **Hiệu năng.** `POST /tools/inventory-import` với file 150 dòng NÊN xong dưới 5 giây. `GET /health` PHẢI dưới 500ms | Đo trên môi trường đã triển khai, ghi vào PR của BR-02 |
| **NFR-04** | **Quan sát được.** Mọi log PHẢI có `request_id`. `ai_metrics_log.jsonl` PHẢI ghi được. `/health` PHẢI đủ các trường ở §3.3 | Gọi một request, tìm lại được nó trong log bằng `request_id` |
| **NFR-05** | **Dữ liệu khách.** File tải lên PHẢI xử lý trong bộ nhớ, không ghi ra đĩa. Dữ liệu thật của khách PHẢI không vào repo | Rà PR; `sample_data/an_danh.py` cho bản ẩn danh |
| **NFR-06** | **Chưa biết khác bằng không.** Mọi trường thiếu dữ liệu PHẢI là `None`, không phải `0` | Có trong test của từng yêu cầu |

---

## 6. Phân công và lịch

### 6.1. Vai

| Vai | Là ai | Ghi chú |
|---|---|---|
| **Brain-1** | người mới vào | Nhận việc nhỏ, biên rõ, có đáp án kiểm được: BR-01, BR-04, CH-01 |
| **Brain-2** | người sắp nghỉ một thời gian | Nhận việc cần ngữ cảnh sẵn có: BR-02, BR-03. **Dồn vào tuần 1** |
| **Đội Body** | cả đội | BD-01, BD-02, BD-03 |
| **Chủ dự án** | bạn | Quyết §8.3, chủ trì CH-02, tìm kế toán rà sổ |

> **Ràng buộc lịch quan trọng nhất của chu kỳ này.** Brain-2 sắp nghỉ. Giá trị lớn nhất họ để lại là thứ chưa nằm trong tài liệu. Vì vậy BR-03 làm **theo cặp** với Brain-1, và mọi thứ Brain-2 giải thích miệng PHẢI được Brain-1 viết vào tài liệu trong cùng ngày. Sau Thứ Sáu 30/10, kế hoạch giả định Brain-2 không còn trả lời được.

### 6.2. Đường găng

```
BD-03 (xác nhận lược đồ)  ─┐
                           ├─► BR-03
BD-01 (chỗ đặt) ─► BR-02 ──┴─► CH-01 ─► CH-02  ◄── cổng ra chu kỳ
```

**BD-01 trượt là cả chu kỳ trượt.** Nó là việc duy nhất không ai bên Brain làm thay được, và nó phải xong trong tuần 1.

### 6.3. Tuần 1: Thứ Hai 26/10 đến Thứ Sáu 30/10

| Ngày | Brain-1 | Brain-2 | Đội Body | Chủ dự án |
|---|---|---|---|---|
| **T2 26/10** | Dựng môi trường theo [sổ tay §2](SO_TAY_NGUOI_MOI.md), chạy ra 1003 passed. Làm bài tập 1 và 2 | Rà `requirements.txt`, tách danh sách CPU | Chốt chỗ đặt, mở môi trường | **Chốt §8.3 trong ngày.** Trễ là cả chu kỳ trễ |
| **T3 27/10** | **BR-01** | **BR-02** Dockerfile | **BD-03 hạn 17h** | Liên hệ kế toán rà sổ |
| **T4 28/10** | **BR-01** xong, có test hồi quy | **BR-02** tiếp | **BD-01 hạn** | |
| **T5 29/10** | Cặp với Brain-2 trên **BR-03**, và là người **viết tài liệu** | **BR-02 hạn.** Rồi **BR-03** | Hỗ trợ Brain nối vào Body đã triển khai | |
| **T6 30/10** | Viết nốt những gì Brain-2 giải thích miệng | **BR-03 hạn.** Bàn giao nốt | | **Mốc M1**, xem 6.5 |

### 6.4. Tuần 2: Thứ Hai 02/11 đến Thứ Sáu 06/11

| Ngày | Brain-1 | Đội Body | Chủ dự án |
|---|---|---|---|
| **T2 02/11** | Nhận bàn giao, đọc lại tài liệu đã viết | **BD-02 hạn** | |
| **T3 03/11** | **CH-01 hạn.** Rồi **BR-04** | Cùng CH-01 | |
| **T4 04/11** | Nạp dữ liệu thật của Hoàng Phát lên môi trường đã triển khai, chạy thử trọn vòng một lượt | Sửa chỗ hỏng lộ ra | Chuẩn bị buổi chạy thử |
| **T5 05/11** | Quan sát, ghi chép | Quan sát, ghi chép | **CH-02: buổi chạy thử với kế toán** |
| **T6 06/11** | Sửa chỗ khựng ở mức sửa được trong ngày | Sửa chỗ khựng | **Mốc M2.** Viết kết quả vào ROADMAP |

### 6.5. Hai mốc kiểm

**M1, Thứ Sáu 30/10 cuối ngày.** Trả lời đúng một câu: *từ một máy bất kỳ không phải máy dựng, mở địa chỉ Body, đăng nhập, tải `ton_kho_mau.xlsx`, có thấy 8 phát hiện trên 7 mã không?*

Không đạt thì **dừng mọi việc P1 và P2**, dồn toàn bộ tuần 2 vào đường găng. Đừng làm BR-04 trong khi cổng chính chưa mở.

**M2, Thứ Sáu 06/11.** Cổng ra chu kỳ, xem §7.

---

## 7. Cổng ra chu kỳ

Chu kỳ 01 coi là đạt khi đủ cả năm:

- [ ] Kế toán Hoàng Phát tự tải file MISA thật lên và tự đọc được kết quả, **không ai ngồi cạnh** (CH-02)
- [ ] Quét xác thực trên môi trường đã triển khai, qua HTTPS thật, mọi endpoint trừ `/health` trả 401 khi không có token (CH-01)
- [ ] `/tools/vat` trả 422 cho trường lạ, không còn tính bằng 0 rồi buộc tội sổ sách (BR-01)
- [ ] `pytest -q` xanh, `ruff` sạch, và các con số đó đo trên **đúng mã đã triển khai**
- [ ] Biên bản chu kỳ ghi rõ ba thứ: chi phí thật VNĐ/tháng, những chỗ khách khựng lại, và danh sách đẩy sang chu kỳ 02

Mỗi mục chưa đạt PHẢI có một dòng nêu lý do và người chịu trách nhiệm đẩy tiếp.

---

## 8. Rủi ro, giả định, và việc cần chốt

### 8.1. Rủi ro

| Rủi ro | Dấu hiệu sớm | Xử lý |
|---|---|---|
| BD-01 trượt vì chưa chốt chỗ đặt | Hết Thứ Hai 26/10 mà chưa có quyết định | Chủ dự án quyết trong ngày. Mọi phương án đều hơn không quyết |
| Brain-2 nghỉ sớm hơn dự kiến | không có dấu hiệu báo trước | Dồn BR-03 lên sớm, và Brain-1 viết tài liệu **trong lúc** nghe, không để sau |
| `docker compose` chưa ai chạy bao giờ, nổ lúc dựng | BR-02 trượt Thứ Tư | Lùi về chạy uvicorn thẳng trên máy đích. Cổng ra không đòi Docker |
| Dữ liệu thật của khách chưa về kịp buổi 05/11 | Hết Thứ Hai 02/11 chưa có file | Chạy buổi đó bằng bản xuất MISA khách đã gửi tháng 8 |
| Lược đồ Body đổi giữa chu kỳ | migration mới trên nhánh dùng chung | Phép thử hợp đồng ở BR-03 yêu cầu 6 sẽ đỏ, đó là mục đích của nó |

### 8.2. Giả định

1. Hoàng Phát vẫn là khách duy nhất, nên chưa cần cô lập dữ liệu đa khách.
2. Không thuê GPU trong chu kỳ này. Nhánh `/chat` tắt theo thiết kế ở môi trường khách.
3. Bốn file MISA đã nhận tháng 8 còn dùng được làm dữ liệu thử.
4. Đội Body có quyền triển khai mà không cần phê duyệt bên ngoài.

### 8.3. Chủ dự án cần chốt trước 17h Thứ Hai 26/10

| # | Câu hỏi | Vì sao không hoãn được |
|---|---|---|
| 1 | **Body và Brain đặt ở đâu?** Nêu nhà cung cấp và ai trả tiền | Chặn BD-01, tức chặn đường găng |
| 2 | **Tắt `/chat` ở môi trường khách trong chu kỳ này có được không?** | Đây là đề xuất của tài liệu, không phải quyết định đã có. Nếu phải bật thì chu kỳ cần thêm một tuần cho việc nối vLLM |
| 3 | **Ai là Brain-1 và Brain-2?** Brain-2 nghỉ từ ngày nào | Quyết toàn bộ lịch tuần 1 |
| 4 | **Buổi 05/11 kế toán nào ngồi?** Người của Hoàng Phát, hay kế toán rà sổ, hay cả hai | Hai người này phục vụ hai mục đích khác nhau |

---

## 9. Ngoài phạm vi chu kỳ 01

Nêu ra để không ai làm, và để biết chúng chưa chết:

| Việc | Vì sao hoãn | Ở đâu |
|---|---|---|
| Nối `VLLMServerClient` vào `engine.py` | Không phục vụ cổng ra. Lớp sổ sách không cần model | [GIAO_VIEC_BRAIN.md](GIAO_VIEC_BRAIN.md) V2 |
| Nối Redis cho `TASK_REGISTRY`, client HTTP cho vision | Chưa chặn gì khi chạy một worker | V2 bước 5 |
| Bộ đo RAG: recall@20, MRR, faithfulness | Cần tài liệu thật của khách mới đo có nghĩa | V4 |
| Phiên đo lại trên Colab | Cần GPU và một buổi trọn vẹn | V5 |
| Mảng vận tải | Chặn bởi khách. Hoàng Phát chưa làm vận tải | V7 |
| Tuổi nợ 30/60/90 | Chặn bởi sổ chi tiết công nợ của khách | V6 |
| Huấn luyện lại model | Đã đo: narration hỏng 11 sửa 0 | ROADMAP GĐ D |

Việc duy nhất ngoài phạm vi mà vẫn **nên khởi động trong chu kỳ này** là tìm kế toán có nghề rà [HOANG_PHAT_SOAT_SO_1108.md](HOANG_PHAT_SOAT_SO_1108.md). Nó phụ thuộc lịch người ngoài nên càng hỏi sớm càng tốt, và nó rẻ hơn mọi việc trong tài liệu này.

---

## 10. Tham chiếu

| Cần gì | Đọc đâu |
|---|---|
| Dựng môi trường, hiểu mã, từ điển thuật ngữ | [SO_TAY_NGUOI_MOI.md](SO_TAY_NGUOI_MOI.md) |
| Bảy việc dài hạn kèm bối cảnh đầy đủ | [GIAO_VIEC_BRAIN.md](GIAO_VIEC_BRAIN.md) |
| Năm ràng buộc R1–R5, quy trình phản biện | [AGENTS.md](AGENTS.md) |
| Quyết định kiến trúc, sổ lỗi | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Cổng ra từng giai đoạn | [ROADMAP.md](ROADMAP.md) |
| Kịch bản chạy thử từng bước | [CHAY_THU_NOI_BO.md](CHAY_THU_NOI_BO.md) |
| Kết quả soát sổ gửi khách | [HOANG_PHAT_SOAT_SO_1108.md](HOANG_PHAT_SOAT_SO_1108.md) |
| Hợp đồng API với Body | `tests/test_body_contract.py` |

---

*Chu kỳ 02 dùng lại khuôn ở §1.2. Đầu vào của nó là biên bản §7 và danh sách §9, không phải một trang giấy trắng.*
