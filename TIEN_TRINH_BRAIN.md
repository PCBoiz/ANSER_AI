# TIẾN TRÌNH BRAIN — bản kiểm soát lộ trình

**Cập nhật 25/08/2026.** File này trả lời bốn câu cho người tiếp quản:
*đang ở đâu, cái gì đã chắc, cái gì đang dở, và đụng vào đâu thì gãy.*

Khác với [BAN_GIAO_VAN_TAI.md](BAN_GIAO_VAN_TAI.md) — bản đó chỉ nói phần **vận
tải**. Bản này nói **toàn cảnh Brain**, vì phần vận tải nằm trên cùng một lớp
nền với phần kế toán: không biết lớp nền có gì thì sửa một chỗ vỡ ba chỗ.

---

## 1. Đang ở đâu

### Nhánh

| Nhánh | Nội dung | Trạng thái |
|---|---|---|
| `feat/workflow-format-and-deterministic-core` | **nhánh chính đang làm việc** | `6609984`, đã đẩy, **1003 test xanh** |
| `feat/lop-provider-cho-benchmark` | lớp provider cho benchmark + loạt sửa Colab | **đã gộp vào nhánh chính** ngày 25/08 |
| `main` | bản cũ | không dùng, đừng gộp vào |
| `test` | nhánh rác | không dùng |

> Nhánh chính **chưa gộp vào `main`**. Đây là chủ ý: `main` là bản trước khi có
> lõi tất định, gộp ngược vào là kéo về kiến trúc cũ.

### Số đo hiện tại

```
1003 test xanh   (785 hàm khai báo; chênh do parametrize —
                  test_auth_bao_phu.py sinh 50 ca từ 24 route)
43 file test
```

Phân bố theo mảng — dùng để biết chỗ nào có lưới an toàn, chỗ nào không:

| Mảng | Test | File | Ghi chú |
|---|---|---|---|
| **Kế toán / sổ sách** | 193 | 9 | dày nhất — cũng là chỗ chạy trên dữ liệu thật |
| **Bộ đo / huấn luyện** | 133 | 4 | gồm `providers.py` mới của nhánh benchmark |
| **Lớp AI / agentic** | 125 | 6 | |
| **Vận tải** | 82 | 4 | mã đủ, **chưa hiệu chỉnh trên số thật của ai** |
| **Hạ tầng / API** | 80 | 9 | gồm 50 ca quét xác thực |
| **RAG / tri thức** | 70 | 4 | test đơn vị, **không có thước đo truy hồi** |
| Khác | 102 | 7 | |

---

## 2. Cái gì đã chắc

Chắc = **đã chạy trên dữ liệu thật hoặc đã đo bằng số**, không phải "đã viết xong".

### 🟢 Lõi kế toán — chạy thật, ra tiền

Sáu phép kiểm tất định, **không cần GPU, không cần model**. Chạy trên 6 file MISA
thật của Hoàng Phát:

| Phép kiểm | Tìm ra gì |
|---|---|
| Tồn kho | 2 mã âm; **5.596.500đ** giá vốn không được ghi |
| Đối chiếu hai kỳ | chứng từ **sửa hồi tố**, 108 lít chạy từ mã này sang mã kia |
| Thuế suất GTGT | **157/160 mã** để sai diện thuế theo NĐ 174/2025 |
| Công nợ | phải thu **3,96 tỷ** = 113 ngày giá vốn; 3 khách giữ **66%** |
| Mã số thuế | 114 mã kiểm được, **0 sai**, 0 báo oan |
| Hàng chết | 29 mã, ~161 triệu nằm im |

Bộ đo riêng: `offline_training/eval_ke_toan.py` — 12 ca gieo lỗi vào chính sổ
thật, hiện **12/12 bắt được, 12/12 không báo oan**. Nhưng n=12 nên khoảng tin cậy
là **75,8%–100%** — bộ đo tự nói ra giới hạn của nó.

### 🟢 Lớp AI — đã đo, đã quyết

Hai phiên Colab đầy đủ (15/08), so theo cặp bằng McNemar:

| Nhánh | Model gốc | Fine-tune | Hỏng | Sửa | p |
|---|---|---|---|---|---|
| extraction | 0,0% | **65,3%** | 0 | 64 | ~0 |
| n8n | 50,0% | 67,6% | 6 | 12 | 0,2379 |
| narration | 85,2% | 44,4% | 11 | 0 | 0,0010 |
| agentic | 52,6% | 15,8% | 8 | 1 | 0,0391 |

