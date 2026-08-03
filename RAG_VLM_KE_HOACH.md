# Kế hoạch RAG + VLM

> Hai khối này nằm ở **Giai đoạn 3** của [ROADMAP.md](ROADMAP.md) — sau khi GĐ 0 chốt
> công thức giá và GĐ 2 chạy được end-to-end. Kế hoạch viết trước để đội Body và
> việc thu thập dữ liệu chạy song song, **không phải để bắt đầu code ngay**.

**Nguyên tắc phân định, quyết định 29/07/2026:**

> **RAG cho văn bản mình *tra cứu*. Tool cho con số mình *tính*.**

Con số đi qua vector DB là con số hết hạn: giá dầu, tồn kho, công nợ, giá cước đều
đổi theo ngày. Nhúng chúng vào embedding nghĩa là trả lời bằng ảnh chụp của quá khứ
mà nghe như hiện tại. Đó là dạng sai nguy hiểm nhất — nghe đúng, không ai kiểm.

---

# Phần A — RAG

## A.1. `knowledge.py` hiện tại: 6 lỗ hổng, 1 cái là chặn

Đã đọc lại toàn bộ [src/core/knowledge.py](src/core/knowledge.py). Bốn lỗ hổng
ARCHITECTURE §13b.3 đã ghi, cộng hai cái mới phát hiện khi đọc kỹ.

### 🔴 A.1.1 — CHẶN: không có cách ly theo khách hàng

```python
self.collection = self.client.get_or_create_collection(name="project_a_docs")
metadatas = [{"source": source} for _ in raw_chunks]
```

Một collection dùng chung, metadata chỉ có `source`. Đây là **SaaS nhiều khách trên
một vector DB không có vách ngăn** — hợp đồng của khách A lọt vào câu trả lời cho
khách B. Vi phạm P2, và là loại lỗi không sửa được sau khi đã xảy ra.

**Phải làm trước mọi thứ khác:** `workspace_id` vào metadata, và **mọi** truy vấn
đều `where={"workspace_id": ...}`. Không có đường tắt "lọc ở tầng trên" — quên một
lần là rò một lần. Cân nhắc mỗi workspace một collection riêng: Chroma chịu được,
và cách ly ở tầng lưu trữ thì không quên được.

### 🟠 A.1.2 — Reranker là model TIẾNG ANH

```python
self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', ...)
self.relevance_threshold = float(os.getenv("KB_RELEVANCE_THRESHOLD", "0.0"))
```

`ms-marco-MiniLM-L-6-v2` huấn luyện trên MS MARCO — **tiếng Anh**. Truy vấn tiếng
Việt cho ra điểm gần như vô nghĩa, mà cả tầng lọc `relevance_threshold` lại dựa vào
đúng điểm đó. Nghĩa là tầng "chống lạc đề" hiện đang lọc bằng một con số ngẫu nhiên.

Embedder thì đúng (`paraphrase-multilingual-MiniLM-L12-v2`), nên lỗi này bị che: kết
quả *có vẻ* hoạt động vì retrieval ổn, chỉ có xếp hạng lại là hỏng.

**Thay bằng** `BAAI/bge-reranker-v2-m3` (đa ngữ, có tiếng Việt) hoặc bỏ hẳn reranker
và dùng điểm hợp nhất dense + BM25. Đo trước khi chọn — đừng đổi model theo cảm tính.

#### Kiểm giấy phép trước khi kiểm điểm số (03/08/2026)

Đây là sản phẩm **bán cho khách**, nên giấy phép là bộ lọc đầu tiên, không phải
điểm benchmark. Rà lại thì có một ứng viên phải loại thẳng:

| Model | Giấy phép | Kết luận |
|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Apache-2.0 | đang dùng — **chỉ tiếng Anh** |
| `jinaai/jina-reranker-v2-base-multilingual` | **CC-BY-NC-4.0** | ❌ **cấm dùng thương mại.** Nhanh và tốt, nhưng muốn dùng thật thì phải mua API của Jina. Loại. |
| `BAAI/bge-reranker-v2-m3` | Apache-2.0 | ✅ an toàn, đa ngữ, ~568M tham số |
| `namdp-ptit/ViRanker` | Apache-2.0 | ✅ **chuyên tiếng Việt**, nền BGE-M3, thắng các baseline đa ngữ trên MMARCO-VI |

