"""
tests/test_deploy_config.py — khoá hợp đồng giữa FILE TRIỂN KHAI và CODE.

VÌ SAO CÓ FILE NÀY
------------------
Ngày 13/08/2026, chạy test nội bộ qua HTTP thật phát hiện: `deploy/docker-compose.yml`
đặt biến `API_TOKEN`, còn `dependencies.py` đọc `API_AUTH_TOKEN`. Và
`require_api_token` BỎ QUA mọi kiểm tra khi biến nó đọc rỗng.

Hậu quả nếu triển khai đúng theo README: một Brain **không kiểm token nào**, đưa
thẳng ra Internet qua Cloudflare tunnel, trong khi người vận hành vừa bị `:?` bắt
điền token nên đinh ninh đã khoá. Không log nào kêu, không test nào đỏ — vì mọi
test đều chạy TestClient trong cùng tiến trình, nơi file compose không tồn tại.

Đây là loại lỗi mà test đơn vị về bản chất không thấy được: hai tạo tác đúng
riêng lẻ, sai khi ghép. Nên phải có một test đọc CẢ HAI và đối chiếu.
"""

from __future__ import annotations

import pathlib
import re

import pytest

GOC = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = GOC / "deploy" / "docker-compose.yml"
ENV_MAU = GOC / "deploy" / ".env.example"

# Biến compose đặt cho `brain` mà code CỐ Ý chưa đọc, kèm lý do. Danh sách này
# tồn tại để một biến chưa nối phải được KHAI BÁO, thay vì nằm im trông như đã
# chạy. Nối xong thì xoá khỏi đây.
CHUA_NOI: dict[str, str] = {
    "REDIS_URL": (
        "Redis đã có container nhưng TASK_REGISTRY vẫn là OrderedDict trong RAM "
        "(src/core/engine.py). Tác vụ nền vẫn mất khi restart, và vẫn sai nếu "
        "chạy nhiều worker."
    ),
    "VLLM_VISION_BASE_URL": (
        "Chưa có client HTTP cho vision — serving.py mới chỉ có đường text. "
        "Vision hiện nạp thẳng trong tiến trình qua transformers, tức là Brain "
        "vẫn cần GPU, ngược với thiết kế 'brain CPU only' của compose."
    ),
    "VLLM_VISION_MODEL": "Cùng lý do với VLLM_VISION_BASE_URL.",
}

# Biến đọc qua f-string nên quét bằng regex không thấy:
#     os.getenv(f"{prefix}MAX_CONCURRENT")  với prefix = f"ANSER_{name.upper()}_"
DOC_QUA_FSTRING = {
    "ANSER_TEXT_MAX_CONCURRENT",
    "ANSER_TEXT_MAX_QUEUE",
    "ANSER_TEXT_WAIT_TIMEOUT_S",
    "ANSER_VISION_MAX_CONCURRENT",
    "ANSER_VISION_MAX_QUEUE",
    "ANSER_VISION_WAIT_TIMEOUT_S",
}

# Biến do thư viện/hệ điều hành đọc, không phải code mình.
NGOAI_CODE = {"ENV", "PYTHONPATH", "PYTHONUNBUFFERED", "TZ"}


def _env_cua_brain() -> list[str]:
    """Tên biến trong khối `environment:` của service `brain`."""
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"^  brain:.*?^    environment:\n(.*?)(?=^\s{4}\w|\Z)", text, re.S | re.M)
    assert m, "không tìm thấy khối environment của service 'brain' trong compose"
    return re.findall(r"^\s{6}([A-Z_][A-Z0-9_]*):", m.group(1), re.M)


def _env_code_doc() -> set[str]:
    """Mọi tên biến môi trường code đọc bằng chuỗi tường minh."""
    ra: set[str] = set()
    mau = (
        re.compile(r"getenv\(\s*[\"']([A-Z_][A-Z0-9_]*)[\"']"),
        re.compile(r"environ\.get\(\s*[\"']([A-Z_][A-Z0-9_]*)[\"']"),
        re.compile(r"environ\[\s*[\"']([A-Z_][A-Z0-9_]*)[\"']\s*\]"),
    )
    for p in (GOC / "src").rglob("*.py"):
        noi_dung = p.read_text(encoding="utf-8")
        for rx in mau:
            ra |= set(rx.findall(noi_dung))
    return ra | DOC_QUA_FSTRING


