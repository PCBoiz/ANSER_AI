# ANSER — sơ đồ kiến trúc (C4)

Phụ lục hình vẽ cho [ARCHITECTURE.md](ARCHITECTURE.md). Tách file riêng vì
ARCHITECTURE.md đã 64KB; **quyết định kiến trúc vẫn nằm ở đó**, file này chỉ vẽ
lại cho dễ nhìn.

Vẽ tay từ code thật, cập nhật 03/08/2026. Mermaid nên xem thẳng được trên GitHub
và sửa cùng commit với code.

> **Vì sao vẽ tay:** Grapuco chưa index hai repo này (chỉ có 2 bản `PE_test`), và
> MCP của nó không có tool tự index — phải thêm repo từ giao diện Grapuco trước.
> Khi có index rồi thì dùng để **đối chiếu** với bản vẽ này chứ không thay thế:
> sơ đồ sinh tự động cho biết code *đang* thế nào, bản vẽ tay nói *vì sao* thế.

Đọc kèm: [RAG_VLM_KE_HOACH.md](RAG_VLM_KE_HOACH.md) ·
[HOANG_PHAT_DU_LIEU_CAN_XIN.md](HOANG_PHAT_DU_LIEU_CAN_XIN.md)

---

## Mức 1 — Bối cảnh

```mermaid
graph TB
    CHU["👤 Chủ doanh nghiệp<br/><i>hỏi số liệu, xem lãi lỗ</i>"]
    NV["👤 Nhân viên kho / kinh doanh<br/><i>nhập xuất, bán hàng</i>"]
    KT["👤 Kế toán<br/><i>xuất sổ từ MISA</i>"]

    ANSER["🟦 <b>ANSER</b><br/>Tự động hoá cho DN vừa và nhỏ<br/><i>phân phối dầu nhớt + vận tải</i>"]

    MISA["📗 MISA / Fast / Bravo"]
    NHAXE["🚚 Nhà xe<br/><i>hoá đơn giấy / Zalo</i>"]
    N8N["⚙️ n8n"]
    DS["🧠 DeepSeek API"]

    CHU --> ANSER
    NV --> ANSER
    KT --> ANSER
    KT -.->|"xuất .xlsx N-X-T"| ANSER
    NHAXE -.->|"ảnh hoá đơn cước"| ANSER
    ANSER -->|"webhook"| N8N
    ANSER -.->|"CHỈ offline lúc sinh dữ liệu train<br/>KHÔNG gọi lúc chạy thật"| DS
    MISA -.-> KT

    classDef sys fill:#1168bd,stroke:#0b4884,color:#fff
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff
    classDef person fill:#08427b,stroke:#052e56,color:#fff
    class ANSER sys
    class MISA,NHAXE,N8N,DS ext
    class CHU,NV,KT person
```

Điều đáng chú ý nhất: DeepSeek nối bằng nét đứt kèm ghi chú "không gọi lúc chạy
thật". Dữ liệu huấn luyện do nó sinh, nhưng khi khách dùng thì không byte số liệu
nào rời hạ tầng của mình (P2). Sổ kho lộ ra giá vốn từng mặt hàng — thứ nhạy cảm
nhất của một nhà phân phối.

---

## Mức 2 — Container

```mermaid
graph TB
    NGUOI["👤 Người dùng"]

    subgraph body["🟩 Body — ANSER_Logistics (Next.js 16)"]
        UI["Dashboard<br/><i>React 19, Tailwind</i>"]
        API["Route API<br/><i>/api/ai/*, /api/products...</i>"]
        STORE["Store<br/><i>Drizzle ORM</i>"]
    end

    subgraph brain["🟦 Brain — AI_ANSER (FastAPI)"]
        REST["REST<br/><i>/chat, /tools/*, /ocr/*</i>"]
        TOOLS["Công cụ TẤT ĐỊNH<br/><i>báo giá, kiểm kho, báo cáo</i>"]
        ENGINE["ModelEngine"]
        RAG["KnowledgeBase<br/><i>tách theo khách</i>"]
    end

    VLLM["⚡ vLLM — Qwen3-8B AWQ"]
    VLM["👁 Qwen2.5-VL-3B"]
    PG[("🐘 Neon Postgres")]
    CHROMA[("📚 Chroma")]
    N8N["⚙️ n8n"]

    NGUOI --> UI --> API --> STORE --> PG
    API -->|"HTTP + X-API-Token"| REST
    REST --> TOOLS & ENGINE & RAG
    ENGINE --> VLLM & VLM
    RAG --> CHROMA
    TOOLS -.->|"MCP bọc REST"| N8N

    classDef c fill:#438dd5,stroke:#2e6295,color:#fff
    classDef db fill:#c4a000,stroke:#8a7300,color:#fff
    classDef ext fill:#999,stroke:#6b6b6b,color:#fff
    class UI,API,STORE,REST,TOOLS,ENGINE,RAG c
    class PG,CHROMA db
    class VLLM,VLM,N8N ext
```

