"""
tests/test_serving.py — điều tiết tải + client vLLM chế độ server.

Chạy KHÔNG cần GPU và không cần vLLM: guard là logic asyncio thuần, client được
kiểm bằng transport giả của httpx.

Trọng tâm: hệ thống phải hỏng theo cách DỰ ĐOÁN ĐƯỢC khi quá tải — từ chối dứt
khoát kèm Retry-After, chứ không phải chậm dần đều cho tới lúc mọi client hết giờ.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.core.serving import (
    BackendError,
    BackendTimeout,
    BackendUnavailable,
    CompletionRequest,
    ConcurrencyGuard,
    Overloaded,
    VLLMServerClient,
    guard_from_env,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# ConcurrencyGuard
# ---------------------------------------------------------------------------

async def test_cho_qua_khi_con_cho():
    guard = ConcurrencyGuard(max_concurrent=2, max_queue=4)
    async with guard.slot():
        assert guard.stats.in_flight == 1
    assert guard.stats.in_flight == 0
    assert guard.stats.admitted == 1


async def test_khong_bao_gio_vuot_max_concurrent():
    guard = ConcurrencyGuard(max_concurrent=3, max_queue=50, wait_timeout_s=5)
    seen: list[int] = []

    async def work():
        async with guard.slot():
            seen.append(guard.stats.in_flight)
            await asyncio.sleep(0.01)

    await asyncio.gather(*[work() for _ in range(20)])
    assert max(seen) <= 3
    assert guard.stats.in_flight == 0
    assert guard.stats.admitted == 20


async def test_hang_doi_day_thi_tu_choi_NGAY():
    """
    Từ chối nhanh là lựa chọn có ý thức: client chờ 60s thì thường đã bỏ đi,
    phục vụ nó lúc đó là lấy mất GPU của người còn đang ngồi đợi.
    """
    guard = ConcurrencyGuard(max_concurrent=1, max_queue=1, wait_timeout_s=5)
    released = asyncio.Event()

    async def hold():
        async with guard.slot():
            await released.wait()

    async def wait_in_queue():
        async with guard.slot():
            pass

    t1 = asyncio.create_task(hold())
    await asyncio.sleep(0.02)                 # t1 chiếm chỗ chạy
    t2 = asyncio.create_task(wait_in_queue())
    await asyncio.sleep(0.02)                 # t2 vào hàng đợi (đầy)

    with pytest.raises(Overloaded) as exc:
        async with guard.slot():
            pass
    assert "đã đầy" in str(exc.value)
    assert exc.value.retry_after_s >= 1
    assert guard.stats.rejected_full == 1

    released.set()
    await asyncio.gather(t1, t2)


async def test_cho_qua_lau_thi_bo_cuoc_kem_retry_after():
    guard = ConcurrencyGuard(max_concurrent=1, max_queue=10, wait_timeout_s=0.05)
    released = asyncio.Event()

    async def hold():
        async with guard.slot():
            await released.wait()

    t = asyncio.create_task(hold())
    await asyncio.sleep(0.02)

    with pytest.raises(Overloaded) as exc:
        async with guard.slot():
            pass
    assert "Chờ quá" in str(exc.value)
    assert guard.stats.rejected_timeout == 1

    released.set()
    await t


async def test_ngoai_le_trong_than_van_tra_lai_cho():
    """Handler ném lỗi mà không trả chỗ thì hệ thống chết dần sau vài lỗi."""
    guard = ConcurrencyGuard(max_concurrent=1, max_queue=1)
    for _ in range(5):
        with pytest.raises(ValueError):
            async with guard.slot():
                raise ValueError("lỗi nghiệp vụ")
    assert guard.stats.in_flight == 0
    async with guard.slot():
        pass                                   # vẫn nhận được request mới


async def test_bo_cuoc_giua_chung_khong_ro_ri_cho():
    """Client ngắt kết nối giữa chừng -> task bị cancel -> chỗ phải được trả lại."""
    guard = ConcurrencyGuard(max_concurrent=1, max_queue=10, wait_timeout_s=5)
    released = asyncio.Event()

    async def hold():
        async with guard.slot():
            await released.wait()

    async def waiter():
        async with guard.slot():
            await asyncio.sleep(1)

    t1 = asyncio.create_task(hold())
    await asyncio.sleep(0.02)
    t2 = asyncio.create_task(waiter())
    await asyncio.sleep(0.02)
    t2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t2

    released.set()
    await t1
    assert guard.stats.in_flight == 0
    async with guard.slot():                   # chỗ đã về, không rò rỉ
        pass


async def test_thong_ke_du_de_chinh_nguong():
    guard = ConcurrencyGuard(max_concurrent=2, max_queue=8, wait_timeout_s=5)

    async def work():
        async with guard.slot():
            await asyncio.sleep(0.01)

    await asyncio.gather(*[work() for _ in range(10)])
    snap = guard.snapshot()
    assert snap["admitted"] == 10
    assert snap["peak_in_flight"] == 2
    assert snap["peak_queued"] >= 1
    assert snap["rejected_total"] == 0
    assert snap["avg_wait_seconds"] >= 0


async def test_tham_so_vo_ly_bi_chan_ngay():
    with pytest.raises(ValueError):
        ConcurrencyGuard(max_concurrent=0)
    with pytest.raises(ValueError):
        ConcurrencyGuard(max_concurrent=1, max_queue=-1)


async def test_doc_nguong_tu_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("ANSER_TEXT_MAX_CONCURRENT", "7")
    monkeypatch.setenv("ANSER_TEXT_MAX_QUEUE", "3")
    monkeypatch.setenv("ANSER_TEXT_WAIT_TIMEOUT_S", "1.5")
    g = guard_from_env("text")
    assert (g.max_concurrent, g.max_queue, g.wait_timeout_s) == (7, 3, 1.5)


# ---------------------------------------------------------------------------
# VLLMServerClient
# ---------------------------------------------------------------------------

def _client(handler, **kw) -> VLLMServerClient:
    c = VLLMServerClient(base_url="http://vllm:8001", model="anser-v3", **kw)
    c._client = httpx.AsyncClient(
        base_url="http://vllm:8001", transport=httpx.MockTransport(handler)
    )
    return c


async def test_sinh_text_qua_http():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/completions"
        return httpx.Response(200, json={"choices": [{"text": "  xin chào  "}]})

    c = _client(handler)
    assert await c.complete(CompletionRequest(prompt="hi")) == "xin chào"
    await c.aclose()


async def test_payload_giu_dung_ten_tham_so_cua_vllm():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"text": "ok"}]})

    c = _client(handler)
    await c.complete(CompletionRequest(
        prompt="p", max_tokens=64, temperature=0.3, repetition_penalty=1.1,
        stop=["</s>"], guided_json={"type": "object"},
    ))
    assert seen["model"] == "anser-v3"
    assert seen["max_tokens"] == 64
    assert seen["temperature"] == 0.3
    assert seen["repetition_penalty"] == 1.1        # field ngoài chuẩn OpenAI
    assert seen["stop"] == ["</s>"]
    assert seen["guided_json"] == {"type": "object"}
    await c.aclose()


async def test_khong_gui_guided_json_khi_khong_can():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"text": "ok"}]})

    c = _client(handler)
    await c.complete(CompletionRequest(prompt="p"))
    assert "guided_json" not in seen and "stop" not in seen
    await c.aclose()


async def test_chua_cau_hinh_thi_noi_ro_chu_khong_nem_loi_kho_hieu():
    c = VLLMServerClient(base_url="", model="")
    assert c.configured is False
    with pytest.raises(BackendUnavailable) as exc:
        await c.complete(CompletionRequest(prompt="p"))
    assert "VLLM_BASE_URL" in str(exc.value)


async def test_server_tra_loi_thi_thanh_BackendError():
    def handler(request):
        return httpx.Response(422, text="max_model_len exceeded")

    c = _client(handler)
    with pytest.raises(BackendError) as exc:
        await c.complete(CompletionRequest(prompt="p"))
    assert "422" in str(exc.value)
    await c.aclose()


async def test_khong_noi_duoc_thi_thanh_BackendUnavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    c = _client(handler)
    with pytest.raises(BackendUnavailable):
        await c.complete(CompletionRequest(prompt="p"))
    await c.aclose()


async def test_qua_gio_thi_thanh_BackendTimeout():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    c = _client(handler)
    with pytest.raises(BackendTimeout):
        await c.complete(CompletionRequest(prompt="p"))
    await c.aclose()


async def test_json_hong_tu_server_khong_lam_sap_brain():
    def handler(request):
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    c = _client(handler)
    with pytest.raises(BackendError) as exc:
        await c.complete(CompletionRequest(prompt="p"))
    assert "không đọc được" in str(exc.value)
    await c.aclose()


async def test_health_khong_bao_gio_nem_ngoai_le():
    """/health của Brain phải trả lời được kể cả khi vLLM đã chết."""
    def handler(request):
        raise httpx.ConnectError("refused")

    c = _client(handler)
    h = await c.health()
    assert h["ok"] is False and "reason" in h
    await c.aclose()

    c2 = _client(lambda r: httpx.Response(200))
    assert (await c2.health())["ok"] is True
    await c2.aclose()

    assert (await VLLMServerClient(base_url="").health())["ok"] is False


async def test_api_key_chi_doc_tu_env(monkeypatch):
    """R2b: khoá không được truyền xuống từ tầng gọi."""
    monkeypatch.setenv("VLLM_API_KEY", "k-secret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"choices": [{"text": "ok"}]})

    c = _client(handler)
    await c.complete(CompletionRequest(prompt="p"))
    assert seen["auth"] == "Bearer k-secret"
    await c.aclose()


# ---------------------------------------------------------------------------
# Guard + client ghép lại: đúng đường đi thật
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("_", [0])
async def test_qua_tai_tra_503_kem_retry_after_chu_khong_phai_500(_):
    """
    Quá tải KHÔNG phải lỗi máy chủ. Trả 500 khiến client retry ngay lập tức và
    làm tình hình tệ thêm; 503 + Retry-After nói rõ chờ bao lâu là đủ.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.main import handle_overloaded

    app = FastAPI()
    app.add_exception_handler(Overloaded, handle_overloaded)

    @app.get("/boom")
    async def boom():
        raise Overloaded("hàng đợi đầy", retry_after_s=7)

    resp = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "7"
    body = resp.json()
    assert body["error"] == "overloaded" and body["retry_after_s"] == 7


