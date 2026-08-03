import asyncio
import logging
import os
import threading
import time
from collections import OrderedDict

from src.core.config import Config
from src.core.serving import guard_from_env

logger = logging.getLogger("projecta.engine")


class TaskRegistry:
    """Thread-safe, bounded task registry with FIFO eviction."""

    def __init__(self, max_size: int = 1000):
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, task_id: str):
        with self._lock:
            entry = self._store.get(task_id)
            if entry is None:
                return None
            return dict(entry)  # return a copy

    def set(self, task_id: str, data: dict):
        with self._lock:
            data["_created_at"] = data.get("_created_at", time.time())
            self._store[task_id] = data
            # FIFO eviction when over capacity
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def __contains__(self, task_id: str):
        with self._lock:
            return task_id in self._store


TASK_REGISTRY = TaskRegistry(max_size=1000)

# Số lượt hội thoại tối đa đưa lại vào prompt. 6 lượt (3 cặp hỏi-đáp) đủ cho
# các câu nối tiếp thực tế ("thế xe 3 tấn thì sao?") mà không ăn hết ngân sách
# ngữ cảnh — mỗi lượt cũ đẩy chi phí mọi request sau đó lên.
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "6"))
# Lượt cũ dài hơn mức này bị cắt: câu trả lời workflow JSON có thể vài nghìn
# token, nhét nguyên vào lượt sau là vô ích mà tốn ngữ cảnh.
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "1200"))


def sanitize_history(history: list[dict] | None) -> list[dict]:
    """
    Lọc lịch sử hội thoại trước khi đưa vào chat template.

    Bỏ bản ghi sai vai/rỗng, cắt lượt quá dài, giữ N lượt gần nhất, và đảm bảo
    lượt đầu tiên là 'user' — chat template của Qwen kỳ vọng user/assistant xen
    kẽ, mở đầu bằng 'assistant' làm hỏng cấu trúc ChatML.
    """
    if not history:
        return []

    cleaned = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + " […đã rút gọn]"
        cleaned.append({"role": role, "content": content})

    cleaned = cleaned[-MAX_HISTORY_TURNS:]
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