**Brain KHÔNG đọc cơ sở dữ liệu.** Mọi `/tools/*` là hàm thuần qua HTTP: dữ liệu
vào trong request, kết quả trong response. Body lấy dữ liệu rồi chuyển sang. Nhờ
vậy test không cần DB, và khi thuê GPU thì dữ liệu khách không nằm trên máy Brain.

**`/chat` là BẤT ĐỒNG BỘ** — trả `{task_id}` rồi chạy nền. Bản đầu của
`askBrain()` đọc thẳng `answer` từ phản hồi đó; trường ấy không tồn tại nên hàm
trả chuỗi rỗng mà không lỗi gì, UI hiện bong bóng trống. Chỉ chạy thật mới lộ ra.

---

## Mức 3 — Bên trong Brain

```mermaid
graph TB
    subgraph api["Tầng REST — src/api/"]
        MAIN["main.py<br/><i>503 + Retry-After</i>"]
        DEPS["dependencies.py<br/><i>token, danh tính int hoặc str</i>"]
        RCHAT["routes/chat.py"]
        RTOOLS["routes/tools.py<br/><i>manifest + MCP</i>"]
        RDOCS["routes/documents.py<br/><i>/ocr · /ocr/freight</i>"]
    end

    subgraph det["Tầng TẤT ĐỊNH — KHÔNG LLM (P1)"]
        PRICING["pricing.py"]
        CARRIER["carrier_selection.py"]
        REPORT["reporting.py"]
        INV["inventory.py"]
        IMPORT["inventory_import.py<br/><i>3 lớp tự kiểm</i>"]
        FREIGHT["freight_invoice.py<br/><i>kiểm số học</i>"]
    end

    subgraph model["Tầng MODEL"]
        ENGINE["engine.py"]
        SERVING["serving.py<br/><i>ConcurrencyGuard</i>"]
        VISION["agents/vision.py"]
        MANAGER["agents/manager.py"]
    end

    subgraph rag["Tầng RAG"]
        KB["knowledge.py<br/><i>workspace_id BẮT BUỘC</i>"]
        CHUNK["chunking.py<br/><i>giữ cấu trúc bảng</i>"]
    end

    MAIN --> DEPS
    MAIN --> RCHAT & RTOOLS & RDOCS
    RTOOLS --> PRICING & CARRIER & REPORT & IMPORT
    IMPORT --> INV
    RDOCS --> FREIGHT & VISION
    RCHAT --> MANAGER --> KB & ENGINE
    VISION --> ENGINE --> SERVING
    KB --> CHUNK

    classDef d fill:#2e7d32,stroke:#1b5e20,color:#fff
    classDef m fill:#6a1b9a,stroke:#4a148c,color:#fff
    classDef a fill:#438dd5,stroke:#2e6295,color:#fff
    classDef r fill:#ef6c00,stroke:#a34e00,color:#fff
    class PRICING,CARRIER,REPORT,INV,IMPORT,FREIGHT d
    class ENGINE,SERVING,VISION,MANAGER m
    class MAIN,DEPS,RCHAT,RTOOLS,RDOCS a
    class KB,CHUNK r
```

**Màu xanh lá là phần không có LLM.** Mọi con số tài chính do khối đó tính. LLM
chỉ làm hai việc: đọc câu tiếng Việt tự do thành tham số có cấu trúc, và diễn
giải kết quả thành lời.