**Chọn `ViRanker`, lùi về `bge-reranker-v2-m3` nếu nó trục trặc.** Hai model dùng
chung nền BGE-M3 nên đổi qua lại chỉ là đổi một chuỗi tên, không phải viết lại.

Điểm quan trọng hơn cả việc chọn: cả hai đều trả điểm đã chuẩn hoá về 0–1, khác
`ms-marco` trả logit thô. Nghĩa là `KB_RELEVANCE_THRESHOLD` **lần đầu tiên có ý
nghĩa** — 0,5 là "mô hình nghiêng về liên quan", còn hiện tại ngưỡng 0,0 trên
logit tiếng Anh chấm câu tiếng Việt thì chỉ là một con số cho có.

### 🟠 A.1.7 — Embedder cắt cụt quá nửa mỗi đoạn *(mới, 03/08/2026)*

Mục A.1.2 ở trên viết "embedder thì đúng". **Sai.**

`paraphrase-multilingual-MiniLM-L12-v2` có `max_seq_length = 128` token. Đoạn cắt
ra là **150 từ**; tiếng Việt khoảng 1,5–2 token mỗi từ, tức 225–300 token. Phần
vượt quá 128 **bị cắt bỏ im lặng** — không cảnh báo, không lỗi.

Nghĩa là hơn nửa nội dung mỗi đoạn chưa từng được nhúng. Tìm kiếm dense đang chạy
trên một nửa kho tài liệu, và không có gì trên màn hình cho thấy điều đó.

Kiểm tra một dòng:

```python
from sentence_transformers import SentenceTransformer
print(SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2').max_seq_length)
```

**Thay bằng `BAAI/bge-m3`** (giấy phép MIT): 8192 token, 1024 chiều, đa ngữ mạnh ở
tiếng Việt. Cùng nền với `ViRanker` nên embedder và reranker "hiểu" giống nhau.

### 🟠 A.1.8 — Cắt đoạn KHÔNG THỂ biết bảng, vì cấu trúc đã bị xoá trước đó *(mới)*

```python
def smart_chunk(self, text, chunk_size=150, overlap=30):
    words = word_tokenize(text)          # <-- xoá sạch xuống dòng
    ...
    chunk = " ".join(words[start:end])   # <-- nối lại bằng dấu cách
```

`word_tokenize` trên **cả tài liệu** rồi nối lại bằng dấu cách làm **biến mất mọi
ký tự xuống dòng và ranh giới ô bảng** trước khi cắt một chữ nào.

Nên bảng giá cước vào RAG là mất hẳn cấu trúc: `Hà Nội Đà Nẵng xe tải 5 tấn
12.000.000 Hà Nội TP.HCM container 20ft 31.500.000` thành một dải chữ, và khi cắt
ở giữa thì một đoạn có tuyến còn đoạn kia có số tiền. Model nhận được "12.000.000"
mà không biết của tuyến nào.

Đây là **nguyên nhân gốc**, không phải triệu chứng: giữ nguyên `word_tokenize` thì
mọi cải tiến cắt đoạn đều vô nghĩa. Bảng giá lại đúng là tài liệu giá trị nhất
trong nguồn 1.

**Sửa:** giữ nguyên văn bản thô, cắt theo cấu trúc (dòng trống, tiêu đề, dòng
bảng), chỉ dùng `word_tokenize` cho BM25 — nơi duy nhất thật sự cần tách từ.

### 🟡 A.1.9 — Thư viện RAG chưa cài, `knowledge.py` hiện không import nổi *(mới)*

`chromadb`, `sentence-transformers`, `rank_bm25`, `underthesea` đều có trong
`requirements.txt` nhưng chưa cài ở môi trường phát triển. `dependencies.py` bắt
ngoại lệ và đặt `kb_error`, nên app vẫn sống và `/health` báo `kb_ready: false` —
không ai thấy gì hỏng. Cần nhớ điều này khi đọc `/health`: `kb_ready: false` lâu
nay **không phải** vì chưa nạp tài liệu.

### 🟠 A.1.3 — Không trả nguồn, nên xAI không dùng được

```python
return "\n\n---\n\n".join(best_docs)
```

