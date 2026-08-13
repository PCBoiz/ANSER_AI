"""
src/core/findings.py — hình dạng chung của MỘT PHÁT HIỆN.

Mọi module kiểm tra (tồn kho, đối chiếu hai kỳ, công nợ, thuế suất) đều trả về
cùng một kiểu dict. Nhờ vậy bên Body chỉ cần một component để hiển thị, và một
phát hiện mới không kéo theo việc sửa giao diện.

Bốn trường bắt buộc phải có ý nghĩa với người đọc là chủ doanh nghiệp:

* `title`      — nói CÁI GÌ sai, bằng tiếng Việt thường
* `evidence`   — những con số để họ mở MISA đối chiếu tay, không phải để trang trí
* `money_impact` — quy ra tiền, hoặc `None` khi thành thật là không quy được
* `suggestion` — việc cần làm tiếp

`money_impact=None` và `money_impact=0` khác nhau: một cái là 'chưa quy ra tiền
được', cái kia là 'quy ra rồi, bằng không'. Đừng gộp.
"""

from __future__ import annotations

from typing import Any, Optional

MUC_DO = ("cao", "trung bình", "thấp")

_THU_TU = {m: i for i, m in enumerate(MUC_DO)}


def finding(
    kind: str,
    severity: str,
    title: str,
    evidence: dict[str, Any],
    suggestion: str,
    *,
    code: Optional[str] = None,
    product: Optional[str] = None,
    unit: Optional[str] = None,
    money_impact: Optional[float] = None,
) -> dict[str, Any]:
    """Dựng một phát hiện. `severity` phải nằm trong MUC_DO."""
    if severity not in _THU_TU:
        raise ValueError(f"mức độ không hợp lệ: {severity!r} (phải là một trong {MUC_DO})")
    return {
        "kind": kind,
        "severity": severity,
        "code": code,
        "product": product,
        "unit": unit,
        "title": title,
        "evidence": evidence,
        "money_impact": None if money_impact is None else round(money_impact),
        "suggestion": suggestion,
    }


def sap_xep(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nặng trước, trong cùng mức độ thì nhiều tiền trước."""
    return sorted(
        findings,
        key=lambda f: (_THU_TU.get(f.get("severity", "thấp"), 9),
                       -(f.get("money_impact") or 0),
                       f.get("code") or ""),
    )