---

## Luồng 1 — Hỏi đáp (chỗ suýt hỏng im lặng)

```mermaid
sequenceDiagram
    participant U as Người dùng
    participant C as BrainChat.tsx
    participant R as /api/ai/chat
    participant B as brain.ts
    participant BR as Brain /chat

    U->>C: "Doanh thu quý này?"
    C->>R: POST {message}
    R->>R: kiểm phiên + đối chiếu kho có thật
    R->>B: askBrain()
    B->>BR: POST /chat
    BR-->>B: {task_id, status:"processing"}
    Note over B,BR: KHÔNG có `answer` ở đây. Bản đầu đọc thẳng<br/>`answer` → chuỗi rỗng, không lỗi gì.
    loop nhịp giãn dần, có hạn chót
        B->>BR: GET /api/v1/task/{id}
        BR-->>B: {status:"running"}
    end
    BR-->>B: {status:"completed", result:{answer}}
    B->>B: answer rỗng → NÉM lỗi, không nuốt
    B-->>R: {answer, sources, confidence}
    R-->>C: {reply}
```

---

## Luồng 2 — Kiểm sổ kho và nạp giá vốn

```mermaid
sequenceDiagram
    participant KT as Kế toán
    participant P as InventoryAuditPanel
    participant R as /api/ai/inventory-audit
    participant BR as Brain /tools/inventory-import
    participant DB as Postgres

    KT->>P: tải lên .xlsx từ MISA
    P->>R: multipart
    R->>BR: chuyển tiếp (KHÔNG ghi ra đĩa)
    BR->>BR: 3 lớp tự kiểm<br/>đơn giá BQ · dòng Tổng cộng · cân đối

    alt đọc KHÔNG chắc chắn
        BR-->>P: audit=null, unit_costs=[] + lý do
        Note over BR,P: TỪ CHỐI kiểm. Bảng lệch cột vẫn cho ra bản<br/>kiểm sạch bong — số sai nhưng vẫn cân đối<br/>với nhau ở cột bên cạnh.
    else đọc sạch
        BR-->>P: findings + unit_costs (kèm NGUỒN)
        KT->>P: "Xem trước sẽ ghi gì"
        P->>DB: matchCosts() — khớp theo MÃ
        DB-->>P: N ô trống sẽ điền, M ô đã có
        KT->>P: xác nhận
        P->>DB: chỉ ghi ô đang trống
    end
```

Mặc định chỉ điền ô trống vì giá vốn dựng từ phiếu nhập là giá **theo lô**, còn
giá suy từ bảng tổng hợp là **bình quân cả kỳ**. Đè cái sau lên cái trước là đổi
số chính xác lấy số ước lượng.

---

## Luồng 3 — Đọc hoá đơn nhà xe

```mermaid
sequenceDiagram
    participant NV as Nhân viên
    participant R as /ocr/freight
    participant V as VisionAgent
    participant E as ModelEngine
    participant F as freight_invoice.verify

    NV->>R: ảnh hoá đơn
    R->>V: extract_freight_invoice()
    V->>E: generate_vision(json_schema=...)
    E->>E: lm-format-enforcer chỉ cho token<br/>giữ JSON hợp lệ
    E-->>V: JSON
    V-->>R: dict → ép FreightInvoice
    R->>F: verify()
    F->>F: tính LẠI cộng tiền hàng · thuế · tổng
    alt lệch, HOẶC không kiểm được phép nào
        F-->>R: ok=false + bằng chứng số
        R-->>NV: needs_manual_review = true
    else khớp hết
        R-->>NV: dùng được
    end
```

`ok` đòi **cả hai** vế: không sai lệch **và** đã thật sự kiểm được ít nhất một
phép. Thiếu vế sau thì một tấm ảnh mờ đọc ra rỗng sẽ hiện lên như hoá đơn sạch —
không phép kiểm nào thất bại vì chẳng có gì để kiểm.

---

## Phụ thuộc giữa các module Brain

