# AGENTS.md — Chỉ thị vận hành cho Agent kỹ thuật, dự án ANSER Brain

> **Phiên bản:** 2.0 — 27/07/2026
> **Đọc kèm:** [ARCHITECTURE.md](ARCHITECTURE.md) là nguồn sự thật về *kiến trúc*. File này là nguồn sự thật về *cách làm việc*.
> **Thay thế:** AGENTS.md v1.0 (giả định A100 80GB + Qwen2.5-Coder-32B — cả hai đều không còn đúng).

---

## 1. Phạm vi & ranh giới

| Repo | Vai trò | Quyền của agent |
|---|---|---|
| **`AI_ANSER` (Brain)** | FastAPI service cung cấp năng lực AI | ✅ Toàn quyền sửa |
| **`ANSER Body`** (Flask, VPS, Neon, n8n) | Nền tảng nghiệp vụ, gọi Brain qua HTTP | ❌ **KHÔNG ĐƯỢC SỬA.** Chỉ được *đề xuất* thay đổi bằng văn bản |

Khi một việc cần Body đổi (ví dụ thêm bảng logistics ở [ARCHITECTURE.md §10](ARCHITECTURE.md)), agent viết bản đặc tả thay đổi và **dừng lại chờ người quyết định** — không tự ý mock hay giả định Body đã có.

### Bản sao mô tả

[`agent_middleware.py`](src/core/agent_middleware.py) và các khối `SCHEMA MAP` trong [`memory.py`](src/core/memory.py), [`saas_api.py`](src/core/saas_api.py) là **bản sao mô tả** của thứ thuộc về Body. Chúng lệch được, và đã từng lệch. Trước khi tin vào chúng, đối chiếu lại với Body.

---

## 2. Năm ràng buộc bất biến

Đây là phiên bản hành động của 5 nguyên tắc trong [ARCHITECTURE.md §1](ARCHITECTURE.md). Vi phạm bất kỳ điều nào ⇒ code bị từ chối, không tranh luận.

### R1 — Deterministic-first

**LLM không bao giờ tính toán.**

| ❌ Cấm | ✅ Bắt buộc |
|---|---|
| Prompt kiểu "tính giúp tôi tổng tiền thuế" | `MCPServer.calculate_vat()` — code thuần |
| Cho LLM tự cộng dòng hóa đơn | `validate_invoice_total()` tính lại toàn bộ |
| Cho LLM suy ra "vì sao lệch 3 triệu" | `reconciliation.py` phân rã kèm bằng chứng, LLM chỉ diễn giải |
| Cho LLM sinh SQL tự do rồi chạy | Tool có tham số ràng buộc, SQL viết sẵn |
| Cho LLM tự cộng doanh thu/chi phí ra lợi nhuận | `reporting.build_report()` — code thuần, LLM chỉ diễn giải |
| Trong vòng agentic: model tự tính rồi tuyên bố kết quả | Grammar `oneOf` gọi-tool/trả-lời; mọi con số phải đến từ kết quả tool |

Kiểm tra nhanh trước khi commit: *nếu model đọc sai một chữ số, có bản ghi sổ sách nào sai theo không?* Nếu có — thiếu lớp tất định.

**Thiếu dữ liệu thì nói thiếu, không điền 0.** `reporting.py` không coi giá vốn trống là 0 (làm thế thì lãi gộp = doanh thu — một con số sai mà trông rất đẹp); nó tính `cogs_coverage_pct`, hạ `confidence` và cảnh báo. Con số tài chính sai mà *nghe có vẻ đúng* là loại lỗi tệ nhất: không ai phát hiện tới lúc quyết toán.

### R2 — Chủ quyền dữ liệu

**Không gửi dữ liệu khách hàng tới bất kỳ LLM bên thứ ba nào.** Không OpenAI, không Gemini, không Claude, không DeepSeek — kể cả "chỉ để test".