class ModelEngine:
    """
    Singleton quản lý 2 model trên 1 GPU L4 22.5GB:
      - Text reasoning: Qwen2.5-7B-Instruct-AWQ qua vLLM.
      - Vision/VLM:    Qwen2-VL-2B-Instruct qua transformers (NẰM NGOÀI pool vLLM).

    LƯU Ý KIẾN TRÚC: đây là NGUỒN VISION DUY NHẤT. VisionAgent (vision.py) PHẢI
    gọi engine.generate_vision(...) thay vì tự load Florence-2 riêng — nếu không sẽ
    nạp 2 model vision song song và lãng phí ~4.5GB VRAM.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            inst = super(ModelEngine, cls).__new__(cls)
            try:
                inst._initialize()
            except Exception:
                # Không giữ instance hỏng — lần gọi sau sẽ thử khởi tạo lại
                cls._instance = None
                raise
            cls._instance = inst
        return cls._instance

    def _initialize(self):
        self.env = os.getenv("ENV", "LOCAL").upper()
        self.config = Config()

        # Điều tiết tải. Trước đây KHÔNG có giới hạn nào: `run_in_executor(None, …)`
        # dùng thread pool mặc định (~32 luồng), nên tới 32 lệnh `llm.generate()`
        # có thể chồng lên nhau trên cùng một đối tượng LLM. Đó chính là hiện
        # tượng "quá tải rồi treo" — xem src/core/serving.py.
        self.text_guard = guard_from_env("text")
        self.vision_guard = guard_from_env("vision")

        if self.env == "LOCAL":
            logger.info("Booting LOCAL mock engine (không load model thật)")
            self.llm = None
            self.vision_model = None
            self.vision_processor = None
            logger.info("Mock engine online")
            return

        logger.info("Booting COLAB engine — target GPU L4 22.5GB")

        import torch
        from transformers import AutoModelForVision2Seq, AutoProcessor
        from vllm import LLM

        # 1) Text brain — vLLM.
        #    gpu_memory_utilization là TỔNG ngân sách vLLM (weights + activation + KV-cache).
        vc = self.config.vllm_config
        logger.info(
            "Loading text model: %s (util=%.2f, max_len=%d, quant=%s)",
            self.config.text_model_id,
            vc["gpu_memory_utilization"],
            vc["max_model_len"],
            vc.get("quantization"),
        )
        self.llm = LLM(
            model=self.config.text_model_id,
            gpu_memory_utilization=vc["gpu_memory_utilization"],
            max_model_len=vc["max_model_len"],
            dtype=vc["dtype"],
            # None = để vLLM tự đọc `quantization_config` trong config.json và
            # chọn nhân hợp GPU. Chỉ khác None khi có TEXT_QUANTIZATION.
            quantization=vc.get("quantization"),
            enforce_eager=vc.get("enforce_eager", False),  # fix CUDA graph bug với Qwen
            trust_remote_code=True,
        )

        # 2) Vision eye — transformers, load vào phần VRAM CÒN LẠI ngoài pool vLLM.
        #
        #    `AutoModelForVision2Seq` thay cho `Qwen2VLForConditionalGeneration`
        #    (03/08/2026): lớp cụ thể kia KHÔNG nạp được Qwen2.5-VL — kiến trúc
        #    đó cần `Qwen2_5_VLForConditionalGeneration`. Đóng đinh một lớp cụ
        #    thể nghĩa là mỗi lần đổi model vision lại phải sửa code; `Auto...`
        #    đọc `architectures` trong config.json và chọn đúng lớp.
        #
        #    VRAM bf16: Qwen2-VL-2B ~4,5GB, Qwen2.5-VL-3B ~7,5GB. Cộng cả vLLM
        #    (gpu_memory_utilization là phần GIỮ CHỖ, không phải phần dùng thật)
        #    thì L4 22,5GB rất sát trần — xem RAG_VLM_KE_HOACH.md §B.2.4, và đó
        #    là lý do embedder/reranker của RAG chạy CPU.
        logger.info("Loading vision model: %s", self.config.vision_model_id)
        self.vision_model = AutoModelForVision2Seq.from_pretrained(
            self.config.vision_model_id,
            torch_dtype=torch.bfloat16,
            device_map="cuda",
        )
        self.vision_model.eval()
        self.vision_processor = AutoProcessor.from_pretrained(self.config.vision_model_id)

        logger.info("Unified engine online (text + vision)")

    # ------------------------------------------------------------------
    # TEXT
    # ------------------------------------------------------------------
    async def generate_text(self, prompt, max_tokens=1024, temperature=0.1):
        """Sinh text bất đồng bộ. LOCAL trả mock không block ASGI loop."""
        if self.env == "LOCAL":
            await asyncio.sleep(0.05)
            return '{"mock_response": "LOCAL mock text response."}'

        from vllm import SamplingParams

        loop = asyncio.get_running_loop()
        # KHÔNG thêm no_repeat_ngram_size: đó là tham số của HF transformers,
        # vLLM SamplingParams chưa bao giờ có field này -> TypeError sập MỌI lần
        # gọi /chat trên GPU (fix fdec1d2 nhánh anser-ai, wikiepeidia/ANSER).
        params = SamplingParams(
            temperature=temperature,
            max_tokens=max_tokens,
            repetition_penalty=1.25,     # Ngày 7: 1.15 chưa đủ, model vẫn lặp nguyên câu
        )

        def _blocking_generate():
            outputs = self.llm.generate([prompt], params)
            return outputs[0].outputs[0].text.strip()

        # vLLM generate là blocking -> đẩy ra thread pool để không nghẽn event loop.
        # Guard chặn trước cửa: quá tải thì từ chối dứt khoát (503 + Retry-After)
        # thay vì để mọi request cùng chậm dần đều cho tới lúc hết giờ.
        async with self.text_guard.slot():
            return await loop.run_in_executor(None, _blocking_generate)

    @staticmethod
    def _build_guided_decoding(json_schema: dict):
        """
        Dựng GuidedDecodingParams cho vLLM. Trả None nếu bản vLLM không hỗ trợ.

        Guided decoding ép output khớp JSON Schema ngay ở tầng SAMPLING — token nào
        làm JSON sai schema thì bị loại khỏi phân phối. JSON hỏng trở thành BẤT KHẢ
        THI về cấu trúc, thay vì "hy vọng model làm đúng rồi retry".

        Không raise khi thiếu: bản vLLM cũ vẫn chạy được, chỉ là quay về đường
        validate + retry cũ.
        """
        if not json_schema:
            return None
        try:
            from vllm.sampling_params import GuidedDecodingParams
        except ImportError:
            logger.warning(
                "vLLM không có GuidedDecodingParams — bỏ qua guided decoding, "
                "dùng lại đường validate+retry. Cân nhắc nâng cấp vLLM."
            )
            return None
        return GuidedDecodingParams(json=json_schema)

    async def generate_chat(
        self,
        system: str,
        user: str,
        max_tokens=1024,
        temperature=0.1,
        json_schema: dict | None = None,
        history: list[dict] | None = None,
    ):
        """
        Sinh text theo ĐÚNG định dạng chat của Qwen.
        Tự dựng messages [system, ...history, user] rồi để
        tokenizer.apply_chat_template chèn token ChatML chuẩn.

        `json_schema`: bật guided decoding, ép output khớp schema. Dùng cho nhánh
        sinh workflow và trích xuất hoá đơn.

        `history`: các lượt trước dạng [{"role": "user"|"assistant", "content": ...}].
        Không có nó thì mọi tin nhắn là một phiên độc lập — "thế xe 3 tấn thì
        sao?" không thể hiểu được. Lịch sử đi vào ĐÚNG khe hội thoại của chat
        template, KHÔNG nối vào system prompt (nối tay khiến model coi lời của
        chính nó là chỉ thị hệ thống).
        """
        if self.env == "LOCAL":
            await asyncio.sleep(0.05)
            return '{"mock_response": "LOCAL mock chat response."}'

        from vllm import SamplingParams

        loop = asyncio.get_running_loop()

        # KHÔNG thêm no_repeat_ngram_size: đó là tham số của HF transformers,
        # vLLM SamplingParams chưa bao giờ có field này -> TypeError sập MỌI lần
        # gọi /chat trên GPU (fix fdec1d2 nhánh anser-ai, wikiepeidia/ANSER).
        sampling_kwargs = dict(
            temperature=temperature,
            max_tokens=max_tokens,
            repetition_penalty=1.25,     # Ngày 7: 1.15 chưa đủ, model vẫn lặp nguyên câu
        )

        guided = self._build_guided_decoding(json_schema) if json_schema else None
        if guided is not None:
            sampling_kwargs["guided_decoding"] = guided
            # Grammar đã ép cấu trúc. Giữ repetition_penalty cao sẽ PHẠT các token
            # lặp hợp lệ mà JSON bắt buộc ("typeVersion", "position", dấu ngoặc
            # giữa các node) -> model bị dồn vào nhánh grammar kém hơn. Nới về 1.0.
            sampling_kwargs["repetition_penalty"] = 1.0

        params = SamplingParams(**sampling_kwargs)
        messages = [{"role": "system", "content": system}]
        messages.extend(sanitize_history(history))
        messages.append({"role": "user", "content": user})

        def _blocking_generate():
            tokenizer = self.llm.get_tokenizer()
            # enable_thinking=False: với Qwen3, template mặc định bật thinking —
            # model xổ chuỗi <think> dài trước mọi câu trả lời (tốn token, và
            # dataset v3 train KHÔNG think). Qwen2.5 không có biến này trong
            # template nên kwargs thừa bị bỏ qua — an toàn cho cả hai đời model.
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            outputs = self.llm.generate([prompt], params)
            return outputs[0].outputs[0].text.strip()

        async with self.text_guard.slot():
            return await loop.run_in_executor(None, _blocking_generate)

    # ------------------------------------------------------------------
    # VISION  (method MỚI — để vision_model không còn là "dead load")
    # ------------------------------------------------------------------
    async def generate_vision(self, image_path: str, prompt: str, max_new_tokens: int = 512):
        """
        Chạy Qwen2-VL trên 1 ảnh + prompt, trả về text.
        Bất đồng bộ: inference nặng được đẩy ra thread pool (không block event loop).
        """
        if self.env == "LOCAL":
            await asyncio.sleep(0.05)
            return '{"mock_vision": "LOCAL mock OCR/caption result."}'

        loop = asyncio.get_running_loop()

        def _blocking_vision():
            import torch
            from qwen_vl_utils import process_vision_info

            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": image_path},
                    {"type": "text", "text": prompt},
                ],
            }]
            text = self.vision_processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.vision_processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.vision_model.device)

            with torch.no_grad():
                generated = self.vision_model.generate(**inputs, max_new_tokens=max_new_tokens)
            trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated)]
            return self.vision_processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0].strip()

        # Guard riêng cho vision: ảnh ngốn VRAM khác hẳn text, trộn chung một
        # ngưỡng thì một luồng OCR nặng có thể đói cả nhánh chat.
        async with self.vision_guard.slot():
            return await loop.run_in_executor(None, _blocking_vision)

    # ------------------------------------------------------------------
    # BACKGROUND
    # ------------------------------------------------------------------
    async def background_worker(self, task_id: str, handler_func, *args, **kwargs):
        """Worker nền. handler_func PHẢI là async coroutine. Cập nhật TASK_REGISTRY."""
        try:
            TASK_REGISTRY.set(task_id, {"status": "running"})
            result = await handler_func(*args, **kwargs)
            TASK_REGISTRY.set(task_id, {"status": "completed", "result": result})
        except Exception as e:
            logger.exception("Error in background worker for task %s: %s", task_id, e)
            TASK_REGISTRY.set(task_id, {"status": "failed", "error": str(e)})