**Kết luận cho nhánh kế toán: dùng model gốc.** Nhưng đọc kỹ dòng extraction —
nó là **nhánh của vận tải**, và ở đó bản fine-tune thắng áp đảo. Hai kết luận
ngược nhau cho hai sản phẩm, và cả hai đều đúng.

### 🟢 Xác thực — đã quét từng endpoint qua HTTP thật

`tests/test_auth_bao_phu.py` hỏi **toàn bộ bảng route**, không phải danh sách
viết tay. Không token → 401, token sai → 401, và `/health` vẫn mở để biết Brain
sống hay chết.

Ba lỗ đã vá ngày 15/08 — xem mục 5.

---

## 3. Cái gì đang dở

### 🟡 Việc treo #1 — `render_tools()` đã sửa, **chưa đo lại**

Commit `0c82c4d` sửa một lỗ hổng thật: prompt **quảng cáo đúng những trường mà
lược đồ đã gạch tên**.

```
- report: ...
    tham số: granularity, periods_back, top_n, sales, expenses
- inventory_audit: ...
    tham số: lines*, warehouse, period_start, period_end
```

`sales`, `expenses`, `lines*` là trường **hệ thống tự bơm**. Ta bảo model "phải
điền `lines`", rồi định dùng grammar cấm nó điền. Model làm đúng lời dặn → viết
mảng dài → tràn trần token → JSON cắt cụt → vòng lặp gãy.

**Đã sửa trong mã, chưa có số chứng minh nó kéo agentic lên.** Cần một phiên đo.

### 🟡 Việc treo #2 — phiên đo lại sau khi có `providers.py`

Nhánh benchmark thêm lớp `NhaCungCap` với `nha.rang_buoc` — ghi lại **chế độ ràng
buộc** vào file kết quả. Tôi đắp phép thử của mình lên: `rang_buoc` nói bộ đo
**định** dùng chế độ nào, phép thử nói chế độ đó có **thi hành** thật không.

Vì sao cần phân biệt: phiên 15/08 sửa `additionalProperties: False` mà kết quả
**không đổi một đơn vị nào** — backend giải mã bỏ qua ràng buộc đó. Cả một vòng
đo mất trắng, và nó chỉ lộ ra vì có người đọc tay mẫu đầu ra.

Runbook: [PHIEN_DO_COLAB.md](PHIEN_DO_COLAB.md). **Lần này bỏ được bước sinh dữ
liệu** (dữ liệu còn trên Drive) nên chỉ mất ~1 giờ thay vì 2.

### 🟡 Việc treo #3 — ba phần hạ tầng khai báo mà chưa nối

Ghi thẳng trong `deploy/docker-compose.yml` và khoá bằng
`tests/test_deploy_config.py` — nối xong cái nào thì test đỏ, buộc phải sửa cả
chú thích:

1. **`redis`** — container chạy, **không code nào dùng**. `TASK_REGISTRY` vẫn là
   `OrderedDict` trong RAM. Restart là mất task đang chạy.
2. **`vllm-vision`** — chưa có client HTTP cho vision. Vision vẫn nạp thẳng trong
   tiến trình qua transformers.
3. Vì (2), **`brain` không thật sự chạy được bằng CPU** khi bật nhánh vision. Sơ
   đồ trong compose là đích đến, chưa phải hiện trạng.

Ba thứ này **không chặn phần kế toán** — phần đó không cần model.

### 🟡 Việc treo #4 — RAG chưa có thước đo

571 dòng mã, 70 test đơn vị, **không một chỉ số recall/MRR/faithfulness nào**.
Phương án chi tiết ở [BAN_GIAO_VAN_TAI.md](BAN_GIAO_VAN_TAI.md) mục E.3.

---

## 4. Đụng vào đâu thì gãy

Đây là phần quan trọng nhất khi tiếp quản. Bốn nguyên tắc dưới **không phải sở
thích** — mỗi cái đứng sau một sự cố đã xảy ra.

### P1 — Số tài chính ra từ mã tất định, không từ model

Model làm đúng hai việc: đọc lời người dùng thành cấu trúc, và diễn giải kết quả
thành câu. Nó **không** được tính tiền.

Sự cố 23/08: câu soát hoá đơn có kế hoạch `["vat"]` nhưng `tool_calls = 0` —
model tự nhẩm `5.000.000 + 500.000` rồi so với `6.500.000` trong đầu. Lần đó ra
**đúng**, và đó mới là chỗ nguy: số model tự tính thì lần sau sai cũng không có
gì báo.