Trả về một chuỗi phẳng. Chúng ta vừa xây cả nhánh `EXPLAIN_SYSTEM` để mọi câu trả lời
truy ngược được về dữ liệu, nhưng câu trả lời từ RAG thì **không thể trích dẫn** —
không biết đoạn nào từ tài liệu nào.

**Phải trả** `list[{text, source, score, effective_from, chunk_id}]`, và prompt phải
buộc model dẫn nguồn. Với câu hỏi pháp lý, "theo Nghị định 10/2020, Điều 11" khác hẳn
"theo tôi biết".

### 🟠 A.1.4 — Không có ngày hiệu lực

Văn bản pháp luật bị thay thế. NĐ 72/2024 sửa mức VAT; NĐ 10/2020 có thông tư sửa
đổi. Không có `effective_from` / `effective_to` thì model trích một điều khoản **đã
hết hiệu lực** với giọng chắc nịch y hệt.

**Metadata bắt buộc cho tài liệu pháp lý:** `effective_from`, `effective_to`,
`superseded_by`. Truy vấn mặc định lọc theo ngày hôm nay. Tài liệu hết hiệu lực
không xoá — giữ lại để trả lời câu hỏi về quá khứ, nhưng phải gắn nhãn.

### 🟡 A.1.5 — Không cập nhật được tài liệu

```python
existing = self.collection.get(where={"source": filename})
if existing['ids']:
    continue
```

Khớp theo **tên file**. File đã nạp mà nội dung thay đổi thì **không bao giờ** được
nạp lại, và không có đường xoá. Sửa một hợp đồng nghĩa là phải xoá cả DB.

**Sửa:** lưu `content_hash` (SHA của nội dung). Hash đổi → xoá chunk cũ theo
`source`, nạp lại. Có `delete_document(source)`.

### 🟡 A.1.6 — Nạp toàn bộ trong `__init__`, và BM25 dựng lại cả kho

```python
def __init__(...):
    ...
    self.ingest_folder()      # quét đĩa + embed MỌI file
    self._ensure_bm25()

def _ensure_bm25(self):
    all_data = self.collection.get()          # KHÔNG giới hạn
    tokenized_corpus = [word_tokenize(doc.lower()) for doc in self.bm25_docs]
```

Khởi tạo đối tượng kéo theo đọc đĩa và nhúng toàn bộ tài liệu — chặn startup. Và mỗi
lần cờ `_bm25_dirty` bật, toàn bộ kho được kéo vào RAM rồi tách từ lại từ đầu. Với
vài chục tài liệu thì không thấy; với hàng nghìn chunk mỗi lần thêm một file là một
lần đứng máy.

**Sửa:** tách `ingest` khỏi `__init__` (gọi tường minh hoặc job nền), BM25 dựng theo
workspace và cache ra đĩa.

---

## A.2. Nạp gì vào RAG — ba nguồn, xếp theo tỷ lệ giá trị trên công sức

### Nguồn 1 — Tài liệu nội bộ của khách 🥇 *bắt đầu từ đây*

Hợp đồng vận chuyển mẫu, điều khoản với từng nhà xe, quy định bồi thường hàng hư
hỏng/mất mát, chính sách công nợ, quy trình khiếu nại.

**Vì sao đứng đầu:** khách đã có sẵn (miễn phí), không ai ngoài họ có (không đối thủ
nào sao chép được), và đây đúng là thứ một công ty 5 người **hay quên**: *"hợp đồng
với nhà xe Minh Thành cho nợ bao nhiêu ngày?"*, *"hàng vỡ thì bên nào chịu?"*.

Rủi ro: đây là tài liệu nhạy cảm nhất. **Không nạp trước khi xong A.1.1.**

### Nguồn 2 — Thông số sản phẩm dầu nhớt 🥈 *mới, và trực tiếp ra tiền*

Dữ liệu tồn kho cho thấy khách có **119 mã dầu nhớt** ENEOS/Caltex: cấp SAE, tiêu
chuẩn API (CI-4, SN/CF, SP/CF), JASO, dung tích, loại động cơ phù hợp.

Câu hỏi thật của khách hàng cuối: *"xe tải Hino 5 tấn chạy đường dài nên dùng dầu
gì?"*, *"CI-4 với CF-4 khác nhau chỗ nào?"*, *"dầu này thay bao nhiêu km?"*. Đây là
**câu hỏi tra cứu văn bản** — đúng bài của RAG, không phải của tool.