# ---------------------------------------------------------------------------
# Xác thực — chỗ đã hỏng thật
# ---------------------------------------------------------------------------

def test_compose_dat_dung_ten_bien_token_ma_code_doc():
    """
    Đây là ca đã hỏng thật. Sai tên biến này không làm gì đổ — nó chỉ lặng lẽ
    TẮT xác thực trên một dịch vụ đang mở ra Internet.
    """
    from src.api import dependencies

    ten_code_doc = re.search(
        r"API_AUTH_TOKEN = os\.getenv\(\s*[\"'](\w+)[\"']",
        (GOC / "src" / "api" / "dependencies.py").read_text(encoding="utf-8"),
    )
    assert ten_code_doc, "không đọc được tên biến token trong dependencies.py"
    ten = ten_code_doc.group(1)
    assert ten in _env_cua_brain(), (
        f"compose phải đặt biến '{ten}' cho service brain — đó là tên code đọc. "
        f"Đặt tên khác là tắt xác thực mà không có dấu hiệu nào."
    )
    assert hasattr(dependencies, "API_AUTH_TOKEN")


def test_khong_kiem_token_khi_chua_dat_thi_health_phai_noi_ra():
    """
    `require_api_token` cho qua khi token rỗng — hợp lý lúc chạy máy mình. Nhưng
    trạng thái đó PHẢI nhìn thấy được từ ngoài, nếu không thì một lần đặt sai tên
    biến là mở toang mà không ai biết.
    """
    from fastapi.testclient import TestClient

    from src.api.main import app

    body = TestClient(app).get("/health").json()
    assert "auth_enabled" in body, "/health phải cho biết xác thực đang bật hay tắt"
    assert isinstance(body["auth_enabled"], bool)


def test_env_mau_co_khoa_token():
    assert "API_TOKEN=" in ENV_MAU.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Không để biến nào nằm im trông như đã chạy
# ---------------------------------------------------------------------------

def test_moi_bien_compose_dat_deu_duoc_code_doc_hoac_khai_bao_la_chua_noi():
    """
    Một biến compose đặt mà code không đọc là lời hứa suông: nó làm file triển
    khai đọc như thể tính năng đã có. Chưa nối thì phải ghi vào `CHUA_NOI` kèm
    lý do — người đọc compose có quyền biết cái gì thật, cái gì mới là dự định.
    """
    doc = _env_code_doc()
    treo = [x for x in _env_cua_brain()
            if x not in doc and x not in CHUA_NOI and x not in NGOAI_CODE]
    assert not treo, (
        f"compose đặt {treo} nhưng không chỗ nào trong src/ đọc. Nối vào code, "
        f"hoặc thêm vào CHUA_NOI kèm lý do."
    )


@pytest.mark.parametrize("ten", sorted(CHUA_NOI))
def test_bien_khai_bao_chua_noi_thi_dung_la_chua_noi(ten):
    """
    Chiều ngược lại: nối xong rồi mà quên xoá khỏi `CHUA_NOI` thì danh sách đó
    thành sai lệch, và lần sau không ai tin nó nữa.
    """
    assert ten not in _env_code_doc(), (
        f"'{ten}' nay đã được code đọc — xoá khỏi CHUA_NOI trong file test này."
    )
    assert CHUA_NOI[ten].strip(), f"'{ten}' phải kèm lý do vì sao chưa nối"


def test_redis_chay_nhung_task_registry_van_trong_RAM():
    """
    Khoá lại một sự thật khó chịu để nó không bị quên: compose dựng Redis và
    ghi chú rằng đó là chỗ giữ trạng thái tác vụ nền, nhưng code chưa dùng.
    Restart Brain là mất sạch task đang chạy.

    Test này sẽ ĐỎ ngay khi ai đó nối Redis vào — lúc ấy sửa cả nó lẫn CHUA_NOI.
    """
    from src.core.engine import TASK_REGISTRY

    assert type(TASK_REGISTRY).__name__ == "TaskRegistry"
    assert not any(
        "redis" in p.read_text(encoding="utf-8").lower()
        for p in (GOC / "src").rglob("*.py")
    ), "đã có code dùng Redis — cập nhật CHUA_NOI và xoá test này"
