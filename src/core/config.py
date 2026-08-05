import os

from src.core.prompts import Prompts


class Config:
    """
    Cấu hình ANSER_AI (Brain) — tối ưu cho Google Colab Pro, GPU L4 22.5GB.
    Mọi con số VRAM dưới đây là ƯỚC TÍNH; phải đo lại bằng nvidia-smi /
    torch.cuda.memory_allocated() trên L4 thật rồi tinh chỉnh.
    """

    def __init__(self):
        # ----------------------------- Paths -----------------------------
        self.PROJECT_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.DATA_DIR = os.path.join(self.PROJECT_ROOT, "src", "data")
        self.DOCS_DIR = os.path.join(self.DATA_DIR, "docs")
        os.makedirs(self.DATA_DIR, exist_ok=True)
        os.makedirs(self.DOCS_DIR, exist_ok=True)

        # --------------------------- Database ----------------------------
        raw_url = os.getenv("DATABASE_URL", "")
        if raw_url.startswith("postgres://"):
            self.DB_URL = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif raw_url.startswith("postgresql://"):
            self.DB_URL = raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        else:
            self.DB_URL = "sqlite:///:memory:"

        # ------------------------ System context -------------------------
        self.SYSTEM_CONTEXT = Prompts.SYSTEM_CONTEXT

        # =================================================================
        #  NGÂN SÁCH VRAM — GPU L4 22.5GB (Colab Pro)
        #  Đệm an toàn ~19.5GB (chừa ~3GB cho CUDA context/driver/allocator).
        # -----------------------------------------------------------------
        #  Thành phần        Model                      Định dạng    VRAM
        #  Text weights      anser-qwen-distill-awq     AWQ 4-bit    ~5.5GB  ┐ trong vLLM
        #  KV-cache+activ.   —                          —            ~6.5GB  ┘ (~12.0GB)
        #  Vision/VLM        Qwen2-VL-2B-Instruct       FP16(bf16)   ~4.5GB  ┐
        #  Embedding         paraphrase-MiniLM-L12-v2   FP16         ~0.5GB  │ ngoài vLLM
        #  Reranker          ms-marco-MiniLM-L-6-v2     FP16         ~0.3GB  │ (~6.3GB)
        #  ChromaDB (hot)    —                          —            ~1.0GB  ┘
        # -----------------------------------------------------------------
        #  TỔNG ~18.3GB < 19.5GB ✓
        # =================================================================

        # --- Brain: Text reasoning (chạy qua vLLM) ---
        # Dùng env var TEXT_MODEL_ID để linh hoạt mọi môi trường:
        #   Colab : export TEXT_MODEL_ID=/content/drive/MyDrive/ANSER_data/anser-qwen-distill-awq
        #   Server: export TEXT_MODEL_ID=/app/models/anser-qwen-distill-awq
        #   Mặc định fallback về HuggingFace Hub nếu không set.
        self.text_model_id = os.getenv(
            "TEXT_MODEL_ID",
            "/content/drive/MyDrive/ANSER_data/anser-retail-v2-awq"
        )

        # --- Eye: Vision/VLM (load riêng qua transformers, ngoài vLLM) ---
        # Qwen2.5-VL-3B thay cho Qwen2-VL-2B (03/08/2026): đọc tài liệu và OCR
        # tốt hơn rõ, mà việc của nó là đọc đúng con số tiền trên tờ giấy nhàu.
        # Đổi bằng env khi VRAM chật: VISION_MODEL_ID=Qwen/Qwen2-VL-2B-Instruct
        self.vision_model_id = os.getenv("VISION_MODEL_ID", "Qwen/Qwen2.5-VL-3B-Instruct")

        # --- RAG: Embedding + Reranker ---
        # Đổi 03/08/2026, ba lý do — xem RAG_VLM_KE_HOACH.md §A.1.2 và §A.1.7:
        #  - MiniLM cũ giới hạn 128 token, cắt cụt IM LẶNG quá nửa mỗi đoạn.
        #  - ms-marco là model TIẾNG ANH, mà điểm của nó lại dùng làm ngưỡng lọc.
        #  - jina-reranker-v2 tốt nhưng CC-BY-NC-4.0: cấm dùng thương mại.
        # bge-m3 (MIT) + ViRanker (Apache-2.0) cùng nền BGE-M3, dùng thương mại được.
        self.embedding_model_id = os.getenv("KB_EMBEDDER_ID", "BAAI/bge-m3")
        self.reranker_model_id  = os.getenv("KB_RERANKER_ID", "namdp-ptit/ViRanker")

        # --- RAG: phạm vi kho tri thức ---
        # Hợp đồng, bảng giá cước, chính sách công nợ là của CẢ CÔNG TY, không
        # của riêng kho hàng nào. Nếu lấy `store_id` (kho đang chọn) làm khoá thì
        # tài liệu nạp lúc đứng ở kho A sẽ vô hình khi hỏi lúc đứng ở kho B —
        # và biểu hiện duy nhất là "không tìm thấy", không có lỗi nào cả.
        #
        # Nên khoá phạm vi tách hẳn khỏi `store_id`. Body dùng đúng giá trị này
        # ở đường nạp tài liệu; hai bên cùng mặc định "default" nên không cấu
        # hình gì thì vẫn khớp nhau.
        self.kb_workspace_id = os.getenv("KB_WORKSPACE_ID", "default").strip() or "default"

        # =================================================================
        #  vLLM CONFIG
        # -----------------------------------------------------------------
        #  gpu_memory_utilization = PHẦN TỔNG VRAM dành cho vLLM
        #     0.55 × 22.5GB ≈ 12.4GB cho vLLM
        #       ├─ weights 7B-AWQ ........ ~5.5GB
        #       └─ KV-cache + activation . ~6.5GB
        #
        #  enforce_eager=True: tắt CUDA graphs — fix lỗi
        #  "Forward context is not set" của vLLM + Qwen trên Colab.
        # =================================================================
        #  quantization / dtype: ĐỂ vLLM TỰ NHẬN từ `quantization_config` trong
        #  config.json của model, thay vì khai cứng "awq" + "half".
        #
        #  Khai cứng vẫn CHẠY (float16 là dtype hợp lệ của nhân awq) nhưng ép
        #  vLLM xuống nhân chậm hơn — chính nó cảnh báo trong log:
        #
        #      Detected that the model can run with awq_marlin, however you
        #      specified quantization=awq explicitly, so forcing awq
        #
        #  Lý do đổi không phải để nhanh hơn, mà để benchmark và lúc serve chạy
        #  CÙNG MỘT nhân. benchmark_v3.py cũng đã bỏ ép (03/08/2026); nếu hai
        #  bên chọn nhân khác nhau thì con số đo được không nói gì về lúc chạy
        #  thật, mà đó lại là toàn bộ mục đích của việc đo.
        #
        #  Ép tay bằng env khi cần (GPU lạ, nhân mới lỗi): TEXT_QUANTIZATION=awq
        #  thì nhớ đặt luôn TEXT_DTYPE=half — nhân awq cũ chỉ nhận float16.
        forced_quant = os.getenv("TEXT_QUANTIZATION", "").strip() or None
        self.vllm_config = {
            "gpu_memory_utilization": 0.55,
            "max_model_len":          4096,
            "dtype": os.getenv("TEXT_DTYPE", "").strip()
                     or ("half" if forced_quant == "awq" else "auto"),
            "quantization":           forced_quant,
            "enforce_eager":          True,   # fix vLLM + Qwen CUDA graph bug
        }
