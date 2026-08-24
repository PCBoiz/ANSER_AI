"""
tests/test_runtime_loading.py — nạp model KHÔNG được chặn event loop.

VÌ SAO CÓ FILE NÀY (sự cố 23/08/2026)
-------------------------------------
`RuntimeState.ensure_text_runtime` gọi thẳng `ModelEngine()` trong coroutine.
Dựng `LLM(...)` của vLLM và kéo VLM về VRAM là công việc CHẶN LUỒNG 1–3 phút,
nên trong suốt thời gian đó event loop không chạy nổi một callback nào: /health
câm, mọi request đang bay đông cứng, client báo "Body timeout 180s" ngay trên
POST /chat. Nhìn từ ngoài giống hệt server chết — mà log lại không có lỗi nào.

Không test nào của engine bắt được: bản thân `_initialize` luôn đúng. Chỗ hỏng
nằm ở CÁCH GỌI. Nên các test dưới đây đo đúng thứ đó — trong lúc nạp, loop còn
phục vụ được việc khác hay không — và KHÔNG nạp model thật một lần nào.

Các test chạy ENV=LOCAL: đường mock (`_initialize` thoát sớm, `llm = None`)
phải còn nguyên vẹn, có test riêng khoá lại điều đó.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

pytestmark = pytest.mark.asyncio

# Thời gian giả lập một lần nạp model. Đủ dài để phân biệt "loop còn thở" với
# "loop bị chặn", đủ ngắn để test không thành gánh nặng.
NAP_GIAY = 1.0


class _MemoryGia:
    pass


class _KhoGia:
    def loaded_embedder(self):
        return None


class _ManagerGia:
    def __init__(self, engine, memory, kb=None):
        self.engine, self.memory, self.kb = engine, memory, kb


class _CoderGia:
    def __init__(self, engine, memory):
        self.engine, self.memory = engine, memory


def _gia_lap_phu_tro(monkeypatch) -> list:
    """
    Thay mọi thứ NẶNG quanh engine bằng bản giả, trả về sổ đếm lần dựng manager.

    Cố ý không đụng tới `ModelEngine`: nó là thứ đang được kiểm.
    """
    dem_manager: list[int] = []

    class _ManagerDem(_ManagerGia):
        def __init__(self, *a, **kw):
            dem_manager.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr("src.core.memory.MemoryManager", _MemoryGia)
    monkeypatch.setattr("src.core.knowledge.KnowledgeBase", _KhoGia)
    monkeypatch.setattr("src.agents.manager.ManagerAgent", _ManagerDem)
    monkeypatch.setattr("src.agents.coder.CoderAgent", _CoderGia)
    return dem_manager


def _nap_cham(monkeypatch, nhat_ky: list, giay: float = NAP_GIAY):
    """
    Biến `ModelEngine._initialize` thành một lần nạp CHẬM, ghi lại luồng đã chạy.

    `time.sleep` chứ không phải `asyncio.sleep` — cố ý: đây là công việc chặn
    luồng đúng như vLLM, và đó chính là thứ test muốn dựng lại.
    """
    from src.core.engine import ModelEngine

    def _cham(self):
        nhat_ky.append(threading.get_ident())
        time.sleep(giay)
        # Tối thiểu để phần còn lại của runtime dùng được engine giả này.
        self.env = "LOCAL"
        self.llm = None
        self.vision_model = None
        self.vision_processor = None

    # Singleton: phải xoá instance cũ, nếu không `__new__` trả ngay bản đã nạp
    # ở test khác và `_initialize` không bao giờ chạy.
    monkeypatch.setattr(ModelEngine, "_instance", None, raising=False)
    monkeypatch.setattr(ModelEngine, "_initialize", _cham)


async def test_nap_model_khong_chan_event_loop(monkeypatch):
    """
    Trong lúc nạp, loop vẫn phải chạy được coroutine khác.

    Đây là phép đo tái hiện sự cố: nếu việc nạp chạy thẳng trong coroutine thì
    `viec_nho()` không được nhúc nhích cho tới khi nạp xong, và `wait_for` với
    hạn nửa thời gian nạp sẽ ném TimeoutError.
    """
    from src.api import dependencies as deps

    _gia_lap_phu_tro(monkeypatch)
    nhat_ky: list[int] = []
    _nap_cham(monkeypatch, nhat_ky)

    rs = deps.RuntimeState()
    task = asyncio.create_task(rs.ensure_text_runtime())

    async def viec_nho() -> str:
        await asyncio.sleep(0.02)
        return "ok"

    moc = time.perf_counter()
    ket_qua = await asyncio.wait_for(viec_nho(), timeout=NAP_GIAY / 2)
    troi_qua = time.perf_counter() - moc

    assert ket_qua == "ok"
    assert troi_qua < NAP_GIAY / 2, "loop bị chặn: việc nhỏ phải đợi hết lượt nạp"
    assert not task.done(), "tiền đề: lượt nạp vẫn đang chạy lúc đo"

    await task
    assert nhat_ky, "phải thực sự gọi _initialize"
    assert nhat_ky[0] != threading.get_ident(), "phần nạp nặng phải chạy ngoài luồng loop"
    assert rs.manager and rs.coder and rs.memory


async def test_hai_luot_dong_thoi_chi_nap_mot_lan(monkeypatch):
    """
    Khoá + double-check phải giữ nguyên ngữ nghĩa sau khi đẩy sang executor.

    Hai request đầu tiên đến cùng lúc mà nạp hai lần thì hai bản model cùng
    tranh một GPU — hết VRAM, và triệu chứng lại là một lỗi CUDA khó lần ngược.
    """
    from src.api import dependencies as deps

    dem_manager = _gia_lap_phu_tro(monkeypatch)
    nhat_ky: list[int] = []
    _nap_cham(monkeypatch, nhat_ky, giay=0.2)

    rs = deps.RuntimeState()
    await asyncio.gather(rs.ensure_text_runtime(), rs.ensure_text_runtime())

    assert len(nhat_ky) == 1, f"model bị nạp {len(nhat_ky)} lần"
    assert dem_manager == [1], "ManagerAgent chỉ được dựng một lần"


async def test_duong_mock_local_khong_nap_gi(monkeypatch):
    """ENV=LOCAL: engine thật vẫn phải thoát sớm, không chạm vLLM/VLM."""
    from src.api import dependencies as deps
    from src.core.engine import ModelEngine

    _gia_lap_phu_tro(monkeypatch)
    monkeypatch.setattr(ModelEngine, "_instance", None, raising=False)
    monkeypatch.setenv("ENV", "LOCAL")

    rs = deps.RuntimeState()
    await rs.ensure_text_runtime()

    assert rs.engine is not None and rs.engine_error is None
    assert rs.engine.env == "LOCAL"
    assert rs.engine.llm is None, "LOCAL không được nạp model text"
    assert rs.engine.vision_model is None, "LOCAL không được nạp model vision"


async def test_nap_vision_cung_khong_chan_event_loop(monkeypatch):
    """Nhánh vision nạp cùng một ModelEngine — cũng không được chặn loop."""
    from src.api import dependencies as deps

    nhat_ky: list[int] = []
    _nap_cham(monkeypatch, nhat_ky)
    monkeypatch.setattr("src.agents.vision.VisionAgent", lambda engine: object())

    rs = deps.RuntimeState()
    task = asyncio.create_task(rs.ensure_vision_runtime())

    moc = time.perf_counter()
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=NAP_GIAY / 2)
    assert time.perf_counter() - moc < NAP_GIAY / 2
    assert not task.done()

    await task
    assert rs.vision is not None
    assert nhat_ky and nhat_ky[0] != threading.get_ident()