Dữ liệu khách hàng gồm: tồn kho, doanh thu, công nợ, **bảng giá cước**, **tỷ lệ biên lợi nhuận**, danh sách khách, nội dung hóa đơn, lịch sử chat.

Ngoại lệ duy nhất — nguồn công khai, **chỉ đọc, không kèm tham số chứa dữ liệu khách**: giá xăng dầu, thời tiết, tỷ giá, tìm kiếm web.

> ⚠️ [`evaluate_system.py`](src/evaluate_system.py) hiện gọi DeepSeek API làm "judge". **Chỉ được chạy trên dữ liệu tổng hợp/mẫu**, tuyệt đối không trên dữ liệu khách thật. Ưu tiên thay bằng judge local.

> ⚠️ `requirements.txt` có `openai`. Nếu package này được dùng để gọi API ngoài với dữ liệu khách — đó là vi phạm R2. Dùng nó làm client cho vLLM OpenAI-compatible server **nội bộ** thì hợp lệ.

**R2b — Kỷ luật bí mật (bổ sung 27/07/2026, sau sự cố lộ mật khẩu Neon):**

1. **Không bao giờ hardcode credential** — kể cả trong script một lần (`src/archive/`), kể cả trong `_backups/`. Sự cố thật: 3 script archive chứa nguyên chuỗi Neon Postgres, nhân bản thành 12 file qua các bản backup, bị đẩy lên GitHub public → Neon phát cảnh báo, phải xoay mật khẩu.
2. **Trước khi push lịch sử lên một remote MỚI hoặc public**: bắt buộc quét bí mật trên TOÀN BỘ lịch sử (`git log --all -S` với các mẫu `postgres://.*:.*@`, `npg_`, `sk-`, `hf_`, `AIza`...), không chỉ quét HEAD. Push lịch sử = publish mọi commit từng tồn tại.
3. **Đưa bất kỳ giá trị bảo mật nào vào env / đổi cách quản lý bí mật → HỎI Ý KIẾN chủ dự án TRƯỚC** — chỉ thị trực tiếp của chủ dự án. Tái sử dụng biến đã có (như `DATABASE_URL`) để sửa sự cố thì được, nhưng phải báo lại rõ ràng.
4. Credential đã lộ là credential **đã chết** — xoá khỏi git không thu hồi được nó (bot quét GitHub trong vài giây). Việc đầu tiên luôn là **xoay/vô hiệu credential**, dọn repo chỉ là bước sau.

**Lưu ý trung thực với khách:** ở bậc hạ tầng T0/T1 (GPU thuê), R2 mới thỏa mãn *một phần* — xem [ARCHITECTURE.md §4.3](ARCHITECTURE.md). Không quảng cáo "dữ liệu không rời hệ thống" trước khi đạt T3 (máy tự sở hữu).

### R3 — Kỷ luật ngân sách

Trần hạ tầng phục vụ pilot miễn phí: **5.000.000đ/tháng. Thấp hơn càng tốt.** Mục tiêu hiện tại là bậc T0 ≈ 750.000đ/tháng.

Mọi PR làm tăng chi phí vận hành (model to hơn, context dài hơn, thêm GPU, thêm service thường trực) phải kèm:
1. Chi phí tăng thêm, tính bằng VNĐ/tháng
2. Chỉ số nghiệp vụ nào cải thiện, đo bằng cách nào
3. Doanh thu nào chi trả cho phần tăng đó

Không có 3 mục này ⇒ PR bị từ chối.

### R4 — Một định dạng, một nguồn sự thật

**Định dạng workflow duy nhất: n8n.** Make.com và engine nội bộ Body không phải đích sinh code.

Ba nơi sau phải luôn khớp nhau. Sửa một nơi mà không sửa hai nơi kia là lỗi:

| Nơi | Vai trò |
|---|---|
| [`prompts.py::CODER_SYSTEM`](src/core/prompts.py) | Dạy model định dạng |
| [`agent_middleware.py`](src/core/agent_middleware.py) | Danh mục node đưa vào prompt |
| [`chat.py::_validate_workflow`](src/api/routes/chat.py) | Kiểm tra đầu ra |