```mermaid
graph LR
    subgraph L4["Tầng 4 — HTTP"]
        main["api/main.py"]
        rtools["routes/tools.py"]
        rdocs["routes/documents.py"]
        rchat["routes/chat.py"]
    end
    subgraph L3["Tầng 3 — điều phối"]
        manager["agents/manager.py"]
        vision["agents/vision.py"]
        engine["core/engine.py"]
        kb["core/knowledge.py"]
    end
    subgraph L2["Tầng 2 — nghiệp vụ thuần"]
        pricing["core/pricing.py"]
        inventory["core/inventory.py"]
        inv_imp["core/inventory_import.py"]
        freight["core/freight_invoice.py"]
        reporting["core/reporting.py"]
    end
    subgraph L1["Tầng 1 — nền"]
        config["core/config.py"]
        serving["core/serving.py"]
        chunking["core/chunking.py"]
        schemas["core/schemas.py"]
    end

    main --> rtools & rdocs & rchat
    rtools --> pricing & inventory & inv_imp & reporting
    rdocs --> freight & vision & schemas
    rchat --> manager
    manager --> kb & engine
    vision --> engine
    engine --> config & serving
    kb --> chunking
    inv_imp --> inventory
    agentic["agents/agentic.py"] --> utils["core/utils.py"]

    classDef l4 fill:#438dd5,stroke:#2e6295,color:#fff
    classDef l3 fill:#6a1b9a,stroke:#4a148c,color:#fff
    classDef l2 fill:#2e7d32,stroke:#1b5e20,color:#fff
    classDef l1 fill:#546e7a,stroke:#37474f,color:#fff
    class main,rtools,rdocs,rchat l4
    class manager,vision,engine,kb,agentic l3
    class pricing,inventory,inv_imp,freight,reporting l2
    class config,serving,chunking,schemas,utils l1
```

**Mũi tên chỉ đi xuống** — và từ 03/08/2026 điều đó **kiểm được**, không còn là
lời hứa: [`tests/test_layering.py`](tests/test_layering.py) duyệt AST toàn bộ
`src/` và đỏ nếu có module nào import ngược tầng. Duyệt AST chứ không grep, vì
lỗi lần trước nằm trong **thân hàm** — grep theo dòng đầu file không thấy.

### Chuyện đã xảy ra: bản đầu của trang này khẳng định sai

Bản đầu viết "mũi tên chỉ đi xuống" trong khi `agents/agentic.py` (T3) đang
import `api/routes/chat.py` (T4) để dùng `_extract_json_block`. Tôi vẽ tay theo
trí nhớ về *thiết kế* nên đã khẳng định điều mình muốn đúng, không phải điều
đang đúng. Bản đồ Grapuco sinh tự động bắt được.

Đã sửa: hàm chuyển sang `core/utils.py` (nó chỉ đếm ngoặc trên một chuỗi, chẳng
liên quan gì HTTP), `chat.py` giữ alias cho 5 chỗ gọi cũ.

### Rà toàn repo: 1 thật trên 5 chỗ Grapuco báo

| Grapuco báo | Thực tế |
|---|---|
| `agentic.py` → `routes/chat.py` | ✅ **thật** — đã sửa |
| `core/integrations.py` → `core/memory.py` | ❌ tiêm phụ thuộc: `memory_manager` truyền vào `__init__` |
| `core/tools.py` → `core/memory.py` | ❌ tiêm phụ thuộc: `memory` là **tham số hàm** |
| `core/workflow_schema.py` → `agents/researcher.py` | ❌ trùng tên hàm `search`, không có tham chiếu nào |

Cạnh `CALLS` của phân tích tĩnh là **manh mối, không phải phán quyết**. Nó không
phân biệt được "gọi qua đối tượng được truyền vào" với "phụ thuộc cứng vào
module" — mà đó chính là ranh giới giữa thiết kế tốt và nợ kỹ thuật. Cạnh
`IMPORTS` thì đáng tin: cả hai lần nó báo đều đúng.

---

## Phụ thuộc ngoài — và vì sao chọn

