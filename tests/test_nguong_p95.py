"""tests/test_nguong_p95.py — hai ngưỡng p95 (NFR-03, chốt 28/10/2026)."""

import pytest

from src.core.nguong_p95 import (
    MAC_DINH_MS_MOI_TOKEN,
    MAC_DINH_NGUONG_MS,
    danh_gia,
    doc_nguong,
)


def test_mac_dinh_khi_env_trong(monkeypatch):
    monkeypatch.delenv("P95_NGUONG_MS", raising=False)
    monkeypatch.delenv("P95_MS_MOI_TOKEN", raising=False)
    assert doc_nguong() == (MAC_DINH_NGUONG_MS, MAC_DINH_MS_MOI_TOKEN) == (5000.0, 60.0)


def test_doi_qua_env(monkeypatch):
    monkeypatch.setenv("P95_NGUONG_MS", "10000")
    monkeypatch.setenv("P95_MS_MOI_TOKEN", "45")
    assert doc_nguong() == (10000.0, 45.0)


@pytest.mark.parametrize("gia_tri", ["abc", "0", "-5"])
def test_gia_tri_rac_bao_ten_bien(monkeypatch, gia_tri):
    monkeypatch.setenv("P95_MS_MOI_TOKEN", gia_tri)
    with pytest.raises(ValueError, match="P95_MS_MOI_TOKEN"):
        doc_nguong()


def test_so_do_br04_vuot_tong_nhung_dat_moi_token(monkeypatch):
    """BR-04: 9.074 ms cho ~217 token ≈ 42 ms/token — máy khoẻ, câu dài."""
    monkeypatch.delenv("P95_NGUONG_MS", raising=False)
    monkeypatch.delenv("P95_MS_MOI_TOKEN", raising=False)
    kq = danh_gia(9074, 41.8)
    assert kq["tong_dat"] is False and kq["moi_token_dat"] is True


def test_khong_do_duoc_thi_khong_ket_luan():
    kq = danh_gia(None, None)
    assert kq["tong_dat"] is None and kq["moi_token_dat"] is None