Và nó **trực tiếp ra đơn hàng**: trả lời được là bán được. Trong khi hỏi về hợp đồng
chỉ tiết kiệm thời gian.

Nguồn: catalogue nhà sản xuất (ENEOS/Caltex có bản PDF công khai) + chính tên hàng
trong bảng tồn kho (đã có sẵn cấp SAE và chuẩn API ngay trong tên).

> ⚠️ Chỉ nạp **thông số kỹ thuật**. Giá bán và tồn kho **KHÔNG** — cả hai đổi theo
> ngày và đã có tool riêng (`/tools/inventory-audit`, bảng giá).

### Nguồn 3 — Văn bản pháp luật 🥉 *giá trị cao, công sức cao*

NĐ 10/2020 (kinh doanh vận tải bằng ô tô), TT 12/2020, quy định tải trọng và giấy tờ
vận chuyển, NĐ 72/2024 (VAT), VAS 02 (hàng tồn kho — liên quan trực tiếp phát hiện
"hai phương pháp giá vốn song song").

**Vì sao xếp cuối dù nghe quan trọng nhất:** trả lời sai về pháp luật gây hại thật,
mà văn bản lại thay đổi liên tục. Chỉ nạp **sau khi** xong A.1.4 (ngày hiệu lực) và
A.1.3 (dẫn nguồn). Và phải kèm câu miễn trừ: đây là tra cứu, không phải tư vấn pháp lý.

## A.3. Cái gì TUYỆT ĐỐI không vào RAG

| Dữ liệu | Vì sao không | Đã có đường khác |
|---|---|---|
| Giá dầu | Đổi theo ngày; nhúng = trả lời bằng giá cũ | Tool đồng bộ realtime |
| Tồn kho, công nợ | Đổi theo giờ | SQL qua Body / `/tools/inventory-audit` |
| Giá cước, báo giá | Phải **tính**, không phải nhớ | `compute_quote` |
| Số liệu tài chính | Sai một con số là sai quyết toán | `build_report`, `audit_inventory` |

## A.4. Đo bằng gì

Không có bộ đo thì mọi thay đổi RAG đều là cảm tính. Cần **30-50 câu hỏi thật** kèm
đáp án đúng và tài liệu nguồn, do khách đặt câu hỏi chứ không phải ta tự nghĩ.

Chỉ số: `recall@5` (tài liệu đúng có lọt top-5 không), `citation_accuracy` (nguồn
model dẫn có đúng không), và **`refusal_rate` trên câu hỏi ngoài phạm vi** — trả lời
"không có trong tài liệu" đúng lúc quan trọng ngang trả lời đúng.

---

# Phần B — VLM hoá đơn nhà xe

## B.1. Vì sao việc này quan trọng hơn nó có vẻ

Hoá đơn nhà xe **chính là giá vốn** của mảng vận tải — đúng con số mà `build_report`
đang thiếu và phải tự thú *"chỉ 62% doanh thu có giá vốn"*.

Bên tồn kho đã lấp được nửa lỗ: `inventory.unit_cost_table` cho giá vốn hàng hoá.
Nửa còn lại là cước vận chuyển, và nó chỉ tồn tại trên **ảnh chụp Zalo**. Nối được
VLM thì báo cáo lãi lỗ mới có nghĩa. Hai đường cùng lấp một lỗ.

## B.2. Trạng thái hiện tại và bốn vấn đề

Đọc [src/agents/vision.py](src/agents/vision.py) và [src/core/schemas.py](src/core/schemas.py).

### 🔴 B.2.1 — Lược đồ đang là hoá đơn BÁN LẺ, không phải cước vận tải

```python
class InvoicePayload(BaseModel):
    items: List[InvoiceItem]     # name, price, qty, is_reduced_vat
    total: float
```

`{tên hàng, đơn giá, số lượng}` là hình dạng của hoá đơn siêu thị. Hoá đơn nhà xe có
hình dạng khác hẳn: **nhà xe, MST, số hoá đơn, ngày, biển số xe, điểm đi, điểm đến,
loại xe, khối lượng/số khối, đơn giá cước, các khoản phụ phí, tổng tiền**.

