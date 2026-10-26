"""
tests/test_engine_backend.py — BR-03, SRS chu kỳ 01.

`VLLMServerClient` từng được dựng xong, có test, khai trong compose, và KHÔNG
caller nào gọi nó. `test_deploy_config` không bắt được: nó thấy
`os.getenv("VLLM_BASE_URL")` nằm trong `serving.py` rồi kết luận biến đã được
mã dùng. Đọc khác dùng.

Phép thử ở đây dựng một SERVER HTTP THẬT trên 127.0.0.1, trỏ `VLLM_BASE_URL`
vào nó, gọi `generate_chat`, rồi đòi server nhận được request. Không tiêm
transport giả vào client: nếu engine không thật sự đi ra socket thì test đỏ.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.core.engine import CauHinhSai, ModelEngine, chon_backend
from src.core.serving import BackendUnavailable

# ---------------------------------------------------------------------------
# Một chỗ quyết định (yêu cầu 1, 2, 7)
# ---------------------------------------------------------------------------

URL = "http://vllm:8001"


@pytest.mark.parametrize("env,url,ky_vong", [
    ("LOCAL", "", ("mock", "mock")),
    ("LOCAL", URL, ("server", "mock")),
    ("GPU", "", ("in_process", "in_process")),
    ("COLAB", "", ("in_process", "in_process")),
    ("GPU", URL, ("server", "in_process")),       # cấu hình BR-04
    ("COLAB", URL, ("server", "in_process")),
    ("SERVER", URL, ("server", "none")),          # compose
    ("local", "", ("mock", "mock")),              # không phân biệt hoa thường
    ("LOCAL", "   ", ("mock", "mock")),           # chỉ khoảng trắng = không có
])
def test_bang_chon_backend(env, url, ky_vong):
    assert chon_backend(env, url) == ky_vong


def test_env_server_khong_co_url_thi_bao_loi_ngay():
    """Trước BR-03, `SERVER` rơi vào nhánh nạp model lên CUDA trong container Brain."""
    with pytest.raises(CauHinhSai, match="VLLM_BASE_URL"):
        chon_backend("SERVER", "")


@pytest.mark.parametrize("env", ["LCOAL", "PROD", ""])
def test_env_la_bao_loi_thay_vi_lang_le_nap_cuda(env):
    with pytest.raises(CauHinhSai, match="không hợp lệ"):
        chon_backend(env, "")


# ---------------------------------------------------------------------------
# Server giả — HTTP thật
# ---------------------------------------------------------------------------

class _VllmGia:
    """Trả lời đúng hình dạng vLLM OpenAI-compatible, ghi lại mọi request."""

    def __init__(self, noi_dung: str = '  {"tool": "vat"}  ', ma: int = 200):
        self.requests: list[tuple[str, dict]] = []
        gia = self

        class _H(BaseHTTPRequestHandler):
            # Keep-alive như vLLM/uvicorn thật. HTTP/1.0 (mặc định) đóng kết nối
            # sau mỗi request nên che mất lỗi client dùng lại kết nối trên một
            # event loop đã đóng (QA 26/10).
            protocol_version = "HTTP/1.1"

            def _tra(self, ma_http: int, than: dict | None):
                raw = json.dumps(than or {}).encode()
                self.send_response(ma_http)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                gia.requests.append((self.path, {}))
                self._tra(200 if self.path == "/health" else 404, {})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                than = json.loads(self.rfile.read(n) or b"{}")
                gia.requests.append((self.path, than))
                if ma != 200:
                    self._tra(ma, {"error": "loi gia"})
                elif self.path == "/v1/chat/completions":
                    self._tra(200, {"choices": [{"message": {"content": noi_dung}}]})
                elif self.path == "/v1/completions":
                    self._tra(200, {"choices": [{"text": noi_dung}]})
                else:
                    self._tra(404, {})

            def log_message(self, *a):
                pass

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def dong(self):
        self._srv.shutdown()
        self._srv.server_close()

    def cac_duong(self) -> list[str]:
        return [p for p, _ in self.requests]


@pytest.fixture
def vllm_gia():
    gia = _VllmGia()
    yield gia
    gia.dong()


@pytest.fixture
def engine_server(monkeypatch, vllm_gia):
    """`ModelEngine` dựng từ ENV thật, trỏ vào server giả. Singleton được dọn sau."""
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url + "/v1")   # dạng AGENTS.md R5
    monkeypatch.setenv("VLLM_MODEL", "anser-v3-awq")
    eng = ModelEngine()
    yield eng
    monkeypatch.setattr(ModelEngine, "_instance", None)


# ---------------------------------------------------------------------------
# Yêu cầu 5 — đường HTTP được THI HÀNH, không chỉ tồn tại
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_chat_thuc_su_goi_toi_vllm_server(engine_server, vllm_gia):
    assert engine_server.text_backend == "server"
    assert engine_server.llm is None, "đường server không được nạp vllm.LLM"

    schema = {"type": "object", "properties": {"tool": {"type": "string"}}}
    out = await engine_server.generate_chat(
        system="Bạn là trợ lý kế toán.",
        user="Thuế hoá đơn này bao nhiêu?",
        json_schema=schema,
        history=[
            {"role": "assistant", "content": "lượt mở đầu sai vai — phải bị lọc"},
            {"role": "user", "content": "Chào"},
            {"role": "assistant", "content": "Chào bạn"},
        ],
    )

    assert vllm_gia.cac_duong() == ["/v1/chat/completions"], (
        "server giả KHÔNG nhận được request — engine chưa nối VLLMServerClient"
    )
    _, than = vllm_gia.requests[0]
    assert than["model"] == "anser-v3-awq"
    assert [m["role"] for m in than["messages"]] == ["system", "user", "assistant", "user"]
    assert than["messages"][-1]["content"] == "Thuế hoá đơn này bao nhiêu?"
    # Ba bẫy SRS §3.3 — kiểm lại ở tầng engine, trên dây thật
    assert than["chat_template_kwargs"] == {"enable_thinking": False}
    assert than["guided_json"] == schema
    assert than["repetition_penalty"] == 1.0
    # Yêu cầu 3: cùng hình dạng với đường trong tiến trình (`str` đã strip)
    assert out == '{"tool": "vat"}'


@pytest.mark.asyncio
async def test_generate_chat_khong_grammar_giu_phat_lap_va_khong_gui_guided_json(
    engine_server, vllm_gia
):
    await engine_server.generate_chat(system="s", user="u")
    _, than = vllm_gia.requests[0]
    assert "guided_json" not in than
    assert than["repetition_penalty"] == 1.25


@pytest.mark.asyncio
async def test_generate_text_di_completions_prompt_tho(engine_server, vllm_gia):
    out = await engine_server.generate_text("PROMPT THÔ", max_tokens=32, temperature=0.0)
    assert vllm_gia.cac_duong() == ["/v1/completions"]
    _, than = vllm_gia.requests[0]
    assert than["prompt"] == "PROMPT THÔ"
    assert than["max_tokens"] == 32 and than["repetition_penalty"] == 1.25
    assert isinstance(out, str) and out == out.strip()


@pytest.mark.asyncio
async def test_duong_server_van_qua_guard(monkeypatch, vllm_gia):
    """Guard bảo vệ Brain ở cả đường server — chỗ ra 503 + Retry-After."""
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url)
    eng = ModelEngine()
    await eng.generate_chat(system="s", user="u")
    assert eng.text_guard.stats.admitted == 1
    monkeypatch.setattr(ModelEngine, "_instance", None)


@pytest.mark.asyncio
async def test_server_tra_loi_loi_thi_ra_ngoai_le_backend_khong_phai_chuoi_rac(
    monkeypatch,
):
    from src.core.serving import BackendError

    gia = _VllmGia(ma=500)
    try:
        monkeypatch.setattr(ModelEngine, "_instance", None)
        monkeypatch.setenv("ENV", "LOCAL")
        monkeypatch.setenv("VLLM_BASE_URL", gia.url)
        eng = ModelEngine()
        with pytest.raises(BackendError):
            await eng.generate_chat(system="s", user="u")
    finally:
        gia.dong()
        monkeypatch.setattr(ModelEngine, "_instance", None)


# ---------------------------------------------------------------------------
# Không có VLLM_BASE_URL thì KHÔNG chạm mạng
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_khong_co_url_van_la_mock_va_khong_tao_client(monkeypatch):
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    eng = ModelEngine()
    assert (eng.text_backend, eng.vision_backend) == ("mock", "mock")
    assert eng.server is None
    assert "mock_response" in await eng.generate_chat(system="s", user="u")
    monkeypatch.setattr(ModelEngine, "_instance", None)


@pytest.mark.asyncio
async def test_vision_tat_o_env_server_bao_ro_ly_do(monkeypatch, vllm_gia):
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "SERVER")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url)
    eng = ModelEngine()   # không import torch/transformers: vision = none
    assert eng.vision_model is None
    with pytest.raises(BackendUnavailable, match="chu kỳ 02"):
        await eng.generate_vision("anh.png", "đọc hoá đơn")
    monkeypatch.setattr(ModelEngine, "_instance", None)


def test_env_sai_thi_runtime_bao_loi_o_engine_error_khong_sap(monkeypatch):
    """Cấu hình sai phải NHÌN THẤY ĐƯỢC ở /health, không làm Brain chết lúc khởi động."""
    import asyncio

    from src.api.dependencies import RuntimeState

    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "SERVER")      # thiếu VLLM_BASE_URL
    rs = RuntimeState()
    asyncio.run(rs.ensure_text_runtime())
    assert rs.engine is None
    assert "VLLM_BASE_URL" in (rs.engine_error or "")
    monkeypatch.setattr(ModelEngine, "_instance", None)


# ---------------------------------------------------------------------------
# /health — yêu cầu 4, cam kết với Body PHAN_VIEC §6.2
# ---------------------------------------------------------------------------

NAM_TRUONG_BODY_DOC = {"status", "degraded", "engine_ready", "vision_ready", "load"}


def _health_voi_engine(monkeypatch, eng):
    from fastapi.testclient import TestClient

    import src.api.main as main_mod

    monkeypatch.setattr(main_mod.runtime, "engine", eng)
    monkeypatch.setattr(main_mod.runtime, "engine_error", None)
    monkeypatch.setattr(main_mod.runtime, "kb_error", None)
    monkeypatch.setattr(main_mod.runtime, "vision_error", None)
    return TestClient(main_mod.app).get("/health").json()


def test_health_khai_backend_va_vllm_song(monkeypatch, engine_server, vllm_gia):
    body = _health_voi_engine(monkeypatch, engine_server)
    assert NAM_TRUONG_BODY_DOC <= set(body)
    assert body["text_backend"] == "server"
    assert body["vision_backend"] == "mock"
    assert body["vllm_server"]["ok"] is True
    assert body["degraded"] is False
    assert "/health" in vllm_gia.cac_duong()


def test_health_vllm_chet_thi_degraded_ma_brain_van_tra_loi(monkeypatch):
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:9")   # cổng discard, không ai nghe
    eng = ModelEngine()
    body = _health_voi_engine(monkeypatch, eng)
    assert body["status"] == "ok"
    assert body["engine_ready"] is True
    assert body["vllm_server"]["ok"] is False
    assert body["degraded"] is True
    monkeypatch.setattr(ModelEngine, "_instance", None)


def test_health_mock_khong_co_truong_vllm_server(monkeypatch):
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    body = _health_voi_engine(monkeypatch, ModelEngine())
    assert body["text_backend"] == "mock"
    assert "vllm_server" not in body
    monkeypatch.setattr(ModelEngine, "_instance", None)


# ---------------------------------------------------------------------------
# NFR-06 — không đường dẫn máy ai trong src/, không lặng lẽ nạp model cũ
# ---------------------------------------------------------------------------

def test_khong_con_duong_dan_drive_trong_src():
    """Lệnh nghiệm thu NFR-06: `grep -rn "content/drive" src/` phải rỗng."""
    from pathlib import Path

    goc = Path(__file__).resolve().parents[1] / "src"
    trung = [
        f"{p.relative_to(goc.parent)}:{i}"
        for p in goc.rglob("*.py")
        for i, dong in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "content/drive" in dong
    ]
    assert not trung, f"đường dẫn Drive còn trong src/: {trung}"


def test_nap_trong_tien_trinh_thieu_text_model_id_thi_bao_ro(monkeypatch):
    """Mặc định cũ trỏ vào `anser-retail-v2-awq` đã nghỉ hưu. Nay thiếu biến là báo lỗi."""
    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "GPU")
    monkeypatch.delenv("TEXT_MODEL_ID", raising=False)
    # Không nạp vision: chỉ kiểm đường text, không đụng torch.
    monkeypatch.setattr(ModelEngine, "_nap_vision_trong_tien_trinh", lambda self: None)
    with pytest.raises(CauHinhSai, match="TEXT_MODEL_ID"):
        ModelEngine()
    assert ModelEngine._instance is None, "không được giữ instance hỏng"


# ---------------------------------------------------------------------------
# Các ca QA tái hiện ngày 26/10
# ---------------------------------------------------------------------------

def test_engine_dung_qua_nhieu_event_loop_khong_vo(monkeypatch, vllm_gia):
    """
    Engine là singleton, loop thì không. Trước bản sửa: asyncio.run lần 2 ném
    `RuntimeError: Event loop is closed` vì client giữ kết nối keep-alive của loop cũ.
    """
    import asyncio

    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "LOCAL")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url)
    eng = ModelEngine()
    for _ in range(3):
        assert asyncio.run(eng.generate_chat(system="s", user="u")) == '{"tool": "vat"}'
    assert vllm_gia.cac_duong().count("/v1/chat/completions") == 3
    monkeypatch.setattr(ModelEngine, "_instance", None)


def test_health_lien_tiep_qua_nhieu_testclient_van_ok(monkeypatch, engine_server):
    for _ in range(3):
        body = _health_voi_engine(monkeypatch, engine_server)
        assert body["vllm_server"]["ok"] is True, body["vllm_server"]


def test_vllm_cham_khong_keo_health_cua_brain_qua_5s(monkeypatch):
    """Healthcheck của chính Brain (Dockerfile, compose) hết giờ ở 5s."""
    import time

    gia = _VllmGia()
    goc = gia._srv.RequestHandlerClass.do_GET

    def cham(self):
        time.sleep(4)
        goc(self)

    gia._srv.RequestHandlerClass.do_GET = cham
    try:
        monkeypatch.setattr(ModelEngine, "_instance", None)
        monkeypatch.setenv("ENV", "LOCAL")
        monkeypatch.setenv("VLLM_BASE_URL", gia.url)
        t0 = time.perf_counter()
        body = _health_voi_engine(monkeypatch, ModelEngine())
        assert time.perf_counter() - t0 < 3.0
        assert body["vllm_server"]["ok"] is False and body["degraded"] is True
    finally:
        gia.dong()
        monkeypatch.setattr(ModelEngine, "_instance", None)


def test_env_server_health_khong_bao_vision_ready(monkeypatch, vllm_gia):
    """`vision_backend: none` mà `vision_ready: true` thì Body tưởng vision chạy được."""
    import asyncio

    from src.api.dependencies import RuntimeState

    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "SERVER")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url)
    rs = RuntimeState()
    asyncio.run(rs.ensure_vision_runtime())
    assert rs.vision is None
    assert "ENV=SERVER" in (rs.vision_error or "")
    monkeypatch.setattr(ModelEngine, "_instance", None)


def test_env_server_vision_tat_theo_thiet_ke_khong_lam_degraded(monkeypatch, vllm_gia):
    """
    Cấu hình compose (production dự kiến). Sau lời gọi vision đầu tiên, bản
    trước báo `degraded: true` vĩnh viễn dù vLLM khoẻ (QA 26/10, vòng 2).
    """
    import asyncio

    from fastapi.testclient import TestClient

    import src.api.main as main_mod
    from src.api.dependencies import RuntimeState

    monkeypatch.setattr(ModelEngine, "_instance", None)
    monkeypatch.setenv("ENV", "SERVER")
    monkeypatch.setenv("VLLM_BASE_URL", vllm_gia.url)
    rs = RuntimeState()
    asyncio.run(rs.ensure_text_runtime())
    asyncio.run(rs.ensure_vision_runtime())
    monkeypatch.setattr(main_mod, "runtime", rs)

    body = TestClient(main_mod.app).get("/health").json()
    assert body["vision_backend"] == "none"
    assert body["vision_ready"] is False
    assert body["vision_error"], "lý do vẫn phải nhìn thấy được"
    assert body["vllm_server"]["ok"] is True
    assert body["degraded"] is False, body
    monkeypatch.setattr(ModelEngine, "_instance", None)
