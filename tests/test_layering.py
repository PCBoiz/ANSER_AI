"""
tests/test_layering.py — chặn phụ thuộc NGƯỢC TẦNG quay lại.

Kiến trúc chia bốn tầng, mũi tên chỉ đi xuống:

    T4  src/api/      HTTP
    T3  src/agents/, core/engine.py, core/knowledge.py     điều phối
    T2  src/core/     nghiệp vụ thuần
    T1  core/config.py, serving.py, schemas.py, prompts.py, utils.py, chunking.py

Đó là lý do test nghiệp vụ chạy không cần GPU, không cần DB, không cần mạng.

VÌ SAO CẦN TEST NÀY
-------------------
`agents/agentic.py` từng import ngược lên `api/routes/chat.py` chỉ để dùng
`_extract_json_block` — một hàm thuần đếm ngoặc trên chuỗi. Import đặt trong
THÂN HÀM nên né được vòng lặp import lúc nạp module và **không có gì báo**; nó
sống ở đó tới khi đối chiếu sơ đồ vẽ tay với bản đồ Grapuco sinh tự động
(03/08/2026).

Sơ đồ trong ARCHITECTURE_DIAGRAMS.md khi đó còn ghi "mũi tên CHỈ đi xuống" —
một lời khẳng định sai. Test này biến câu đó thành thứ kiểm được.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

TANG = {
    "api": 4,
    "agents": 3,
    "core/engine.py": 3,
    "core/knowledge.py": 3,
    "core/memory.py": 3,
    "core/config.py": 1,
    "core/serving.py": 1,
    "core/schemas.py": 1,
    "core/prompts.py": 1,
    "core/utils.py": 1,
    "core/chunking.py": 1,
}

# `archive/` là mã đã ngừng dùng, giữ để tra cứu — không nằm trong đường chạy thật.
BO_QUA = ("archive",)


def _tang(rel: str) -> int | None:
    if rel.startswith("api/"):
        return 4
    if rel.startswith("agents/"):
        return 3
    if rel in TANG:
        return TANG[rel]
    if rel.startswith("core/"):
        return 2
    return None


def _modules() -> list[Path]:
    return [
        p for p in SRC.rglob("*.py")
        if not any(part in BO_QUA for part in p.parts) and "__pycache__" not in p.parts
    ]


def _imports(path: Path) -> list[str]:
    """Mọi `import src.x.y` trong file — KỂ CẢ import nằm trong thân hàm."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            out.append(node.module)
        elif isinstance(node, ast.Import):
            out.extend(a.name for a in node.names if a.name.startswith("src."))
    return out


def _rel_from_module(mod: str) -> str:
    """'src.core.engine' -> 'core/engine.py'; 'src.api.routes.chat' -> 'api/routes/chat.py'."""
    return mod[len("src."):].replace(".", "/") + ".py"


def test_khong_module_nao_import_nguoc_len_tang_tren():
    """
    Duyệt bằng AST nên bắt được cả import đặt trong thân hàm — đúng kiểu đã lọt
    lần trước. Grep theo dòng thì chỉ thấy import ở đầu file.
    """
    vi_pham = []
    modules = _modules()
    assert modules, "không quét được file nào — test này sẽ xanh giả"

    for path in modules:
        rel = path.relative_to(SRC).as_posix()
        ta = _tang(rel)
        if ta is None:
            continue
        for mod in _imports(path):
            tb = _tang(_rel_from_module(mod))
            if tb is not None and tb > ta:
                vi_pham.append(f"T{ta} {rel}  ->  T{tb} {_rel_from_module(mod)}")

    assert not vi_pham, (
        "Phụ thuộc ngược tầng:\n  " + "\n  ".join(sorted(set(vi_pham)))
        + "\n\nTầng dưới không được import tầng trên. Cần dùng chung thì chuyển "
          "phần dùng chung xuống tầng thấp hơn (ví dụ core/utils.py)."
    )


def test_tang_nghiep_vu_khong_cham_toi_model_hay_HTTP():
    """
    Tầng 2 (nghiệp vụ thuần) phải chạy được không cần GPU/DB/mạng. Chạm vào
    engine, vLLM, torch hay fastapi là mất tính chất đó — và mất luôn khả năng
    chạy test nghiệp vụ trong CI không GPU.
    """
    CAM = ("src.core.engine", "src.api", "src.agents")
    vi_pham = []
    for path in _modules():
        rel = path.relative_to(SRC).as_posix()
        if _tang(rel) != 2:
            continue
        for mod in _imports(path):
            if mod.startswith(CAM):
                vi_pham.append(f"{rel} -> {mod}")
    assert not vi_pham, "Tầng nghiệp vụ chạm tầng model/HTTP:\n  " + "\n  ".join(vi_pham)


def test_ham_cat_JSON_nam_o_tang_dung_va_hai_cho_goi_deu_dung_no():
    """Chống lùi lại: hàm thuần phải nằm ở tầng 1, không phải trong module route."""
    from src.agents.agentic import extract_json_block as tu_agentic
    from src.api.routes.chat import _extract_json_block as tu_chat
    from src.core.utils import extract_json_block as goc

    assert tu_agentic is goc, "agentic.py không còn dùng bản gốc"
    assert tu_chat is goc, "chat.py giữ một bản CHÉP thay vì alias — hai bản sẽ trôi khỏi nhau"


@pytest.mark.parametrize("text,expect_obj", [
    ('{"a": 1}', {"a": 1}),
    ('lời dẫn {"a": {"b": 2}} lời kết', {"a": {"b": 2}}),
    ('{"s": "có dấu } trong chuỗi", "n": 1}', {"s": "có dấu } trong chuỗi", "n": 1}),
])
def test_cat_JSON_van_dung_sau_khi_chuyen_nha(text, expect_obj):
    from src.core.utils import extract_json_block

    obj, err = extract_json_block(text)
    assert err is None and obj == expect_obj


@pytest.mark.parametrize("text", ["", "không có json", '{"thiếu ngoặc": 1'])
def test_cat_JSON_hong_thi_bao_ly_do(text):
    from src.core.utils import extract_json_block

    obj, err = extract_json_block(text)
    assert obj is None and err