Đã chặn ở tầng sampling (`bat_buoc_tool` trong `build_decision_schema`): còn kế
hoạch thì `answer` **không có trong lược đồ**, chỉ còn `tool` và `hoi_lai`.

> Vì sao không cấm tiệt cả hai: "tính thuế giúp tôi" không kèm số tiền mà bị ép
> gọi `vat` thì model phải **bịa** `stated_total`. Đổi một lỗi R1 lấy một lỗi R1
> khác, mà lỗi sau tệ hơn vì số bịa đi qua tool nên trông như "có nguồn".
> `test_van_hoi_lai_duoc_khi_thieu_tham_so` giữ điều này.

### P2 — Dữ liệu khách không rời khỏi chỗ nó cần ở

File tải lên xử lý trong bộ nhớ, **không ghi ra đĩa**.

### P4 — Một nguồn sự thật

Cùng một con số không được khai ở hai chỗ. Đã dính **ba lần**:

| Lần | Hai chỗ khai gì | Hậu quả |
|---|---|---|
| 13/08 | compose đặt `API_TOKEN`, mã đọc `API_AUTH_TOKEN` | Brain triển khai theo README **không kiểm token nào** mà vẫn mở ra Internet |
| 15/08 | trần token production 700/1200/1600, benchmark 1024/2048/2048 | mọi tỷ lệ cắt cụt đo được **đẹp hơn** thứ khách nhận |
| 15/08 | `max_model_len` khai ba nơi ba số (4096 / 8192 / 8192) | thứ đo trên Colab không phải thứ chạy trên máy khách |

Nay ba trần token là **hằng số module** (`MAX_DECISION_TOKENS`,
`MAX_REPORT_TOKENS`, `MAX_WORKFLOW_TOKENS`) và benchmark **import thẳng** thay vì
viết lại. Cửa sổ ngữ cảnh dùng chung `TEXT_MAX_MODEL_LEN`. **Giữ nguyên cách đó.**

### "Chưa biết" khác "bằng 0"

`None` là chưa biết, `0` là biết và bằng không. Gộp hai thứ này là cách tạo ra
báo cáo sai mà nghe rất xuôi tai — báo cáo lãi lỗ sẽ coi mọi mặt hàng chưa nhập
giá vốn là **lãi 100%**.

Thấy ở khắp nơi: `money_impact=None`, `cost: Optional[int]`,
`confidence: None = chưa đo`, `summary.không_phân_tích_được`.

---

## 5. Ba lỗ bảo mật đã vá 15/08 — đừng dựng lại

Quét **từng endpoint qua HTTP thật** (không phải TestClient) lộ ra:

| Endpoint | Vấn đề |
|---|---|
| `GET /tools` | không kiểm token → công khai **16.623 byte** lược đồ nội bộ của 8 tool. Và **không ai gọi nó** — agentic với MCP gọi thẳng `get_tool_defs()` trong tiến trình |
| `GET /api/v1/task/{id}` | không kiểm token, **không kiểm chủ sở hữu** → trả **câu trả lời đầy đủ của AI**: tên khách, mã số thuế, số công nợ |
| mọi endpoint | `require_api_token` gọi **trong thân handler**, nên FastAPI validate thân request trước → người chưa xác thực nhận **422 kèm tên từng trường** thay vì 401 |

**Cách vá:** `auth_guard` thành **dependency cấp router**, gắn một chỗ trong
`main.py`. Endpoint mới không thể quên vì nó không phải nhớ gì cả. Và dependency
chạy **trước** khi validate thân request, nên 401 đến trước 422.

`/api/v1/task/{id}` thêm kiểm chủ sở hữu, trả **404 chứ không 403** — 403 xác
nhận task **có tồn tại**, tức là biến endpoint thành máy dò task id.

> ⚠️ Nếu tách repo (xem bản bàn giao vận tải), **phải mang theo bản vá này**.
> Chép mã cũ mà bỏ nó là dựng lại đúng ba lỗ trên.

---

## 6. Công cụ vận hành mới (từ nhánh benchmark)

Hai file đáng biết trước khi chạy phiên Colab tiếp:

**`offline_training/chay_thu_live.py`** — chạy thử LIVE qua đúng đường Body đi.
Khác `benchmark_integration.py`: bộ kia chấm nội dung, bộ này chỉ hỏi **đường đi
có đúng không**, và trả lời bằng số đo — nó đọc `ai_metrics.jsonl` để thấy
`route` / `tool_plan` / `tool_calls` **thật** của từng lượt.

