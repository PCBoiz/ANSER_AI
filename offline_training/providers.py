"""
offline_training/providers.py — chỗ cắm model cho benchmark.

VÌ SAO CÓ FILE NÀY
------------------
`benchmark_v3.py` trước đây gọi thẳng `vllm.LLM(...)` trong tiến trình. Nghĩa là
so hai bản chỉ so được hai bộ weights chạy cùng một runtime. Muốn đối chiếu với
một model sau một endpoint — vLLM chế độ server, hay một API bên ngoài — thì
không có chỗ nào để cắm vào.

Tách ra một giao diện duy nhất, ba bản dựng. Năm hàm `score_*` không đổi một
dòng: chúng là hàm thuần `(rows, outputs) -> dict`, không biết model đến từ đâu.
`compare_runs.py` cũng không đổi — nó ghép theo `_id` trên file JSON.

HAI ĐIỀU DỄ LÀM HỎNG SỐ ĐO
--------------------------
1. **`sinh()` phải trả 2-tuple `(văn_bản, lý_do_dừng)`.** `lý_do_dừng == "length"`
   là thứ `score_n8n` và `score_narration` dùng để tách CẮT CỤT khỏi bịa số và
   khỏi JSON hỏng. Trả về list phẳng là gộp ba loại lỗi làm một, và bản báo cáo
   sẽ nói "model bịa số" đúng vào lúc model chỉ chưa nói hết câu.

2. **`rang_buoc` phải nói thật.** Hai model bị ràng buộc bằng hai cơ chế khác
   nhau (grammar phía sampling vs. structured output phía API) thì con số không
   so trực tiếp được. `compare_runs.py` in cảnh báo khi hai lần chạy lệch trường
   này — im lặng ở đây là giấu đúng thứ người đọc cần biết.

DẠNG `--model`
--------------
    Qwen/Qwen3-8B              vLLM trong tiến trình (mặc định, hành vi cũ)
    /content/.../anser-v3-awq  cũng vậy
    openai:http://127.0.0.1:8001/v1#anser-v3    endpoint tương thích OpenAI
    anthropic:claude-opus-5                     API Anthropic

R2: dạng `anthropic:` gửi dữ liệu ra ngoài, nên CHỈ được chạy trên bộ đề tổng
hợp (`generated/*_eval.jsonl`, sinh ngược) hoặc bộ đã ẩn danh
(`sample_data/an_danh.py`). Không bao giờ trên bản xuất sổ sách thật của khách.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

# Số câu gọi song song cho các bản dựng qua mạng. vLLM trong tiến trình tự gộp
# lô nên không dùng số này.
SONG_SONG = int(os.getenv("BENCH_SONG_SONG", "4"))

Chat = list[dict[str, str]]


class NhaCungCap(Protocol):
    """Giao diện duy nhất benchmark biết tới."""

    ten: str
    """Ghi vào trường `model` của file JSON — `compare_runs` in ra làm nhãn A/B."""

    rang_buoc: str
    """`guided_json` | `structured_output` | `khong`. Ghi vào JSON, xem docstring trên."""

    def sinh(self, chats: list[Chat], json_schema: dict | None,
             max_tokens: int, temperature: float) -> tuple[list[str], list[str]]:
        ...


# ---------------------------------------------------------------------------
# Dựng tham số — hàm THUẦN, test được không cần SDK, không cần mạng
# ---------------------------------------------------------------------------

def tham_so_anthropic(model: str, chat: Chat, json_schema: dict | None,
                      max_tokens: int, effort: str = "") -> dict[str, Any]:
    """
    Tham số cho `client.messages.create`.

    KHÔNG có `temperature`. Không phải bỏ quên: Claude Opus 5 đã GỠ `temperature`
    /`top_p`/`top_k`, gửi lên là lỗi 400. Benchmark gọi mọi nhánh với
    `temperature=0.0`, nên nếu chuyển thẳng tham số đó sang đây thì cả phiên đo
    hỏng ngay câu đầu — và thông báo lỗi không nói gì về nhiệt độ.

    Cũng KHÔNG có `budget_tokens`: đã gỡ trên Opus 5, dùng `output_config.effort`.

    Tin nhắn `system` của chat phải tách khỏi `messages` và đưa lên tham số
    `system` riêng — Anthropic không nhận `role: "system"` trong `messages` như
    khuôn OpenAI.
    """
    he_thong = [m["content"] for m in chat if m.get("role") == "system"]
    tin_nhan = [m for m in chat if m.get("role") != "system"]

    kw: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": tin_nhan,
    }
    if he_thong:
        kw["system"] = "\n\n".join(he_thong)

    cau_hinh: dict[str, Any] = {}
    if json_schema is not None:
        cau_hinh["format"] = {"type": "json_schema", "schema": json_schema}
    if effort:
        cau_hinh["effort"] = effort
    if cau_hinh:
        kw["output_config"] = cau_hinh
    return kw


def payload_openai(model: str, chat: Chat, json_schema: dict | None,
                   max_tokens: int, temperature: float) -> dict[str, Any]:
    """
    Thân request cho `/v1/chat/completions`.

    Dùng `chat/completions` chứ không phải `completions` như `src/core/serving.py`:
    ở đây ta có sẵn danh sách tin nhắn, để server tự áp chat template thì không
    phải nạp tokenizer riêng chỉ để dựng chuỗi prompt.

    `guided_json` là phần MỞ RỘNG RIÊNG của vLLM, không thuộc chuẩn OpenAI. Server
    khác sẽ bỏ qua nó trong im lặng — lúc đó `rang_buoc` mà bản dựng này khai báo
    thành sai. Chốt chặn `smoke_test_guided` trong `benchmark_v3.py` bắt đúng
    trường hợp ấy: lược đồ đồ chơi trả về thứ không đọc được thì dừng ngay.
    """
    p: dict[str, Any] = {
        "model": model,
        "messages": chat,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_schema is not None:
        p["guided_json"] = json_schema
    return p


# Anthropic gọi tên lý do dừng khác vLLM. Quy về đúng bộ từ mà tầng chấm điểm
# đang so (`finish == "length"`), nếu không thì CẮT CỤT không bao giờ được nhận
# ra và bị tính thành JSON hỏng.
LY_DO_DUNG = {
    "max_tokens": "length",
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "stop",
    "pause_turn": "stop",
    # Giữ nguyên tên: model TỪ CHỐI trả lời là chuyện khác hẳn với sinh ra rác.
    "refusal": "refusal",
}


def doi_ly_do_dung(stop_reason: str | None) -> str:
    return LY_DO_DUNG.get(stop_reason or "", "stop")


def _bao_cat_cut(finishes: list[str], max_tokens: int) -> None:
    n = sum(1 for f in finishes if f == "length")
    if n:
        print(f"  ⚠ {n}/{len(finishes)} đầu ra bị CẮT CỤT vì chạm trần {max_tokens} token.")
    tu_choi = sum(1 for f in finishes if f == "refusal")
    if tu_choi:
        print(f"  ⚠ {tu_choi}/{len(finishes)} câu bị model TỪ CHỐI trả lời "
              f"(stop_reason=refusal) — KHÔNG phải JSON hỏng.")


# ---------------------------------------------------------------------------
# Bản dựng 1 — vLLM trong tiến trình (hành vi cũ, không đổi)
# ---------------------------------------------------------------------------

class VLLMTrongTienTrinh:
    rang_buoc = "guided_json"

    def __init__(self, model_path: str):
        """
        ÉP `quantization="awq"` LÀ SAI — sửa 03/08/2026 sau khi benchmark chết ngay
        lúc khởi tạo:

            ValueError: torch.bfloat16 is not supported for quantization method awq.
                        Supported dtypes: [torch.float16]

        Hai cái sai chồng nhau. Thứ nhất, nhận dạng bằng cách dò chữ "awq" trong
        ĐƯỜNG DẪN: một thư mục tên bất kỳ có chứa "awq" là bị ép nhầm, còn model AWQ
        để ở thư mục tên khác thì không nhận ra. Thứ hai, ép tay ghi đè lựa chọn của
        vLLM — chính nó đã báo trong log:

            Detected that the model can run with awq_marlin, however you specified
            quantization=awq explicitly, so forcing awq

        `awq_marlin` vừa nhanh hơn vừa chạy được bfloat16; nhân `awq` cũ thì không,
        nên `dtype="auto"` (ra bfloat16 theo config Qwen3) đâm thẳng vào ràng buộc
        float16 rồi nổ.

        Cách đúng: ĐỂ YÊN cho vLLM đọc `quantization_config` trong config.json và tự
        chọn nhân. Nó có đủ thông tin hơn ta — biết cả compute capability của GPU
        đang chạy (awq_marlin cần Ampere trở lên, T4 thì không có).

        `BENCH_QUANT` để ép tay khi cần; ép thì phải hạ dtype xuống float16 vì nhân
        awq cũ chỉ nhận đúng kiểu đó.
        """
        from vllm import LLM

        self.ten = model_path

        forced = os.getenv("BENCH_QUANT", "").strip() or None
        dtype = os.getenv("BENCH_DTYPE", "").strip() or ("float16" if forced == "awq" else "auto")
        if forced:
            print(f"  ép quantization={forced}, dtype={dtype} (BENCH_QUANT)")

        self.llm = LLM(
            model=model_path,
            quantization=forced,
            dtype=dtype,
            max_model_len=8192,
            gpu_memory_utilization=float(os.getenv("BENCH_GPU_UTIL", "0.85")),
            enforce_eager=os.getenv("BENCH_ENFORCE_EAGER", "1") == "1",
            trust_remote_code=True,
        )

    def sinh(self, chats: list[Chat], json_schema: dict | None,
             max_tokens: int, temperature: float) -> tuple[list[str], list[str]]:
        from vllm import SamplingParams

        kwargs: dict[str, Any] = dict(temperature=temperature, max_tokens=max_tokens)
        if json_schema is not None:
            try:
                from vllm.sampling_params import GuidedDecodingParams
                kwargs["guided_decoding"] = GuidedDecodingParams(json=json_schema)
            except ImportError:
                print("  ⚠ vLLM không có GuidedDecodingParams — chạy KHÔNG ràng buộc "
                      "(số liệu sẽ kém hơn lúc serve thật)")
        params = SamplingParams(**kwargs)

        tokenizer = self.llm.get_tokenizer()
        prompts = [
            tokenizer.apply_chat_template(
                chat, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            for chat in chats
        ]
        outputs = self.llm.generate(prompts, params)

        # CẮT CỤT vì chạm trần token là chuyện KHÁC HẲN với sinh ra rác, nhưng cả
        # hai đều làm `json.loads` hỏng rồi thành dict rỗng. vLLM có sẵn
        # `finish_reason`, trước đây ta vứt đi — nên trả kèm để tầng chấm điểm phân
        # biệt được "model làm sai" với "model chưa nói hết câu".
        texts = [o.outputs[0].text.strip() for o in outputs]
        finishes = [o.outputs[0].finish_reason for o in outputs]
        _bao_cat_cut(finishes, max_tokens)
        return texts, finishes


# ---------------------------------------------------------------------------
# Bản dựng 2 — endpoint tương thích OpenAI
# ---------------------------------------------------------------------------

class OpenAITuongThich:
    rang_buoc = "guided_json"

    def __init__(self, base_url: str, model: str, spec: str):
        self.ten = spec
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Khoá đọc từ env, KHÔNG nhận qua tham số dòng lệnh (R2b).
        self._api_key = os.getenv("VLLM_API_KEY", "")

    def _mot_cau(self, chat: Chat, json_schema: dict | None,
                 max_tokens: int, temperature: float) -> tuple[str, str]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload_openai(self.model, chat, json_schema, max_tokens, temperature),
            headers=headers,
            timeout=httpx.Timeout(300.0, connect=10.0),
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"endpoint trả {resp.status_code}: {resp.text[:400]}")
        lua_chon = resp.json()["choices"][0]
        return (lua_chon["message"]["content"] or "").strip(), lua_chon.get("finish_reason") or "stop"

    def sinh(self, chats: list[Chat], json_schema: dict | None,
             max_tokens: int, temperature: float) -> tuple[list[str], list[str]]:
        with ThreadPoolExecutor(max_workers=SONG_SONG) as pool:
            ket_qua = list(pool.map(
                lambda c: self._mot_cau(c, json_schema, max_tokens, temperature), chats
            ))
        texts = [t for t, _ in ket_qua]
        finishes = [f for _, f in ket_qua]
        _bao_cat_cut(finishes, max_tokens)
        return texts, finishes


# ---------------------------------------------------------------------------
# Bản dựng 3 — API Anthropic
# ---------------------------------------------------------------------------

class Anthropic:
    rang_buoc = "structured_output"

    def __init__(self, model: str, spec: str):
        try:
            import anthropic
        except ImportError as exc:
            raise SystemExit(
                "Thiếu gói `anthropic`. Cài: pip install anthropic\n"
                "(đã thêm vào offline_training/requirements_training.txt)"
            ) from exc

        self.ten = spec
        self.model = model
        # `ANTHROPIC_API_KEY` đọc từ env qua chính SDK — không nhận qua dòng lệnh (R2b).
        self._client = anthropic.Anthropic(max_retries=4)
        self._effort = os.getenv("BENCH_CLAUDE_EFFORT", "").strip()

    def _mot_cau(self, chat: Chat, json_schema: dict | None,
                 max_tokens: int) -> tuple[str, str]:
        resp = self._client.messages.create(
            **tham_so_anthropic(self.model, chat, json_schema, max_tokens, self._effort)
        )
        # Lọc theo `type`, không lấy khối đầu tiên: suy nghĩ bật mặc định trên
        # Opus 5 nên khối đầu có thể là `thinking`.
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text, doi_ly_do_dung(resp.stop_reason)

    def sinh(self, chats: list[Chat], json_schema: dict | None,
             max_tokens: int, temperature: float) -> tuple[list[str], list[str]]:
        # `temperature` nhận vào rồi BỎ ĐI — xem `tham_so_anthropic`. Giữ trong
        # chữ ký để mọi bản dựng cùng một giao diện.
        del temperature
        with ThreadPoolExecutor(max_workers=SONG_SONG) as pool:
            ket_qua = list(pool.map(lambda c: self._mot_cau(c, json_schema, max_tokens), chats))
        texts = [t for t, _ in ket_qua]
        finishes = [f for _, f in ket_qua]
        _bao_cat_cut(finishes, max_tokens)
        return texts, finishes


# ---------------------------------------------------------------------------
# Phân giải `--model`
# ---------------------------------------------------------------------------

def tach_spec(spec: str) -> tuple[str, str, str]:
    """
    Tách `--model` thành `(loai, dia_chi, model)`.

    Không có tiền tố thì là đường dẫn/HF id cho vLLM trong tiến trình — nhờ vậy
    mọi lệnh cũ trong notebook và RUNBOOK chạy y nguyên, không phải sửa gì.
    """
    if spec.startswith("openai:"):
        phan = spec[len("openai:"):]
        if "#" not in phan:
            raise SystemExit(
                f"Dạng openai: thiếu tên model. Đúng phải là:\n"
                f"  --model 'openai:<base_url>#<model>'\n"
                f"ví dụ  --model 'openai:http://127.0.0.1:8001/v1#anser-v3'\n"
                f"nhận được: {spec!r}"
            )
        base_url, model = phan.rsplit("#", 1)
        if not base_url or not model:
            raise SystemExit(f"Dạng openai: base_url hoặc model rỗng: {spec!r}")
        return "openai", base_url, model

    if spec.startswith("anthropic:"):
        model = spec[len("anthropic:"):]
        if not model:
            raise SystemExit(
                "Dạng anthropic: thiếu tên model. Đúng phải là:\n"
                "  --model anthropic:claude-opus-5"
            )
        return "anthropic", "", model

    return "vllm", "", spec


def dung_provider(spec: str) -> NhaCungCap:
    loai, dia_chi, model = tach_spec(spec)
    if loai == "openai":
        return OpenAITuongThich(dia_chi, model, spec)
    if loai == "anthropic":
        return Anthropic(model, spec)
    return VLLMTrongTienTrinh(model)


__all__ = [
    "Anthropic",
    "NhaCungCap",
    "OpenAITuongThich",
    "SONG_SONG",
    "VLLMTrongTienTrinh",
    "doi_ly_do_dung",
    "dung_provider",
    "payload_openai",
    "tach_spec",
    "tham_so_anthropic",
]
