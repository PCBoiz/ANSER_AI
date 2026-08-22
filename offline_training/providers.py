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

    def dien_dat_duoc(self, json_schema: dict) -> bool:
        """Bản dựng có ÉP được lược đồ này không, hay chỉ sinh tự do rồi hy vọng."""
        ...


# ---------------------------------------------------------------------------
# Dựng tham số — hàm THUẦN, test được không cần SDK, không cần mạng
# ---------------------------------------------------------------------------

def tham_so_anthropic(model: str, chat: Chat, json_schema: dict | None,
                      max_tokens: int, effort: str = "",
                      suy_nghi: str = "tat") -> dict[str, Any]:
    """
    Tham số cho `client.messages.create`.

    KHÔNG có `temperature`. Không phải bỏ quên: Claude Opus 5 đã GỠ `temperature`
    /`top_p`/`top_k`, gửi lên là lỗi 400. Benchmark gọi mọi nhánh với
    `temperature=0.0`, nên nếu chuyển thẳng tham số đó sang đây thì cả phiên đo
    hỏng ngay câu đầu — và thông báo lỗi không nói gì về nhiệt độ.

    Cũng KHÔNG có `budget_tokens`: đã gỡ trên Opus 5, dùng `output_config.effort`.

    SUY NGHĨ TẮT MẶC ĐỊNH — và đây là quyết định về PHÉP ĐO, không phải về chất
    lượng. Opus 5 bật suy nghĩ mặc định, mà token suy nghĩ tính vào `max_tokens`.
    Bản vLLM thì chạy `enable_thinking=False`. Để nguyên mặc định thì cùng một
    con số `max_tokens` cho hai bên hai lượng đầu ra khác hẳn — đo ở trần 200
    token, Claude tiêu sạch vào suy nghĩ và trả về CHUỖI RỖNG, rồi bảng kết quả
    ghi "JSON hỏng" (gặp thật 23/08/2026).

    Tắt suy nghĩ làm `max_tokens` hai bên nghĩa như nhau. Muốn đo Claude ở trạng
    thái tốt nhất của nó thì đặt `BENCH_CLAUDE_THINKING=adaptive` — nhưng khi đó
    phải nới trần token, và phải nói rõ là đã nới.

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

    kw["thinking"] = {"type": "adaptive"} if suy_nghi == "adaptive" else {"type": "disabled"}

    cau_hinh: dict[str, Any] = {}
    if json_schema is not None:
        # Lược đồ tới đây PHẢI đóng sẵn — xem `dong_luoc_do`. Chỗ gọi có
        # trách nhiệm lùi về không-ràng-buộc khi không đóng được.
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


# Khoá KIỂM TRA mà structured output của Anthropic không đỡ. Bỏ đi KHÔNG làm
# sai phép đo: chúng ràng buộc GIÁ TRỊ, không ràng buộc HÌNH DẠNG, mà tầng chấm
# điểm vốn đã tự kiểm lại giá trị bằng chính pydantic model của endpoint
# (`_kiem_tham_so` trong benchmark_v3.py). Giữ nguyên phần cấu trúc — `type`,
# `properties`, `required`, `enum`, `anyOf`, `$ref`, `$defs`, `items`.
#
# Danh sách này dựng theo lỗi 400 THẬT, không đoán. Gặp khoá mới thì thông báo
# lỗi in ra sẽ gọi đích danh nó; thêm vào đây rồi chạy lại.
KHOA_KHONG_DO = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties",
})

# Khoá CẤU TRÚC Anthropic không đỡ. KHÁC HẲN nhóm trên: những khoá này quyết
# định model được phép sinh ra HÌNH DẠNG nào, nên bỏ đi là đổi phép đo.
#
# `build_decision_schema` dùng `oneOf` + `not` để cấm model xuất nửa vời — vừa
# gọi tool vừa tuyên bố đáp án. Lọc hai khoá đó là cho phép đúng cái nó sinh ra
# để chặn, rồi vẫn chấm điểm như thể đã chặn.
#
# `anyOf` KHÔNG nằm đây: nó qua được (lược đồ quote có `anyOf` và lỗi 400 gọi
# đích danh `oneOf`, không gọi `anyOf`).
KHOA_CAU_TRUC_KHONG_DO = frozenset({"oneOf", "allOf", "not", "if", "then", "else"})


def dong_luoc_do(luoc_do: dict) -> tuple[dict | None, list[str], set[str]]:
    """
    Đóng mọi `object` trong lược đồ, hoặc trả về lý do không đóng được.

    VÌ SAO PHẢI CÓ HÀM NÀY
    ----------------------
    Anthropic từ chối lược đồ có object không khai `additionalProperties: false`:

        400 output_config.format.schema: For 'object' type,
            'additionalProperties' must be explicitly set to false

    vLLM `guided_json` không đòi thế. Nên cùng một lược đồ, một bên nhận một bên
    không — và cách vá hiển nhiên (đóng hết) là cái bẫy.

    ĐÓNG ĐƯỢC vs KHÔNG ĐÓNG ĐƯỢC
    ----------------------------
    Object CÓ `properties` thì đóng vô hại: nó chỉ cấm trường KHÔNG khai, còn
    trường đã khai vẫn qua.

    Object có `properties` RỖNG là object tự do — đóng nó là cấm sạch. Lược đồ
    workflow n8n có đúng hai chỗ như vậy, và cả hai đều sống còn:

        payload.nodes[].parameters   cấu hình thật của từng node
        payload.connections          khoá là TÊN node, nên động hoàn toàn

    Đóng hai chỗ đó thì mọi workflow sinh ra đều không tham số, không kết nối,
    trượt `validate_workflow` sạch — và bảng kết quả sẽ đọc thành "model kém"
    trong khi thứ hỏng là khung đo.

    Nên: đóng được thì đóng, không đóng được thì **trả về None** để chỗ gọi lùi
    về sinh KHÔNG ràng buộc và nói ra, thay vì lặng lẽ đo một thứ khác.

    KHOÁ CẤU TRÚC
    -------------
    Cùng lý do, một dạng khác: `oneOf`/`not` trong `build_decision_schema` quyết
    định hình dạng hợp lệ. Anthropic không đỡ (`Schema type 'oneOf' is not
    supported`), mà lọc đi là cho phép đúng cái lược đồ sinh ra để cấm. Nên xếp
    chung nhóm "không diễn đạt được" với object tự do.

    Trả về `(lược_đồ, lý_do_không_diễn_đạt_được, khoá_đã_lọc)`. Danh sách lý do
    rỗng nghĩa là đóng thành công.
    """
    mo: list[str] = []
    da_loc: set[str] = set()

    def di(nut, duong: str):
        if isinstance(nut, list):
            return [di(v, f"{duong}[{i}]") for i, v in enumerate(nut)]
        if not isinstance(nut, dict):
            return nut

        ra = {}
        for k, v in nut.items():
            # Chỉ lọc ở tầng TỪ VỰNG lược đồ. Một `properties` tên "pattern" là
            # tên trường của người dùng, không phải khoá kiểm tra — nên không
            # đụng tới nội dung nằm dưới `properties`/`$defs`.
            duoi_tu_vung = not duong.endswith((".properties", ".$defs"))
            if k in KHOA_KHONG_DO and duoi_tu_vung:
                da_loc.add(k)
                continue
            if k in KHOA_CAU_TRUC_KHONG_DO and duoi_tu_vung:
                mo.append(f"khoá cấu trúc {k!r} tại {duong or '$'}")
            ra[k] = di(v, f"{duong}.{k}")

        kieu = ra.get("type")
        la_object = kieu == "object" or (isinstance(kieu, list) and "object" in kieu)
        if la_object and "additionalProperties" not in ra:
            if ra.get("properties"):
                ra["additionalProperties"] = False
            else:
                mo.append(duong or "$")
        return ra

    dong = di(luoc_do, "$")
    return (None, mo, da_loc) if mo else (dong, [], da_loc)


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

    def dien_dat_duoc(self, json_schema: dict) -> bool:
        # xgrammar nhận cả `oneOf`, `not`, object tự do. Có hỏng thì hỏng lúc
        # dựng grammar, và `smoke_test_guided` bắt đúng chỗ đó.
        return True

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

    def dien_dat_duoc(self, json_schema: dict) -> bool:
        # `guided_json` của vLLM nhận nguyên lược đồ. Server KHÔNG phải vLLM thì
        # bỏ qua nó trong im lặng — chốt chặn lược đồ đồ chơi bắt trường hợp đó.
        return True

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
        # Danh nghĩa là structured_output; hạ xuống "hon_hop" nếu có lược đồ
        # không đóng được và phải sinh không ràng buộc. Trường này đi vào file
        # JSON, `compare_runs` đọc để cảnh báo.
        self.rang_buoc = "structured_output"
        # `ANTHROPIC_API_KEY` đọc từ env qua chính SDK — không nhận qua dòng lệnh (R2b).
        self._client = anthropic.Anthropic(max_retries=4)
        self._effort = os.getenv("BENCH_CLAUDE_EFFORT", "").strip()
        self._suy_nghi = os.getenv("BENCH_CLAUDE_THINKING", "tat").strip() or "tat"
        self._da_bao: set[str] = set()
        if self._suy_nghi == "adaptive":
            print("  ⓘ suy nghĩ BẬT (BENCH_CLAUDE_THINKING=adaptive) — token suy nghĩ"
                  " tính vào\n    max_tokens, nên trần token không còn so được với bên"
                  " vLLM.")
        else:
            print("  ⓘ suy nghĩ TẮT — để max_tokens nghĩa như bên vLLM"
                  " (enable_thinking=False).")

    def dien_dat_duoc(self, json_schema: dict) -> bool:
        return dong_luoc_do(json_schema)[0] is not None

    def _chuan_bi_luoc_do(self, json_schema: dict | None) -> dict | None:
        """Đóng lược đồ, hoặc bỏ ràng buộc và NÓI RA — không lặng lẽ đổi phép đo."""
        if json_schema is None:
            return None
        dong, mo, da_loc = dong_luoc_do(json_schema)
        if da_loc and "loc" not in self._da_bao:
            self._da_bao.add("loc")
            print(f"  ⓘ đã lọc khoá lược đồ Anthropic không đỡ: {sorted(da_loc)}")
            print("    Đây là ràng buộc GIÁ TRỊ, không phải hình dạng — tầng chấm điểm"
                  " vẫn tự\n    kiểm lại bằng pydantic model thật của endpoint.")
        if dong is not None:
            return dong

        khoa = ",".join(sorted(mo))
        if khoa not in self._da_bao:
            self._da_bao.add(khoa)
            self.rang_buoc = "hon_hop"
            print("  ⚠ LƯỢC ĐỒ KHÔNG DIỄN ĐẠT ĐƯỢC — sinh KHÔNG ràng buộc cho nhánh này.")
            for d in sorted(mo):
                print(f"      {d}")
            print("    Bỏ những chỗ trên đi là ĐỔI PHÉP ĐO, không phải vá lược đồ:"
                  " object tự do\n    mà đóng lại là cấm sạch nội dung; `oneOf`/`not`"
                  " mà lọc đi là cho phép\n    đúng cái lược đồ sinh ra để cấm.")
            print("    -> nhánh này so với bên vLLM là so KHÔNG CÂN: một bên có grammar,"
                  " một bên không.")
        return None

    def _mot_cau(self, chat: Chat, json_schema: dict | None,
                 max_tokens: int) -> tuple[str, str]:
        resp = self._client.messages.create(
            **tham_so_anthropic(self.model, chat, self._chuan_bi_luoc_do(json_schema),
                                max_tokens, self._effort, self._suy_nghi)
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
    "KHOA_CAU_TRUC_KHONG_DO",
    "doi_ly_do_dung",
    "dong_luoc_do",
    "dung_provider",
    "payload_openai",
    "tach_spec",
    "tham_so_anthropic",
]
