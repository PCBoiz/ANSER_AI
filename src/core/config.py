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
        # Nguồn DUY NHẤT ở prompts.py (đã gộp — không định nghĩa lại chuỗi ở đây).
        self.SYSTEM_CONTEXT = Prompts.SYSTEM_CONTEXT

        # =================================================================
        #  NGÂN SÁCH VRAM — GPU L4 22.5GB (Colab Pro)
        #  Đệm an toàn thiết kế ~19.5GB (chừa ~3GB cho CUDA context/driver/allocator).
        # -----------------------------------------------------------------
        #  Thành phần        Model                      Định dạng    VRAM
        #  Text weights      Qwen2.5-7B-Instruct-AWQ    AWQ 4-bit    ~5.5GB   ┐ trong vLLM
        #  KV-cache+activ.   —                          —            ~6.5GB   ┘ (~12.0GB)
        #  Vision/VLM        Qwen2-VL-2B-Instruct       FP16(bf16)   ~4.5GB   ┐
        #  Embedding         paraphrase-MiniLM-L12-v2   FP16         ~0.5GB   │ ngoài vLLM
        #  Reranker          ms-marco-MiniLM-L-6-v2     FP16         ~0.3GB   │ (~6.3GB)
        #  ChromaDB (hot)    —                          —            ~1.0GB   ┘
        # -----------------------------------------------------------------
        #  TỔNG ~18.3GB < 19.5GB ✓  (vision AWQ thay FP sẽ giảm thêm ~1.5GB)
        # =================================================================

        # --- Brain: Text reasoning (chạy qua vLLM) ---
        self.text_model_id = "Qwen/Qwen2.5-7B-Instruct-AWQ"

        # --- Eye: Vision/VLM (load riêng qua transformers, NẰM NGOÀI ngân sách vLLM) ---
        # Mặc định FP bf16 ~4.5GB — KHỚP cách engine.py hiện load (torch_dtype=bfloat16).
        # Muốn tiết kiệm ~1.5GB: đổi sang "Qwen/Qwen2-VL-2B-Instruct-AWQ"
        #   -> NHƯNG phải sửa engine.py để load theo đường AWQ (bỏ torch_dtype=bfloat16,
        #      dùng quantization config của model), nếu không sẽ load sai/ lỗi.
        self.vision_model_id = "Qwen/Qwen2-VL-2B-Instruct"

        # --- RAG: Embedding + Reranker (FP16, đã nhẹ, giữ nguyên) ---
        self.embedding_model_id = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        self.reranker_model_id = "cross-encoder/ms-marco-MiniLM-L-6-v2"

        # =================================================================
        #  vLLM CONFIG  — ĐỌC KỸ ý nghĩa gpu_memory_utilization
        # -----------------------------------------------------------------
        #  gpu_memory_utilization = PHẦN của TỔNG VRAM mà vLLM được dùng cho
        #  TOÀN BỘ executor = weights + activation + KV-cache.
        #  (KHÔNG phải "chỉ KV-cache" — đây là chỗ hay hiểu sai nhất.)
        #
        #     0.55 × 22.5GB ≈ 12.4GB cho vLLM
        #       ├─ weights 7B-AWQ ........ ~5.5GB
        #       └─ KV-cache + activation . ~6.5GB
        #
        #  Phần (1 − 0.55) ≈ 10GB CÒN LẠI dành cho mọi thứ NGOÀI vLLM
        #  (vision ~4.5GB + embedder/reranker ~0.8GB + chroma ~1GB + overhead).
        #
        #  Thứ tự load của engine.py (vLLM trước, vision sau) VẪN OK, miễn là
        #  (vision + embed + rerank + chroma) < ~10GB. Hiện ~6.3GB nên còn dư.
        #
        #  ⚠️ engine.py PHẢI truyền cả 'quantization' vào LLM(...) thì key dưới
        #     mới có tác dụng (bản hiện tại mới truyền dtype/max_len/gpu_util).
        # =================================================================
        self.vllm_config = {
            "gpu_memory_utilization": 0.55,   # was 0.33 (đã hiểu sai là chỉ-KV-cache)
            "max_model_len": 4096,            # was 8192 — giảm để KV-cache vừa ngân sách L4
            "dtype": "half",                  # AWQ tính toán bằng float16
            "quantization": "awq",            # khai báo rõ, không dựa auto-detect
        }