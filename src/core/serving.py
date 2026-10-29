"""
src/core/serving.py — điều tiết tải + client gọi vLLM chế độ server.

VÌ SAO MODULE NÀY TỒN TẠI
-------------------------
Brain hiện gọi model theo kiểu:

    outputs = self.llm.generate([prompt], params)          # engine.py:183
    return await loop.run_in_executor(None, _blocking_generate)

Ba vấn đề chồng lên nhau, và cùng nhau tạo ra đúng hiện tượng "quá tải, treo":

1. `vllm.LLM` là API **chạy lô ngoại tuyến**. Mỗi lần `.generate()` chạy trọn
   một vòng lập lịch cho đúng lô được đưa vào rồi trả về. Đưa vào MỘT prompt
   nghĩa là lô kích thước một — **continuous batching bị vô hiệu hoá hoàn
   toàn**. Đây là tính năng đắt giá nhất của vLLM, và nó đang không chạy.

2. `run_in_executor(None, ...)` dùng thread pool mặc định (~32 luồng ở Python
   3.8+). Nhiều request đồng thời nghĩa là nhiều luồng cùng gọi `.generate()`
   trên **cùng một đối tượng LLM** — thứ không được thiết kế để gọi song song.

3. Không có bất kỳ giới hạn đồng thời nào. Không hàng đợi, không ngưỡng, không
   đường trả lời "bận, thử lại sau". Tải tăng thì mọi request cùng chậm dần
   đều cho tới lúc hết hạn — thay vì phần lớn được phục vụ nhanh và phần thừa
   bị từ chối dứt khoát.

CÁCH SỬA
--------
Chạy vLLM ở **chế độ server** (OpenAI-compatible) trong tiến trình riêng, Brain
gọi qua HTTP. Continuous batching do server lo — đúng chỗ nó được thiết kế để
chạy. Đổi lại một chặng mạng nội bộ (~1ms), lấy về gộp lô thật, nâng cấp vLLM
độc lập với Brain, và đo đạc sẵn có ở `/metrics`.

`ConcurrencyGuard` vẫn cần, kể cả khi đã có server: nó bảo vệ **Brain** khỏi ôm
nhiều request hơn số nó có thể chuyển tiếp, và cho phép trả 503 kèm `Retry-After`
thay vì để client treo.

TỪ CHỐI NHANH TỐT HƠN XẾP HÀNG DÀI
-----------------------------------
Hàng đợi có trần. Vượt trần thì từ chối NGAY, không nhận vào rồi để đó. Client
đã chờ 60 giây thì thường đã bỏ đi — phục vụ nó lúc đó là lấy mất GPU của một
request còn đang có người ngồi đợi. Đây là lựa chọn có ý thức, không phải thiếu sót.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("anser.serving")


class Overloaded(RuntimeError):
    """Brain đang bận hơn mức phục vụ nổi. Ánh xạ sang HTTP 503 + Retry-After."""

    def __init__(self, message: str, retry_after_s: int = 5):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class BackendUnavailable(RuntimeError):
    """Không nối được tới server vLLM (chưa bật, sập, sai URL)."""


class BackendTimeout(RuntimeError):
    """Server vLLM nhận request nhưng không trả lời kịp."""


class BackendError(RuntimeError):
    """Server vLLM trả lỗi có cấu trúc (4xx/5xx)."""


# ---------------------------------------------------------------------------
# Điều tiết tải
# ---------------------------------------------------------------------------

@dataclass
class GuardStats:
    in_flight: int = 0
    queued: int = 0
    admitted: int = 0
    rejected_full: int = 0        # bị từ chối vì hàng đợi đầy
    rejected_timeout: int = 0     # chờ quá lâu trong hàng đợi
    peak_in_flight: int = 0
    peak_queued: int = 0
    wait_seconds_total: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        avg_wait = (
            round(self.wait_seconds_total / self.admitted, 4) if self.admitted else 0.0
        )
        return {
            "in_flight": self.in_flight,
            "queued": self.queued,
            "admitted": self.admitted,
            "rejected_full": self.rejected_full,
            "rejected_timeout": self.rejected_timeout,
            "rejected_total": self.rejected_full + self.rejected_timeout,
            "peak_in_flight": self.peak_in_flight,
            "peak_queued": self.peak_queued,
            "avg_wait_seconds": avg_wait,
        }


class ConcurrencyGuard:
    """
    Giới hạn số request đang chạy, có hàng đợi CÓ TRẦN và thời gian chờ tối đa.

        guard = ConcurrencyGuard(max_concurrent=4, max_queue=16, wait_timeout_s=20)
        async with guard.slot():
            ...gọi model...

    Ba tham số, ba câu hỏi khác nhau:
      - `max_concurrent`: bao nhiêu request được chạm GPU cùng lúc.
      - `max_queue`: bao nhiêu request được phép ĐỨNG CHỜ. Vượt là từ chối ngay.
      - `wait_timeout_s`: chờ tối đa bao lâu rồi bỏ cuộc.

    Không đặt `max_queue` thì hàng đợi dài vô hạn, và độ trễ tăng không giới hạn
    trong khi mọi client vẫn tưởng mình sắp được phục vụ. Đó là kiểu hỏng tệ nhất:
    hệ thống trông vẫn sống mà thực chất không ai nhận được gì.
    """

    def __init__(
        self,
        max_concurrent: int = 4,
        max_queue: int = 16,
        wait_timeout_s: float = 20.0,
        name: str = "text",
    ):
        if max_concurrent < 1:
            raise ValueError("max_concurrent phải >= 1")
        if max_queue < 0:
            raise ValueError("max_queue không được âm")
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self.wait_timeout_s = wait_timeout_s
        self._sem = asyncio.Semaphore(max_concurrent)
        self.stats = GuardStats()

    @property
    def is_saturated(self) -> bool:
        """Đang chạy hết công suất VÀ hàng đợi đã đầy."""
        return (
            self.stats.in_flight >= self.max_concurrent
            and self.stats.queued >= self.max_queue
        )

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        s = self.stats
        if s.queued >= self.max_queue and s.in_flight >= self.max_concurrent:
            s.rejected_full += 1
            raise Overloaded(
                f"Hàng đợi {self.name} đã đầy ({s.queued}/{self.max_queue}), "
                f"{s.in_flight} request đang chạy. Thử lại sau.",
                retry_after_s=max(1, int(self.wait_timeout_s // 2)),
            )

        s.queued += 1
        s.peak_queued = max(s.peak_queued, s.queued)
        started = time.perf_counter()
        acquired = False
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self.wait_timeout_s)
            acquired = True
        except asyncio.TimeoutError:
            s.rejected_timeout += 1
            raise Overloaded(
                f"Chờ quá {self.wait_timeout_s:g}s trong hàng đợi {self.name} "
                "mà chưa tới lượt. Thử lại sau.",
                retry_after_s=max(1, int(self.wait_timeout_s)),
            ) from None
        finally:
            s.queued -= 1

        s.wait_seconds_total += time.perf_counter() - started
        s.admitted += 1
        s.in_flight += 1
        s.peak_in_flight = max(s.peak_in_flight, s.in_flight)
        try:
            yield
        finally:
            s.in_flight -= 1
            if acquired:
                self._sem.release()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "max_queue": self.max_queue,
            "wait_timeout_s": self.wait_timeout_s,
            **self.stats.snapshot(),
        }


# ---------------------------------------------------------------------------
# Client gọi vLLM chế độ server
# ---------------------------------------------------------------------------

@dataclass
class CompletionRequest:
    """
    Tham số sinh text. Giữ TRÙNG TÊN với `SamplingParams` của vLLM để đọc code
    hai bên không phải dịch qua lại.

    `guided_json` là JSON Schema — vLLM ép output khớp lược đồ ngay ở tầng
    sampling, nên JSON hỏng thành BẤT KHẢ THI chứ không phải "hiếm gặp".
    """
    prompt: str
    max_tokens: int = 1024
    temperature: float = 0.1
    repetition_penalty: float = 1.25
    stop: Optional[list[str]] = None
    guided_json: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self, model: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            # vLLM chấp các field ngoài chuẩn OpenAI ngay ở thân request.
            "repetition_penalty": self.repetition_penalty,
        }
        if self.stop:
            payload["stop"] = self.stop
        if self.guided_json:
            payload["guided_json"] = self.guided_json
        return _ap_bat_bien(payload, self.extra, {"model": model, "prompt": self.prompt})


# Phạt lặp mặc định khi sinh tự do. Trùng con số đường trong tiến trình đang
# dùng ở engine.py ("Ngày 7: 1.15 chưa đủ, model vẫn lặp nguyên câu").
#
# Đổi được qua env từ 29/10/2026 để ĐO, mặc định giữ 1,25. BR-05 yêu cầu 9:
# 6/27 câu diễn giải của bản fine-tune suy biến ở mức này — hết ý thì trôi
# sang tiếng Trung/Anh, kê từ đồng nghĩa không lặp ("pull drag haul yank…")
# tới trần 2048 token; bản gốc cùng mức thì không. Chưa biết hạ phạt có đỡ
# không — đo trước, đổi mặc định sau.
REPETITION_PENALTY_TU_DO = float(os.getenv("TEXT_REPETITION_PENALTY", "1.25"))
HEALTH_TIMEOUT_S = 2.0
# Khi bật grammar PHẢI là 1.0. JSON bắt buộc lặp token ("typeVersion",
# "position", dấu ngoặc giữa các node); phạt lặp sẽ cấm đúng các token grammar
# đòi, model bị dồn vào nhánh grammar kém hơn — hỏng im lặng (SRS §3.3 bẫy 3).
REPETITION_PENALTY_GRAMMAR = 1.0


@dataclass
class ChatRequest:
    """
    Tham số cho `/v1/chat/completions` — đường mà SERVER áp chat template.

    Vì sao cần riêng thay vì dựng prompt rồi gọi `complete()`: đường trong tiến
    trình lấy chat template từ tokenizer của chính đối tượng `vllm.LLM`. Đường
    server không có đối tượng đó, nên template phải do server áp (SRS §3.3 bẫy 1).

    Hai bất biến, áp trong `to_payload` SAU `extra` để không gì đè được:

    - `chat_template_kwargs.enable_thinking = False`. Qwen3 mặc định BẬT thinking:
      thiếu cờ này model xổ `<think>` trước mọi câu, trong khi grammar ép `{` là
      token đầu và dataset v3 train không think (bẫy 2).
    - Có `guided_json` thì `repetition_penalty = 1.0` (bẫy 3).

    `repetition_penalty=None` nghĩa là "để client chọn theo việc có grammar hay
    không". Truyền số khác 1.0 cùng `guided_json` thì bị hạ về 1.0 kèm cảnh báo.
    """
    messages: list[dict[str, str]]
    max_tokens: int = 1024
    temperature: float = 0.1
    repetition_penalty: Optional[float] = None
    stop: Optional[list[str]] = None
    guided_json: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages rỗng — không có gì để gửi cho model")
        for m in self.messages:
            if (
                not isinstance(m, dict)
                or m.get("role") not in ("system", "user", "assistant")
                or not isinstance(m.get("content"), str)
            ):
                raise ValueError(f"message sai hình dạng {{role, content}}: {m!r}")

    def repetition_penalty_hieu_luc(self) -> float:
        # `None` = người gọi không chọn -> chọn theo việc có grammar hay không.
        # Bản trước luôn trả 1,25 cho `None`, rồi `_ap_bat_bien` hạ về 1.0 KÈM
        # CẢNH BÁO — tức cảnh báo về một con số không ai đặt. Phiên BR-05
        # 27/10/2026 in dòng đó hơn trăm lần, và production in ở mọi bước của
        # vòng agentic. Cảnh báo chỉ còn khi người gọi CHỦ ĐỘNG đặt số khác 1.0.
        if self.repetition_penalty is None:
            co_grammar = bool(self.guided_json) or any(
                self.extra.get(k) for k in KHOA_GRAMMAR
            )
            return REPETITION_PENALTY_GRAMMAR if co_grammar else REPETITION_PENALTY_TU_DO
        return self.repetition_penalty

    def to_payload(self, model: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in self.messages],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.stop:
            payload["stop"] = self.stop
        payload["repetition_penalty"] = self.repetition_penalty_hieu_luc()
        if self.guided_json:
            payload["guided_json"] = self.guided_json
        payload = _ap_bat_bien(
            payload, self.extra, {"model": model, "messages": payload["messages"]}
        )
        # Bẫy 2: không gì tắt được cờ này, kể cả `extra`.
        kwargs = payload.get("chat_template_kwargs")
        if not isinstance(kwargs, dict):
            if kwargs is not None:
                logger.warning("chat_template_kwargs không phải object (%r) — bỏ", kwargs)
            kwargs = {}
        payload["chat_template_kwargs"] = {**kwargs, "enable_thinking": False}
        return payload


# Mọi cách vLLM nhận để bật ràng buộc giải mã. Có BẤT KỲ khoá nào trong này
# là đang có grammar, dù nó đến từ `guided_json` hay lọt qua `extra` (QA 26/10:
# `extra={"guided_json": ...}` từng gửi grammar kèm phạt lặp 1,25).
KHOA_GRAMMAR = (
    "guided_json", "guided_regex", "guided_choice", "guided_grammar",
    "response_format", "structured_outputs",
)


def _ap_bat_bien(
    payload: dict[str, Any], extra: dict[str, Any], loi: dict[str, Any]
) -> dict[str, Any]:
    """
    Trộn `extra` rồi áp lại bất biến. MỘT hàm cho cả completions và chat.

    - Khoá lõi (`model`, `prompt`/`messages`) không để `extra` đè: `extra=
      {"messages": []}` từng thay mất hội thoại thật.
    - Có grammar ở bất kỳ dạng nào thì `repetition_penalty = 1.0` (bẫy 3).
    """
    if extra:
        payload.update(extra)
    payload.update(loi)
    if any(payload.get(k) for k in KHOA_GRAMMAR):
        rp = payload.get("repetition_penalty")
        if rp not in (None, REPETITION_PENALTY_GRAMMAR):
            logger.warning(
                "repetition_penalty=%s bị hạ về %s vì đang bật ràng buộc giải mã",
                rp, REPETITION_PENALTY_GRAMMAR,
            )
        payload["repetition_penalty"] = REPETITION_PENALTY_GRAMMAR
    return payload


def _chuan_hoa_base_url(url: str) -> str:
    """
    Bỏ `/` cuối và đuôi `/v1`. Client tự nối `/v1/...` cho mọi đường gọi.

    Hai nguồn trong repo ghi hai dạng: AGENTS.md R5 ghi `http://127.0.0.1:8001/v1`,
    compose ghi `http://vllm-text:8001`. Không chuẩn hoá thì làm theo AGENTS sẽ
    gọi `/v1/v1/chat/completions` -> 404 -> `BackendError`, và `/health` của vLLM
    (nằm ở gốc, không dưới `/v1`) cũng trượt theo.
    """
    url = (url or "").strip().rstrip("/")
    # Lặp: `/v1/v1` (dán chồng hai lần) cũng phải về gốc. Không phân biệt hoa thường.
    while url.lower().endswith("/v1"):
        url = url[: -len("/v1")].rstrip("/")
    return url


def _chuoi_tra_ve(x: Any) -> str:
    """`None` -> "" (model chỉ sinh token đặc biệt). Không phải chuỗi -> TypeError -> BackendError."""
    if x is None:
        return ""
    if not isinstance(x, str):
        raise TypeError(f"nội dung trả về là {type(x).__name__}, không phải chuỗi")
    return x.strip()


class VLLMServerClient:
    """
    Gọi vLLM đang chạy chế độ server qua HTTP.

        vllm serve <model> --port 8001 --max-model-len 8192

    Vì sao HTTP thay vì nhúng thẳng `AsyncLLMEngine` vào Brain:

      - Nâng cấp vLLM không kéo theo nâng cấp Brain. Lịch sử repo này cho thấy
        API vLLM/trl trôi liên tục và mỗi lần trôi là một lần gãy.
      - Model nạp một lần, sống độc lập với vòng đời tiến trình web. Brain
        restart không phải nạp lại 6GB weights.
      - Sập một bên không kéo bên kia. Brain vẫn trả lời được `/health` và các
        endpoint tất định (`/tools/*`) khi model chưa sẵn sàng.
      - Đổi model = đổi cờ dòng lệnh, không sửa code.

    Cái mất: một chặng mạng nội bộ. Trên cùng máy là ~1ms, không đáng kể so với
    hàng trăm ms sinh token.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_s: float = 120.0,
        api_key: Optional[str] = None,
        max_connections: int = 32,
    ):
        self.base_url: str = _chuan_hoa_base_url(
            base_url or os.getenv("VLLM_BASE_URL") or ""
        )
        self.model: str = model or os.getenv("VLLM_MODEL") or ""
        self.timeout_s = timeout_s
        # Khoá đọc từ env, KHÔNG nhận qua tham số gọi từ tầng trên (R2b).
        self._api_key = api_key or os.getenv("VLLM_API_KEY", "")
        self._max_connections = max_connections
        self._client: Any = None
        self._client_loop: Any = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def _ensure_client(self):
        """
        Một AsyncClient cho mỗi event loop.

        Engine là singleton, nhưng loop thì không: TestClient, `asyncio.run` trong
        script đo, và tác vụ nền đều có thể chạy trên loop khác nhau. Kết nối
        keep-alive của httpx gắn với loop đã mở nó, dùng lại trên loop khác thì
        ném `RuntimeError: Event loop is closed` — một lỗi thô, không phải
        `Backend*` (QA 26/10). Loop đổi thì bỏ client cũ, dựng client mới.

        Client gắn sẵn từ ngoài (test tiêm transport giả) thì giữ nguyên.
        """
        loop = asyncio.get_running_loop()
        if (
            self._client is not None
            and self._client_loop is not None
            and self._client_loop is not loop
        ):
            # Không `aclose()` được: loop cũ có thể đã đóng. Bỏ để GC dọn.
            self._client = None
        if self._client is None:
            import httpx

            self._client_loop = loop
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_s, connect=5.0),
                limits=httpx.Limits(max_connections=self._max_connections),
            )
        return self._client

    async def health(self) -> dict[str, Any]:
        """Server có sống không. KHÔNG ném ngoại lệ — dùng cho /health của Brain."""
        if not self.configured:
            return {"ok": False, "reason": "chưa cấu hình VLLM_BASE_URL"}
        try:
            client = await self._ensure_client()
            # Ngắn hơn hẳn healthcheck 5s của chính Brain (Dockerfile, compose):
            # vLLM chậm không được kéo Brain thành "unhealthy" theo (QA 26/10).
            resp = await client.get(
                "/health", headers=self._headers(), timeout=HEALTH_TIMEOUT_S
            )
            return {"ok": resp.status_code == 200, "status_code": resp.status_code}
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Một chỗ duy nhất gọi HTTP và ánh xạ lỗi, dùng chung cho `complete` và
        `chat` — hai đường không được phép xử lỗi khác nhau.

        Ném Backend* để tầng trên ánh xạ sang mã HTTP đúng nghĩa.
        """
        if not self.configured:
            raise BackendUnavailable(
                "Chưa cấu hình VLLM_BASE_URL — Brain không biết gọi model ở đâu."
            )
        import httpx

        client = await self._ensure_client()
        try:
            resp = await client.post(path, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise BackendTimeout(
                f"vLLM không trả lời trong {self.timeout_s:g}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise BackendUnavailable(
                f"Không nối được vLLM tại {self.base_url}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise BackendError(f"vLLM trả {resp.status_code}: {resp.text[:400]}")
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("thân trả về không phải object")
            return data
        except ValueError as exc:
            raise BackendError(
                f"vLLM trả nội dung không đọc được: {resp.text[:200]}"
            ) from exc

    async def complete(self, req: CompletionRequest) -> str:
        """Sinh text từ prompt THÔ qua `/v1/completions`. Không áp chat template."""
        data = await self._post("/v1/completions", req.to_payload(self.model))
        try:
            return _chuoi_tra_ve(data["choices"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError(
                f"vLLM trả nội dung không đọc được: {str(data)[:200]}"
            ) from exc

    async def chat(self, req: ChatRequest) -> str:
        """
        Sinh text từ `messages` qua `/v1/chat/completions` — server áp chat template.

        Trả `str` đã `strip()`, cùng hình dạng với `ModelEngine.generate_chat`
        đường trong tiến trình, để tầng gọi không biết mình đang đi đường nào.

        `content` là `null` (model chỉ sinh token đặc biệt) thì trả chuỗi rỗng,
        đúng như đường trong tiến trình làm với `outputs[0].outputs[0].text`.
        """
        data = await self._post("/v1/chat/completions", req.to_payload(self.model))
        try:
            return _chuoi_tra_ve(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError(
                f"vLLM trả nội dung không đọc được: {str(data)[:200]}"
            ) from exc

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._client_loop = None


def guard_from_env(name: str = "text") -> ConcurrencyGuard:
    """
    Dựng guard từ biến môi trường — chỉnh được lúc chạy mà không sửa code.

    Mặc định `max_concurrent=4` — đã đo ở BR-04 (28/10/2026) trên L4 với
    `max_model_len` 32768: 4 request đồng thời chỉ chậm hơn 1 request ~6%. Bốn
    request cùng dài trọn 32k thì vượt bể KV (36.176 token) và vLLM tự xếp
    hàng — chậm, không sập. Máy khác thì đo lại: con số đúng phụ thuộc KV-cache
    còn trống, mà cái đó phụ thuộc độ dài prompt thực tế.
    """
    prefix = f"ANSER_{name.upper()}_"
    return ConcurrencyGuard(
        max_concurrent=int(os.getenv(f"{prefix}MAX_CONCURRENT", "4")),
        max_queue=int(os.getenv(f"{prefix}MAX_QUEUE", "16")),
        wait_timeout_s=float(os.getenv(f"{prefix}WAIT_TIMEOUT_S", "20")),
        name=name,
    )


__all__ = [
    "Overloaded",
    "BackendUnavailable",
    "BackendTimeout",
    "BackendError",
    "GuardStats",
    "ConcurrencyGuard",
    "CompletionRequest",
    "ChatRequest",
    "REPETITION_PENALTY_TU_DO",
    "REPETITION_PENALTY_GRAMMAR",
    "VLLMServerClient",
    "guard_from_env",
]