```mermaid
graph TB
    subgraph text["Đường TEXT"]
        vllm["vllm==0.8.5"]
        tf451["transformers==4.51.3"]
    end
    subgraph vis["Đường ẢNH"]
        autoviz["AutoModelForVision2Seq"]
        lmfe["lm-format-enforcer"]
        jr["json_repair"]
    end
    subgraph ragdep["RAG — chạy CPU"]
        bgem3["BAAI/bge-m3 · MIT"]
        viranker["namdp-ptit/ViRanker · Apache-2.0"]
        chroma["chromadb"]
        bm25["rank_bm25 + underthesea"]
    end
    subgraph loai["❌ ĐÃ LOẠI"]
        jina["jina-reranker-v2<br/>CC-BY-NC — cấm thương mại"]
        minilm["paraphrase-multilingual-MiniLM<br/>giới hạn 128 token"]
        marco["ms-marco-MiniLM<br/>chỉ tiếng Anh"]
        tfl["TensorFlow<br/>USE_TORCH=1 tắt hẳn"]
    end

    vllm -.->|"đòi >=4.51.1<br/>KHÔNG chặn trần trên"| tf451
    tf451 -.->|"import ở mức module<br/>nếu thấy TF"| tfl
    autoviz --> lmfe --> jr
    bgem3 -.-> viranker
    minilm -.->|"thay bằng"| bgem3
    marco -.->|"thay bằng"| viranker
    jina -.->|"loại vì giấy phép"| viranker

    classDef ok fill:#2e7d32,stroke:#1b5e20,color:#fff
    classDef no fill:#b71c1c,stroke:#7f0000,color:#fff
    class vllm,tf451,autoviz,lmfe,jr,bgem3,viranker,chroma,bm25 ok
    class jina,minilm,marco,tfl no
```

### Ba ràng buộc version phải nhớ

| Ràng buộc | Không giữ thì sao |
|---|---|
| `transformers==4.51.3` | Bản 5.x bỏ `all_special_tokens_extended` → vLLM chết lúc dựng tokenizer |
| `USE_TORCH=1` | transformers import TensorFlow → xung đột protobuf → `import vllm` chết |
| Không khai `quantization="awq"` | vLLM bị ép xuống nhân chậm, và `dtype=auto` (bfloat16) đâm vào ràng buộc float16 |

---

## Ngân sách VRAM trên L4 22,5GB

```mermaid
pie showData
    title Phân bổ VRAM (GB)
    "vLLM giữ chỗ (0.55)" : 12.4
    "Qwen2.5-VL-3B bf16" : 7.5
    "Còn trống" : 2.6
```

`gpu_memory_utilization` là phần **giữ chỗ**, không phải phần dùng thật: 0,55
nghĩa là vLLM chiếm 12,4 GB kể cả khi weights chỉ 6 GB.

Cộng thêm `bge-m3` (~1,2 GB) và `ViRanker` (~1,2 GB) là **tràn**. Nên hai model
RAG chạy **CPU**: truy vấn RAG thưa (vài lượt mỗi phút, không phải mỗi token),
đổi ~200 ms độ trễ lấy 2,4 GB VRAM là hời — và nó cho phép Brain chạy trên máy
không GPU.

---

## Trạng thái các giai đoạn

```mermaid
graph LR
    GD0["GĐ 0 — Hiệu chuẩn giá<br/>⏸ chờ dữ liệu khách"]
    GD1["GĐ 1 — Hạ tầng serving<br/>✅ xong"]
    GD2["GĐ 2 — Gắn Brain vào Body<br/>✅ xong"]
    GD3A["GĐ 3a — RAG<br/>✅ code xong<br/>⏸ chờ tài liệu"]
    GD3B["GĐ 3b — VLM<br/>✅ code xong<br/>⏸ chờ ảnh hoá đơn"]
    GD4["GĐ 4 — Đo trên dữ liệu thật<br/>⏸"]

    GD1 --> GD2 --> GD3A & GD3B --> GD4
    GD0 -.->|"song song"| GD4

    classDef done fill:#2e7d32,stroke:#1b5e20,color:#fff
    classDef wait fill:#ef6c00,stroke:#a34e00,color:#fff
    class GD1,GD2 done
    class GD0,GD3A,GD3B,GD4 wait
```

**Cả bốn việc còn lại đều chặn ở DỮ LIỆU, không chặn ở code.** Xem
[HOANG_PHAT_DU_LIEU_CAN_XIN.md](HOANG_PHAT_DU_LIEU_CAN_XIN.md).
