# Vận hành Brain trên máy thuê — Giai đoạn 1b

> **Đây là blocker cứng của cả dự án.** Colab **cấm** phục vụ traffic (ToS), nên
> tới lúc này Brain chưa có chỗ nào chạy được thật. Không có mục này thì không
> tích hợp được với Body, không đo được gì, không pilot được.

---

## 1. Vấn đề đang sửa

Brain gọi model theo kiểu này ([engine.py:190](../src/core/engine.py#L190)):

```python
outputs = self.llm.generate([prompt], params)
return await loop.run_in_executor(None, _blocking_generate)
```

Ba lỗi chồng lên nhau, và chúng cùng nhau tạo ra đúng hiện tượng *"quá tải rồi treo"*:

| # | Lỗi | Hậu quả |
|---|---|---|
| 1 | `vllm.LLM` là API **chạy lô ngoại tuyến**, gọi với **một** prompt | **Continuous batching bị vô hiệu hoá hoàn toàn** — tính năng đắt giá nhất của vLLM đang không chạy |
| 2 | `run_in_executor(None, …)` dùng thread pool mặc định (~32 luồng) | Tới 32 lệnh `.generate()` chồng lên nhau trên **cùng một** đối tượng LLM |
| 3 | Không có giới hạn đồng thời nào | Tải tăng thì **mọi** request cùng chậm dần đều tới lúc hết giờ |

Điểm 1 quan trọng nhất: **nguyên nhân "quá tải" không phải model yếu**, mà là vLLM
đang chạy sai chế độ.

## 2. Kiến trúc sau khi sửa

```
                     ┌──────────────┐
        ┌───────────▶│  vllm-text   │  GPU ~62%   Qwen3-8B AWQ    :8001
┌───────┴─────┐ HTTP └──────────────┘
│    brain    │      ┌──────────────┐
│  CPU thuần  │─────▶│ vllm-vision  │  GPU ~20%   Qwen2.5-VL-3B   :8002
└───────┬─────┘      └──────────────┘
        │            ┌──────────────┐
        └───────────▶│    redis     │  trạng thái tác vụ nền
                     └──────────────┘
        ▲
        │ cloudflared (tunnel ra Internet, không mở cổng nào)
```

**Brain không cần GPU.** Mọi phần nặng nằm sau HTTP; còn lại là FastAPI + các
engine tất định (pricing, reporting, inventory, calibration) — toàn số học thuần.
Hệ quả thực tế:

- image Brain ~1GB thay vì ~8GB, build và restart tính bằng giây
- sửa một dòng code nghiệp vụ **không** phải nạp lại 6GB weights
- vLLM sập thì `/health` và `/tools/*` vẫn sống

Cái mất: một chặng mạng nội bộ (~1ms), không đáng kể so với hàng trăm ms sinh token.

## 3. Dựng lên

```bash
# Chép model đã quantize từ Drive xuống máy thuê
mkdir -p deploy/models
rclone copy drive:ANSER_AI_Logistics/anser-v3-awq deploy/models/anser-v3-awq

cd deploy
cp .env.example .env && nano .env          # điền API_TOKEN + CLOUDFLARE_TUNNEL_TOKEN
docker compose up -d

# Nạp 6GB weights mất 3-5 phút. Theo dõi:
docker compose logs -f vllm-text
curl -s localhost:8000/health | jq
```

Bật thêm VLM (Giai đoạn 3b):

```bash
docker compose --profile vision up -d
```

## 4. Điều tiết tải

`ConcurrencyGuard` ([serving.py](../src/core/serving.py)) có ba tham số, trả lời ba
câu hỏi khác nhau:

| Tham số | Câu hỏi | Mặc định |
|---|---|---|
| `max_concurrent` | Bao nhiêu request được chạm GPU cùng lúc | 4 |
| `max_queue` | Bao nhiêu request được phép **đứng chờ** | 16 |
| `wait_timeout_s` | Chờ tối đa bao lâu rồi bỏ cuộc | 20 |

Vượt trần hàng đợi → **503 kèm `Retry-After`** ngay lập tức, không nhận vào rồi để đó.

> **Từ chối nhanh là lựa chọn có ý thức, không phải thiếu sót.** Client đã chờ 60
> giây thì thường đã bỏ đi — phục vụ nó lúc đó là lấy mất GPU của một request còn
> đang có người ngồi đợi. Hàng đợi không trần thì hệ thống *trông vẫn sống* mà
> thực chất không ai nhận được gì; đó là kiểu hỏng tệ nhất vì không ai báo động.

## 5. Đo trước, chỉnh sau

**`max_concurrent=4` là điểm khởi đầu thận trọng, KHÔNG phải con số đã đo.** Số
đúng phụ thuộc KV-cache còn trống, mà cái đó phụ thuộc độ dài prompt thực tế.

```bash
# Prompt dài thật, không phải "hello"
hey -n 200 -c 8 -m POST \
    -H "X-API-Token: $API_TOKEN" -H "Content-Type: application/json" \
    -d @prompt_that.json \
    http://localhost:8000/chat

curl -s localhost:8000/health | jq .load.text
```

Đọc kết quả:

| Quan sát | Nghĩa là | Làm gì |
|---|---|---|
| `rejected_total` > 0 mà `peak_in_flight` < `max_concurrent` | Nghẽn ở nơi khác, không phải GPU | Xem log vLLM, kiểm tra `max_model_len` |
| `peak_queued` chạm trần `max_queue` liên tục | Đang thiếu công suất thật | Tăng `max_concurrent`, theo dõi p95 |
| p95 tăng vọt khi tăng `max_concurrent` | Đã vượt sức KV-cache | Hạ lại; đây là trần thật của máy |
| `avg_wait_seconds` cao mà `in_flight` thấp | Từng request quá chậm | Vấn đề ở model/độ dài, không phải đồng thời |

**Cổng ra Giai đoạn 1b:** `p95 ≤ 5s` ở mức đồng thời mục tiêu, và máy dựng lại
được từ số không bằng **một lệnh**.

## 6. Cloudflare Tunnel

Cần: tên miền đã trỏ nameserver về Cloudflare.

1. Zero Trust → Networks → Tunnels → **Create a tunnel** (loại `Cloudflared`)
2. Copy token → `CLOUDFLARE_TUNNEL_TOKEN` trong `.env`
3. Public Hostname: `brain.tenmien.com` → `http://brain:8000`
4. Zero Trust → Access → Application: chỉ cho phép IP của Body

Vì sao tunnel thay vì mở cổng: máy thuê theo giờ **không có IP tĩnh**, và mở
cổng thẳng nghĩa là tự lo tường lửa + chứng chỉ TLS + gia hạn. Tunnel gọi ra
ngoài nên **không cổng nào mở vào**.

## 7. Vấn đề còn lại, đã biết

| Việc | Vì sao chưa làm | Chặn cái gì |
|---|---|---|
| `TASK_REGISTRY` vẫn là dict trong RAM | Redis đã dựng sẵn trong compose, chưa nối code | **`--workers 1`** — nhiều worker sẽ trả lời sai về trạng thái tác vụ |
| `VLLMServerClient` chưa thay đường in-process | Cần GPU thật để đối chiếu output hai đường | Continuous batching chưa thực sự bật |
| `config.py` để `max_model_len=4096` | Lệch với lúc train (8192) | Prompt dài bị cắt âm thầm |
| `text_model_id` mặc định trỏ `anser-retail-v2-awq` | Còn sót từ đời v2 | Quên set env → chạy nhầm **model cũ** mà không báo gì |

Ba dòng cuối là **bẫy im lặng** — không có cái nào ném lỗi. Set env tường minh
trong `.env` là cách chắc chắn nhất để không dính.