async def test_health_phoi_thong_ke_hang_doi():
    """Chỉnh ngưỡng mà không đo được hàng đợi thì chỉ là đoán."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    body = TestClient(app).get("/health").json()
    assert "load" in body
    if body["load"]:                       # engine đã dựng (kể cả chế độ mock)
        text = body["load"]["text"]
        for key in ("max_concurrent", "max_queue", "in_flight",
                    "peak_queued", "rejected_total"):
            assert key in text


async def test_qua_tai_thi_tu_choi_som_thay_vi_dim_backend():
    """
    Điểm cốt lõi của cả module: khi tải vượt sức, phần lớn request vẫn được phục
    vụ nhanh và phần thừa bị từ chối DỨT KHOÁT — thay vì tất cả cùng chậm dần.
    """
    guard = ConcurrencyGuard(max_concurrent=2, max_queue=2, wait_timeout_s=0.3)
    hits = 0

    def handler(request):
        nonlocal hits
        hits += 1
        return httpx.Response(200, json={"choices": [{"text": "ok"}]})

    c = _client(handler)

    async def call():
        async with guard.slot():
            await asyncio.sleep(0.05)
            return await c.complete(CompletionRequest(prompt="p"))

    results = await asyncio.gather(*[call() for _ in range(20)], return_exceptions=True)
    served = [r for r in results if isinstance(r, str)]
    refused = [r for r in results if isinstance(r, Overloaded)]

    assert len(served) + len(refused) == 20
    assert refused, "quá tải mà không từ chối ai — hàng đợi đang không có trần"
    assert hits == len(served), "backend chỉ được gọi cho request đã qua cửa"
    assert guard.stats.in_flight == 0
    await c.aclose()