Tương tự với lược đồ DB: [`prompts.py::DB_SCHEMA`](src/core/prompts.py) và [`db_schema.txt`](offline_training/db_schema.txt) và SQL trong [`saas_api.py`](src/core/saas_api.py) phải khớp. Hiện đang lệch (`sales.amount` vs `sales.total_amount`) — xem [ARCHITECTURE.md §11.5](ARCHITECTURE.md).

### R5 — Hardware-neutral

**Không hardcode giả định phần cứng.** Không tên GPU, không con số VRAM, không đường dẫn `/content/drive/...` trong code.

Mọi tham số phần cứng đọc từ biến môi trường, có mặc định an toàn:

```python
TEXT_MODEL_ID          # đường dẫn hoặc HF id
VISION_MODEL_ID
VLLM_BASE_URL          # http://127.0.0.1:8001/v1
GPU_MEMORY_UTILIZATION
MAX_MODEL_LEN
QUANTIZATION
ENV                    # LOCAL | GPU
```

Tiêu chí nghiệm thu: **chuyển từ GPU thuê sang máy tự sở hữu chỉ đổi `.env`, không sửa dòng code nào.**

---

## 3. Môi trường

### 3.1. Ba môi trường

| Môi trường | Phần cứng | `ENV` | Hành vi |
|---|---|---|---|
| **Dev cục bộ** | Windows 11, GTX 1660 Ti 6GB | `LOCAL` | Mock response, **không nạp model thật**. Toàn bộ logic tất định + routing + API vẫn chạy và test được |
| **GPU thuê** (hiện tại) | RTX 3090 24GB, Linux | `GPU` | vLLM server riêng + vision. Đích triển khai bậc T0/T1 |
| **Máy tự sở hữu** (tương lai) | RTX 3090/4090 24GB | `GPU` | Cùng code, chỉ khác `.env` |

Chế độ `LOCAL` không phải "chế độ giả vờ" — nó là thứ cho phép test toàn bộ tầng tất định (nơi P1 nói rằng phần lớn giá trị nằm ở đó) mà không cần GPU. Giữ nó hoạt động.

> ❌ **Colab không còn là môi trường production.** Điều khoản Colab Paid cấm phục vụ web service. Chỉ dùng Colab cho fine-tune / quantize / thử nghiệm rời rạc — xem [ARCHITECTURE.md §4.4](ARCHITECTURE.md).

### 3.1b. Kiểm thử GPU chạy trên Google Colab

Chốt 27/07/2026: test có GPU thật chạy trên **Colab** (không phải máy dev). Notebook test sẽ soạn **khi chủ dự án yêu cầu** — không tự tạo sớm; cải tiến xong mới test. (Colab chỉ cho thử nghiệm rời rạc — production vẫn bị cấm theo §3.1.)

### 3.1c. Dữ liệu giá phải sát thời gian thực

Yêu cầu nghiệp vụ trực tiếp từ chủ dự án: *"hôm nay 25 nghìn, ngày mai 30 nghìn"* — báo giá dựa trên giá cũ là báo giá sai. Hệ quả thiết kế:

1. Tool nào nhận tham số giá (`current_fuel_price`...) thì **caller phải lấy giá mới nhất tại thời điểm gọi**, không đọc giá trị cache cũ từ hôm trước.
2. Nguồn giá công khai (dầu, tỷ giá) cập nhật bằng n8n scheduled job — được phép gọi ra ngoài vì là dữ liệu công khai một chiều (R2).
3. Kết quả báo giá phải ghi kèm **thời điểm và giá đầu vào** đã dùng (đã có trong `internal` của `/tools/quote`) — để khi giá đổi, biết báo giá cũ dựa trên gì.

### 3.2. Cross-platform

