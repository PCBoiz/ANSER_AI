"""
tests/test_auth_bao_phu.py — KHÔNG endpoint nào được thoát khỏi cổng xác thực.

Ngày 15/08/2026, quét từng endpoint qua HTTP thật lộ ra hai chỗ mở công khai:

  GET /tools                  -> 16.623 byte lược đồ nội bộ của 8 tool
  GET /api/v1/task/{task_id}  -> CÂU TRẢ LỜI của AI: tên khách, MST, số công nợ

Hai mươi endpoint kia đều gọi `require_api_token` đúng, nên không có gì cho thấy
hai cái này sai. Đó là hình dạng của mọi lỗi bỏ sót: cái sai trông hệt cái đúng,
chỉ khác ở chỗ THIẾU một dòng — mà thiếu thì không ai in ra được.

826 test lúc đó chạy bằng TestClient trong tiến trình và không test nào đặt câu
hỏi "endpoint này có kiểm token không". Nên bộ này hỏi thẳng, và hỏi về TOÀN BỘ
bảng route chứ không về một danh sách viết tay — danh sách viết tay thì endpoint
thứ 24 lại rơi ra ngoài đúng như cũ.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from fastapi.testclient import TestClient  # noqa: E402

import src.api.dependencies as deps  # noqa: E402
import src.api.main as main_mod  # noqa: E402
from src.api.main import app  # noqa: E402

client = TestClient(app)

TOKEN_THU = "token-thu-cho-test"


@pytest.fixture(autouse=True)
def bat_xac_thuc(monkeypatch):
    """
    Bật xác thực CHỈ trong bộ này, bằng cách vá biến module chứ không đặt env.

    Bản đầu đặt `os.environ["API_AUTH_TOKEN"]` ở đầu file. Hỏng theo hai chiều
    ngược nhau, tuỳ thứ tự pytest nạp file:

      - File khác nạp `src.api.dependencies` TRƯỚC -> biến module đã tính xong
        từ env rỗng, gán env lúc này không tới được nó. Cổng không bật, cả bộ
        này đỏ.
      - Bộ này nạp trước -> env dính cho TOÀN BỘ phiên test, và 60 test khác
        (vốn không gửi token) nhận 401.

    Cả hai đều là một chuyện: `API_AUTH_TOKEN` đọc env MỘT LẦN lúc import. Nên
    thứ phải vá là biến module, và vá có phạm vi.

    `main` giữ bản sao riêng cho `/health`, phải vá cả hai.
    """
    monkeypatch.setattr(deps, "API_AUTH_TOKEN", TOKEN_THU)
    monkeypatch.setattr(main_mod, "API_AUTH_TOKEN", TOKEN_THU)

# `/health` cố ý mở: nó là chỗ để biết Brain sống hay chết, và để nhìn
# `auth_enabled`. Người hỏi chưa có token vẫn phải nhận được câu trả lời đó.
MO_CO_Y = {"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}


def _duong_di_thuc(path: str) -> str:
    """`/api/v1/task/{task_id}` -> `/api/v1/task/x`. Tham số nào cũng được."""
    import re
    return re.sub(r"\{[^}]+\}", "x", path)


def moi_endpoint():
    for r in app.routes:
        if not isinstance(r, APIRoute) or r.path in MO_CO_Y:
            continue
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            yield pytest.param(method, r.path, id=f"{method} {r.path}")


@pytest.mark.parametrize("method,path", list(moi_endpoint()))
def test_moi_endpoint_deu_chan_khi_khong_co_token(method, path):
    """
    KHÔNG token -> 401. Không phải 422, không phải 200.

    422 cũng là trượt: nó nghĩa là FastAPI đã validate thân request TRƯỚC khi
    kiểm token, nên người chưa xác thực đọc được tên từng trường bắt buộc trong
    thông báo lỗi. Dò được lược đồ mà không cần token.
    """
    resp = client.request(method, _duong_di_thuc(path), json={}, headers={})
    assert resp.status_code == 401, (
        f"{method} {path} trả {resp.status_code} thay vì 401.\n"
        f"  200 = endpoint mở công khai.\n"
        f"  422 = validate thân request chạy trước kiểm token (lộ lược đồ).\n"
        f"  Cổng nằm ở `auth_guard` gắn lúc include_router trong src/api/main.py."
    )


@pytest.mark.parametrize("method,path", list(moi_endpoint()))
def test_token_sai_cung_bi_chan(method, path):
    resp = client.request(method, _duong_di_thuc(path), json={},
                          headers={"X-API-Token": "khong-phai-token-that"})
    assert resp.status_code == 401, f"{method} {path} nhận token SAI mà vẫn cho qua"


def test_health_van_mo_de_biet_brain_song_hay_chet():
    """Đóng /health lại là tự bịt mắt: không token thì không biết Brain ra sao."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["auth_enabled"] is True, (
        "API_AUTH_TOKEN có đặt mà /health báo auth_enabled=False — "
        "đúng tín hiệu dựng ra để phát hiện Brain mở toang lúc triển khai."
    )


def test_health_noi_that_khi_KHONG_co_token(monkeypatch):
    """`auth_enabled=False` phải nói ra được, nếu không tín hiệu này vô dụng."""
    monkeypatch.setattr(deps, "API_AUTH_TOKEN", "")
    monkeypatch.setattr(main_mod, "API_AUTH_TOKEN", "")
    assert client.get("/health").json()["auth_enabled"] is False