Ép hoá đơn vận tải vào lược đồ bán lẻ thì phần lớn thông tin **rơi mất**, mà mất
"biển số xe" và "tuyến" là mất luôn khả năng đối chiếu với chuyến đã chạy.

Đây là ARCHITECTURE §11.2, giờ đã đủ dữ kiện để viết cụ thể: cần `FreightInvoice`
riêng, không mở rộng `InvoicePayload` — hai loại chứng từ khác nhau về bản chất.

### 🔴 B.2.2 — Đường vision KHÔNG có guided decoding

```python
raw = await self.analyze_image(image_path, task_hint="invoice")
parsed = repair_json(raw, return_objects=True)
```

Lược đồ nằm trong **prompt**, và `repair_json` chữa cháy sau khi model đã sinh xong.
`repair_json` vá được dấu ngoặc thiếu, nhưng **không** thêm được trường bị bỏ sót,
không bỏ được trường bịa ra, không ép được kiểu số.

Nhánh text đã có `GuidedDecodingParams(json=schema)` từ 27/07 (§11.3). Đường vision
bị bỏ quên. Đây là lỗi cùng loại, ở chỗ hậu quả nặng hơn — vì con số ở đây là tiền.

### 🟠 B.2.3 — Không kiểm tra số học

Không có chỗ nào kiểm `tổng các dòng + phụ phí == tổng ghi trên hoá đơn`. Đúng kỷ
luật đã dùng cho `inventory.py`: lệch thì **báo**, đừng tự sửa, và đừng im lặng.

Đây cũng là **tín hiệu chất lượng OCR miễn phí**: hoá đơn nào không cân là hoá đơn
đọc sai, không cần người đối chiếu mới biết.

### 🟡 B.2.4 — Qwen2-VL-2B đã cũ

Qwen2.5-VL-3B mạnh hơn rõ ở tài liệu và OCR. Nâng model là bước rẻ nhất trong cả
phần này.

#### ⚠ Bảng VRAM bản đầu SAI — tính lại theo code đang chạy (03/08/2026)