1. **Đường dẫn:** dùng `pathlib`. Không hardcode `/` hay `\`. Code phải chạy cả Windows lẫn Linux.
2. **Không phụ thuộc lệnh bash** trong `subprocess`.
3. **Không hardcode credential.** Mọi bí mật qua `os.getenv()`.
4. **Ghim version** khi thêm thư viện vào `requirements.txt`.

---

## 4. Quy tắc code

### 4.1. Bắt buộc

| # | Quy tắc |
|---|---|
| 1 | **Constrained decoding thay cho retry.** Đầu ra JSON dùng `guided_json`. Đừng "hy vọng model làm đúng rồi retry" |
| 2 | **Không chặn event loop.** Inference nặng qua `run_in_executor` hoặc HTTP tới vLLM server |
| 3 | **Log có cấu trúc, không `print`.** `logger` + `extra={"request_id": ...}` |
| 4 | **Không nuốt exception.** `except Exception: pass` bị cấm. Ít nhất phải `logger.warning` kèm ngữ cảnh |
| 5 | **Tool tự validate đầu vào.** Không tin tham số model điền |
| 6 | **Tool ghi dữ liệu tạo `pending_review`.** Không tự động duyệt bất cứ thứ gì chạm tiền hoặc sổ sách |
| 7 | **Prompt chỉ sống trong [`prompts.py`](src/core/prompts.py).** Không rải chuỗi prompt khắp agent |
| 8 | **Sanitize đầu ra VLM.** Hóa đơn là dữ liệu ngoài — chống prompt injection trước khi đưa xuống Body |

### 4.2. Chống mục ruỗng

- Xoá code chết thay vì để lại. `RetailChatResponse`/`ProductExtraction` từng bị đánh dấu dead code — kiểm tra trước khi thêm schema mới.
- `src/archive/` **đã xoá** (05/08/2026): 15 script thời ProjectA_Backup/Make.com, trỏ vào đường dẫn Drive không còn tồn tại, không nơi nào import, và chiếm 215/252 lỗi lint của cả repo. Lấy lại bằng `git show 306a16c:src/archive/<file>` nếu cần đối chiếu.
- Sửa code là sửa tài liệu **trong cùng PR**. ARCHITECTURE.md v1.0 lệch khỏi code nhiều tháng và đã dẫn tới quyết định sai (chọn model theo A100 trong khi code chạy L4).

---

## 5. Quy trình làm việc

### 5.1. Trước khi viết code

1. **Đọc code, không đọc tài liệu cũ.** Tài liệu từng sai ở nhiều điểm quan trọng. Xác minh bằng file thật.
2. **Đối chiếu 5 ràng buộc.** Đề xuất vi phạm R1-R5 ⇒ dừng, không "làm tạm rồi sửa sau".
3. **Nêu chỉ số sẽ cải thiện** và cách đo. Không đo được ⇒ không biết có tác dụng hay không.

### 5.2. Giao thức phản biện

Không code nào được viết mà không có phản biện.

1. `@engineer` đề xuất giải pháp.
2. `@qa` **tìm cách phá nó** — trường hợp biên, lỗi đồng thời, dữ liệu bẩn, thư viện bịa.
3. Tinh chỉnh cho tới khi `@qa` xác nhận `STATUS: VERIFIED AND SAFE FOR EXECUTION`.
4. `@mentor` audit từng dòng, đặc biệt về R1 (LLM có lén tính toán không) và R2 (có dữ liệu nào rò ra ngoài không). Đóng dấu `[PASSED BY MENTOR]`.

Trọng tâm phản biện — 4 câu hỏi hỏi mọi lần:

- Nếu model trả về rác, có bản ghi sổ sách nào sai theo không? *(R1)*
- Payload này có chứa dữ liệu khách hàng, và nó đi tới đâu? *(R2)*
- Việc này làm tăng chi phí GPU bao nhiêu VNĐ/tháng? *(R3)*
- Định nghĩa này đã tồn tại ở chỗ khác chưa? *(R4)*

### 5.3. Kiểm thử

- Logic tất định (pricing, VAT, reconciliation) phải có unit test — đây là phần **không được phép sai**.
- Tầng API test bằng `ENV=LOCAL`, không cần GPU.
- Đổi định dạng workflow ⇒ cập nhật `tests/` trong cùng PR.
- Trước khi tuyên bố "xong": chạy `pytest`, dán kết quả. Test fail thì nói rõ là fail — không mô tả vòng vo.

---

## 6. Version control & sao lưu

1. **Quy tắc 5 thay đổi:** đúng khi chạm 5 file bị sửa, HOẶC trước bất kỳ thay đổi cấu trúc rủi ro cao nào ⇒ commit cục bộ.
2. **Cuối giai đoạn:** sau khi có `[PASSED BY MENTOR]` và người phê duyệt:
   - Sao lưu cục bộ có dấu thời gian vào `_backups/Phase_X_YYYYMMDD/` (bỏ `__pycache__`, `.venv`)
   - `git add . && git commit && git push`
3. **Nếu sandbox chặn:** sinh script Python cross-platform `execute_backup_and_push.py` để người dùng chạy một lần.
4. **Không commit:** credential, model weights, dữ liệu khách hàng thật.
5. **Phải commit:** 5 file nguồn tập train mà [`merge_all.py`](offline_training/merge_all.py) cần (`train_retail_base`, `module_a_clean`, `module_b`, `module_c`, `module_d`). Hiện thiếu ⇒ **không train lại được model** ⇒ single point of failure.

---

## 7. Định nghĩa "xong"

Một việc chỉ được coi là xong khi đủ cả 7:

- [ ] Code chạy ở `ENV=LOCAL` không cần GPU
- [ ] Không vi phạm R1-R5
- [ ] Có test cho phần logic tất định; `pytest` xanh (hoặc nêu rõ cái nào đỏ và vì sao)
- [ ] Tài liệu bị ảnh hưởng đã cập nhật trong cùng PR
- [ ] Nêu được chỉ số cải thiện và cách đo
- [ ] Nêu được tác động chi phí bằng VNĐ/tháng
- [ ] `[PASSED BY MENTOR]`

---

## 8. Ưu tiên hiện tại

Theo [ARCHITECTURE.md §12](ARCHITECTURE.md):

| Thứ tự | Việc | Trạng thái |
|---|---|---|
| S0 | Tài liệu chiến lược — ARCHITECTURE.md + AGENTS.md | ✅ Xong |
| S1 | Chốt n8n làm định dạng duy nhất + bật `guided_json` + xoá vòng retry | ✅ Xong |
| S1b | Pipeline fine-tune v3 (Qwen3-8B, reverse-generation) + khôi phục data v2 | ✅ Xong |
| S3 | Tầng tool + vòng lặp agentic + MCP bọc REST | ✅ Xong |
| S4 | Metrics `ai_metrics_log` | ✅ Xong |
| S7 | Hội thoại nhiều lượt (runtime + data đa lượt) | ✅ Xong |
| S8 | Kênh giải thích xAI (nhánh EXPLAIN) + engine báo cáo DT/CP/LN | ✅ Xong |
| **S2** | **Hạ tầng: vLLM server riêng, Qwen3-8B, ctx 32k, Redis, Cloudflare Tunnel** | 🔵 **Kế tiếp** |
| S5 | XAI hoá đơn: `reconciliation.py` + `InvoiceFieldValidator` + gộp prompt hoá đơn | ⚪ Chờ |
| S6 | Lược đồ Logistics bên Body + API xuất dòng bán/chi phí cho `/tools/report` — **cần phối hợp repo Body** | ⚪ Chặn |

Nghiệp vụ ưu tiên 1 là **logistics / báo giá vận tải**. Bán lẻ giữ lại vì code đã có, nhưng không phải đích tối ưu hoá hiện tại.
