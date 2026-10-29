"""
tests/conftest.py — cô lập bộ test khỏi biến môi trường của máy chạy.

Từ BR-03 (chu kỳ 01), `VLLM_BASE_URL` THẮNG `ENV=LOCAL` ở phía text: có biến đó
thì `ModelEngine` gọi vLLM server thật, ở mọi môi trường. Đó là chủ ý (rẽ theo
backend, không theo tên môi trường), nhưng nó có một hệ quả: máy dev nào đang
export `VLLM_BASE_URL` để thử với Colab sẽ thấy các test "mock" đi gọi mạng.

Nên mặc định gỡ hai biến đó cho MỌI test. Test nào cần đường server thì tự
`monkeypatch.setenv` — và như vậy đọc test là thấy ngay nó cần server.
"""

import os

import pytest

# Hằng số đọc env LÚC IMPORT (`serving.REPETITION_PENALTY_TU_DO`), nên phải gỡ
# ngay khi conftest nạp — trước mọi module `src` — chứ fixture thì đã muộn.
# Sự cố 29/10/2026: ô Colab đo repetition_penalty để lại `=1.0` trong phiên,
# pytest sau đó trượt 4 ca kiểm mặc định 1,25.
os.environ.pop("TEXT_REPETITION_PENALTY", None)


@pytest.fixture(autouse=True)
def _khong_mang_vllm_tu_may_chay_vao_test(monkeypatch):
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