Bảng cũ ghi "Qwen2.5-VL-3B **4-bit** ~2,5 GB". Nhưng [engine.py](src/core/engine.py#L160)
nạp vision bằng `torch_dtype=torch.bfloat16` — **không lượng tử hoá gì cả**. Và
`gpu_memory_utilization` là **phần trăm tổng VRAM cấp cho vLLM**, không phải phần
vLLM thực dùng; 0,55 nghĩa là vLLM giữ chỗ 12,4 GB bất kể weights chỉ 6 GB.

Tính lại cho đúng thứ code thật sự làm:

| Thành phần | VRAM | Ghi chú |
|---|---|---|
| vLLM (`gpu_memory_utilization=0.55`) | 12,4 GB | giữ chỗ cứng, gồm cả KV cache |
| Qwen2.5-VL-3B **bf16** | ~7,5 GB | 3,75B × 2 byte; bản 2B cũ là ~4,5 GB |
| `bge-m3` (embedder mới) | ~1,2 GB | |
| `ViRanker` (reranker mới) | ~1,2 GB | |
| **Tổng** | **~22,3 GB / 22,5 GB** | **không còn chỗ cho activation lẫn phân mảnh** |

Tức là nâng VLM lên 3B **cộng với** nâng embedder/reranker là **tràn**. Bản đầu
kết luận "còn dư" vì giả định 4-bit cho vision, mà code không làm thế.

**Cách xử lý — chạy embedder + reranker trên CPU.** Truy vấn RAG thưa (vài lượt
mỗi phút, không phải mỗi token), nên đổi ~200 ms độ trễ lấy 2,4 GB VRAM là hời.
Nó còn mở ra hai thứ: Brain chạy được trên máy không GPU (đúng `deploy/Dockerfile`
CPU-only đã có), và VLM có đủ chỗ thở.

Còn tràn thì hạ `gpu_memory_utilization` xuống 0,45 (≈10,1 GB) — Qwen3-8B AWQ chỉ
cần ~6 GB weights, phần còn lại là KV cache, mà `max_model_len` đang là 4096 nên
không cần nhiều.

**Đừng lượng tử hoá vision xuống 4-bit để lấy chỗ.** Việc của nó là đọc chính xác
con số tiền trên tờ giấy nhàu; đó đúng là loại tác vụ mất mát lượng tử hoá gây hại
nhất, và ta lại chưa có bộ ảnh thật nào để đo xem mất bao nhiêu.

## B.3. Thứ tự làm — bốn bước rẻ trước, fine-tune sau cùng

Nguyên tắc: **đo trước, huấn luyện sau**. Fine-tune VLM tốn GPU, tốn nhãn, và có thể
hoàn toàn không cần nếu ba bước rẻ đã đủ.

| # | Việc | Công | Vì sao trước |
|---|---|---|---|
| 1 | Lược đồ `FreightInvoice` đúng nghiệp vụ | Nửa ngày | Không có lược đồ đúng thì đo cái gì cũng vô nghĩa |
| 2 | `guided_json` cho đường vision | Nửa ngày | JSON hỏng thành **bất khả thi**, không phải "hiếm" |
| 3 | Kiểm tra số học + đối chiếu chuyến | 1 ngày | Bắt lỗi OCR tự động, không cần người |
| 4 | Nâng Qwen2.5-VL-3B | Nửa ngày | Rẻ nhất, cải thiện rõ nhất |
| 5 | **ĐO** trên 30-50 hoá đơn thật | 1 ngày | Cổng quyết định |
| 6 | Fine-tune — *chỉ khi bước 5 dưới 90%* | 1 tuần | Có thể không cần |

## B.4. Đo thế nào cho khỏi tự lừa mình

**Theo từng trường, không phải "độ chính xác chung".** Đọc đúng 9/10 trường nghe hay,
nhưng nếu trường sai luôn là "tổng tiền" thì hệ thống vô dụng. Trường bắt buộc đúng:
`tổng tiền`, `nhà xe`, `ngày`. Trường sai còn sửa tay được: `biển số`, `loại xe`.

**Phải gồm hoá đơn xấu.** Xin cả tờ mờ, chụp nghiêng, viết tay, có dấu đè. Đo trên
toàn hoá đơn đẹp rồi kết luận "đạt 95%" là tự lừa mình — thực tế chạy toàn tờ xấu.

**Cổng ra GĐ 3b:** trường bắt buộc đạt ≥ 90% trên tập có cả hoá đơn xấu, **và** mọi
tờ sai đều bị lớp kiểm tra số học bắt được. Vế sau quan trọng ngang vế trước: sai mà
biết mình sai thì còn dùng được, sai mà tự tin thì không.

## B.5. Nhãn miễn phí — hỏi khách trước khi tự đi gán

Nếu khách **đã nhập tay** hoá đơn vào sổ kế toán, thì mỗi ảnh hoá đơn đã có sẵn một
bản ghi đúng tương ứng. Ghép ảnh với dòng sổ theo số hoá đơn là ra **tập huấn luyện
có nhãn, không tốn một đồng gán nhãn nào**.

Đây là câu hỏi số 6 trong [GD0_LAM_VIEC_VOI_KHACH.md](GD0_LAM_VIEC_VOI_KHACH.md) —
hỏi ngay buổi đầu, vì câu trả lời quyết định GĐ 3b tốn một tuần hay một ngày.

---

# Phần C — Thứ tự tổng thể

```
GĐ 0  ─────► chốt công thức giá            ⬅ ĐANG Ở ĐÂY
              │
GĐ 1  ─────► hạ tầng serving + spec Body
              │
GĐ 2  ─────► end-to-end với dữ liệu thật
              │
              ├──► GĐ 3a  RAG    A.1.1 (cách ly) ► A.1.3+A.1.4 ► nguồn 1 ► nguồn 2 ► nguồn 3
              │
              └──► GĐ 3b  VLM    lược đồ ► guided_json ► kiểm số học ► nâng model ► ĐO ► (fine-tune?)
```

**Việc duy nhất nên làm ngay, song song với GĐ 0:** thu thập dữ liệu. Cả hai khối đều
chặn ở dữ liệu chứ không chặn ở code — 30-50 hoá đơn thật, 30-50 câu hỏi thật, và tài
liệu nội bộ của khách. Xin từ buổi làm việc đầu tiên, vì đó là thứ mất nhiều thời gian
chờ nhất.
