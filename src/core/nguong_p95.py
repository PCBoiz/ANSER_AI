"""
src/core/nguong_p95.py — ngưỡng độ trễ p95 của một lời gọi model (NFR-03).

VÌ SAO HAI NGƯỠNG (chủ dự án chốt 28/10/2026)
--------------------------------------------
BR-04 đo p95 ≈ 8,5–9,1 giây trên L4, vượt ngưỡng tham chiếu 5.000ms của
ARCHITECTURE §13. Nhưng request tự dừng sau ~217 token ở ~25 token/giây: đó là
thời gian SINH, không phải hàng đợi. Một ngưỡng tổng duy nhất không phân biệt
được "máy chậm" với "câu trả lời dài" — câu dài nào cũng vượt.

  - `P95_MS_MOI_TOKEN` (mặc định 60): p95 của (độ trễ / số token sinh ra). Đo
    SỨC KHOẺ của server: hàng đợi nghẽn, batching hỏng, GPU tranh chấp đều làm
    nó tăng, bất kể câu dài hay ngắn. Đo được ~40ms/token ở 1× và 4× (BR-04).
  - `P95_NGUONG_MS` (mặc định 5000): p95 tổng — thứ người dùng cảm thấy. Giữ
    để thấy, nhưng vượt nó với câu dài là chuyện đã biết, không phải sự cố.

Đổi qua biến môi trường, không sửa số trong mã. Module chỉ dùng thư viện chuẩn
để script đo (`offline_training/`) import được mà không kéo theo cả Brain.
"""

from __future__ import annotations

import os

MAC_DINH_NGUONG_MS = 5000.0
MAC_DINH_MS_MOI_TOKEN = 60.0


def _doc(ten: str, mac_dinh: float) -> float:
    tho = os.getenv(ten, "").strip()
    if not tho:
        return mac_dinh
    try:
        v = float(tho)
    except ValueError:
        raise ValueError(f"{ten}={tho!r} không phải số") from None
    if v <= 0:
        raise ValueError(f"{ten}={tho!r} phải > 0")
    return v


def doc_nguong() -> tuple[float, float]:
    """(ngưỡng tổng ms, ngưỡng ms/token) từ env, rơi về mặc định khi trống."""
    return (_doc("P95_NGUONG_MS", MAC_DINH_NGUONG_MS),
            _doc("P95_MS_MOI_TOKEN", MAC_DINH_MS_MOI_TOKEN))


def danh_gia(p95_ms: float | None, p95_ms_moi_token: float | None) -> dict:
    """Đạt/vượt cho từng ngưỡng. None = không đo được -> không kết luận."""
    nguong_ms, nguong_tok = doc_nguong()
    return {
        "nguong_ms": nguong_ms,
        "nguong_ms_moi_token": nguong_tok,
        "tong_dat": None if p95_ms is None else p95_ms <= nguong_ms,
        "moi_token_dat": None if p95_ms_moi_token is None else p95_ms_moi_token <= nguong_tok,
    }


__all__ = ["MAC_DINH_MS_MOI_TOKEN", "MAC_DINH_NGUONG_MS", "danh_gia", "doc_nguong"]

# BR-07 nghiem thu: bien ten mo ho, ruff E741 PHAI lam CI do. Commit sau go ra.
l = 1