> Vì sao cần: hoá đơn **vận tải** bị luật từ khoá bắt thành LOGISTICS chỉ vì
> **tên dòng hàng** chứa chữ "vận chuyển" — đó là *dữ liệu trong tờ hoá đơn*,
> không phải *ý định người hỏi*. Người dùng đòi **soát** hoá đơn lại nhận luồng
> **báo giá**. Câu trả lời trông vẫn trôi chảy, nên lỗi này **không tự lộ ra khi
> đọc bằng mắt**.

**`offline_training/bat_lai_brain.py`** — dọn GPU theo PID, nạp bản vá, bật lại
Brain, hâm nóng, mở hầm.

> Chạy bằng `%run -i`, **không phải `!python`** — `%run -i` thực thi trong không
> gian tên notebook nên `BRAIN_URL`/`proc` còn lại sau khi chạy. `!python` thì
> uvicorn chết theo ô.

Kèm theo: `POST /chat` nay **chờ trọn thời gian nạp model**. Trước đó Body bỏ
cuộc ở 60s trong khi request đầu tiên sau mỗi lần Brain khởi động phải chờ 1–3
phút nạp model — hiện ra y hệt "model chết". Body có `BRAIN_CHAT_TIMEOUT_MS` để
nới, nhưng **cách chữa đúng là hâm nóng lúc dựng**.

---

## 7. Thứ tự làm tiếp — đề nghị

| # | Việc | Chặn bởi | Ghi chú |
|---|---|---|---|
| 1 | **Phiên đo Colab** | một buổi GPU L4 | Đóng luôn việc treo #1 và #2. ~1 giờ vì bỏ được bước sinh dữ liệu |
| 2 | **Bộ đo RAG** | không | Không cần GPU. Sinh câu hỏi từ chính tài liệu đã nạp — xem bàn giao mục E.3 |
| 3 | **Kế toán thật rà kết quả** | tìm được người | Thứ duy nhất **không mua được bằng code**. Một buổi là đủ |
| 4 | **Nối `redis` cho TASK_REGISTRY** | không | Chỉ cần khi có nhiều tiến trình. Chưa gấp |
| 5 | **Nối `vllm-vision` qua HTTP** | không | Mở đường chạy Brain bằng CPU |

Việc 1 và 2 **làm song song được** — một cần GPU, một không.

---

## 8. Chỗ tra nhanh

| Cần gì | Đọc đâu |
|---|---|
| Nguyên tắc P1–P4 đầy đủ | `AGENTS.md` |
| Lộ trình sản phẩm, cổng ra từng giai đoạn | `ROADMAP.md` |
| Chạy phiên đo Colab | `PHIEN_DO_COLAB.md` |
| Bàn giao mảng vận tải + 3 mảng nghiên cứu | `BAN_GIAO_VAN_TAI.md` |
| Kết quả soát sổ cho khách | `HOANG_PHAT_SOAT_SO_1108.md` |
| Dữ liệu còn phải xin khách | `HOANG_PHAT_DU_LIEU_CAN_XIN.md` |
| Hợp đồng API với Body | `tests/test_body_contract.py` |
| Ba phần hạ tầng chưa nối | `deploy/docker-compose.yml` đầu file |

---

## 9. Một lời cuối về cách đọc con số ở dự án này

Ba lỗi nghiêm trọng nhất hai tháng qua đều cùng một hình dạng: **hai thứ đúng
riêng lẻ, sai khi ghép, và không có gì phát ra tín hiệu.**

Không test đơn vị nào bắt được. Cả ba lộ ra khi **chạy thật qua HTTP** hoặc khi
**đọc tay đầu ra**.

Cụ thể hơn — ba lần bộ đo cho ra số xấu vì lý do **không nằm ở model**:

- `tool_rate = 0.0` — bộ chấm đọc `row["tool"]` trong khi file ghi `expected_tool`
- extraction và agentic gần bằng 0 — guided decoding im lặng không áp dụng
- agentic 15,8% — `arguments_schema` không đóng object

Nên trước khi kết luận "model kém", đọc ba dòng này trong báo cáo: **`⚠ ... đầu ra
KHÔNG đọc được thành JSON`**, **`⚠ ... CẮT CỤT`**, và **`[chốt chặn]`**. Tỷ lệ
JSON hỏng ≥ 30% gần như luôn là mã, không phải model.

> Đừng tin một lớp phòng thủ chỉ vì đã viết nó. Viết một phép thử chứng minh nó
> **thi hành**, không chỉ **tồn tại**.
