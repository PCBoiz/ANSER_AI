# deploy/Dockerfile — Brain, KHÔNG có CUDA.
#
# Mọi phần cần GPU đã nằm sau HTTP (vllm-text, vllm-vision). Còn lại là FastAPI
# + các engine tất định. Hệ quả: image ~1GB thay vì ~8GB nếu kéo theo CUDA, và
# sửa một dòng code nghiệp vụ không phải nạp lại 6GB weights.
#
# torch bản CPU vẫn cần cho sentence-transformers (embedder + reranker của RAG).
# Cài từ index CPU riêng để không kéo về ~2.5GB wheel CUDA.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Lớp phụ thuộc tách riêng để cache: đổi code không phải cài lại thư viện.
COPY requirements.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r requirements.txt

COPY src/ ./src/
COPY offline_training/ ./offline_training/

# Chạy bằng user thường: container này nhận traffic từ Internet qua tunnel.
RUN useradd --create-home --uid 10001 anser \
 && mkdir -p /app/data/vector_db \
 && chown -R anser:anser /app
USER anser

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Một worker: các engine tất định không giữ trạng thái, nhưng TASK_REGISTRY
# hiện là dict trong RAM nên nhiều worker sẽ trả lời sai về trạng thái tác vụ.
# Chỉ nâng --workers SAU KHI đã chuyển TASK_REGISTRY sang Redis.
CMD ["uvicorn", "src.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "65"]
