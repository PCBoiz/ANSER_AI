"""
src/core/forecasting.py — dự báo nhu cầu và điểm đặt hàng lại.

VÌ SAO KHÔNG DÙNG LSTM, VÀ CŨNG KHÔNG DÙNG LLM
-----------------------------------------------
Spec v1.0 §4.6 đặt lộ trình LSTM -> LLM cho dự báo. Cả hai đầu đều không phù hợp
với chế độ dữ liệu thực tế của khách:

  - Nhu cầu của SME bán buôn/vận tải là NHU CẦU GIÁN ĐOẠN (intermittent demand):
    nhiều kỳ bằng 0, thỉnh thoảng một đơn lớn. Đây là chế độ có phương pháp
    chuyên biệt, không phải chuỗi thời gian trơn.
  - Croston là chuẩn de-facto cho chế độ này. Trên dữ liệu thưa, so sánh thực
    nghiệm cho thấy Croston sai số THẤP HƠN cả mô hình hồi quy ML tốt nhất —
    ML/DL cần dữ liệu dày, mà thưa chính là đặc trưng của bài toán.
  - LLM tệ hơn nữa: nó không tính toán, và mọi con số nó "dự báo" đều không tái
    lập được. Vi phạm thẳng P1.

Vì vậy module này là CODE THUẦN, kiểm thử được, chạy trên CPU, không tốn VRAM.
LLM chỉ đọc output rồi diễn giải.

HIỆU CHỈNH THIÊN LỆCH
---------------------
Croston gốc ước lượng DƯ khoảng 15-20% do cách đặt khoảng cách ở mẫu số khi cập
nhật (Syntetos & Boylan 2005). Mặc định ở đây dùng bản hiệu chỉnh SBA.

ĐO SAI SỐ BẰNG MASE, KHÔNG PHẢI MAPE
-------------------------------------
MAPE chia cho giá trị thực. Nhu cầu gián đoạn có rất nhiều kỳ bằng 0 -> MAPE vô
nghĩa (chia cho 0). MASE chuẩn hoá theo sai số của dự báo ngây thơ nên dùng được.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

# Ngưỡng phân loại Syntetos-Boylan-Croston.
ADI_CUTOFF = 1.32     # khoảng cách trung bình giữa hai lần có nhu cầu
CV2_CUTOFF = 0.49     # bình phương hệ số biến thiên của LƯỢNG nhu cầu

# Hệ số mức phục vụ (phân vị chuẩn tắc).
SERVICE_LEVEL_Z = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.98: 2.0537,
    0.99: 2.3263,
}

_PATTERN_VI = {
    "smooth":       "đều — nhu cầu ổn định, dự báo đáng tin",
    "intermittent": "gián đoạn — nhiều kỳ không phát sinh, lượng khá ổn định",
    "erratic":      "thất thường — kỳ nào cũng có nhưng lượng dao động mạnh",
    "lumpy":        "vừa gián đoạn vừa dao động mạnh — dự báo kém tin cậy nhất",
    "no_demand":    "chưa từng phát sinh nhu cầu trong kỳ xét",
}


@dataclass
class DemandProfile:
    """Đặc trưng thống kê của một chuỗi nhu cầu."""
    n_periods: int
    n_nonzero: int
    adi: Optional[float]          # average demand interval
    cv2: Optional[float]          # squared coefficient of variation
    pattern: str
    pattern_vi: str
    mean_nonzero: Optional[float]


@dataclass
class ForecastResult:
    """Kết quả dự báo cho một mặt hàng."""
    per_period: float             # nhu cầu kỳ vọng mỗi kỳ
    method: str
    profile: DemandProfile
    mase: Optional[float]         # sai số đo trên chính chuỗi lịch sử
    confidence: str               # cao | trung bình | thấp
    warnings: list[str]


# ---------------------------------------------------------------------------
# Phân loại chế độ nhu cầu
# ---------------------------------------------------------------------------

def classify_demand(series: Sequence[float]) -> DemandProfile:
    """
    Phân loại theo khung Syntetos-Boylan-Croston.

    Phân loại này KHÔNG chỉ để chọn phương pháp — nó là thông tin nghiệp vụ thật:
    mặt hàng "lumpy" cần tồn an toàn cao hơn hẳn mặt hàng "smooth" ở cùng mức
    phục vụ, và người mua hàng cần biết điều đó.
    """
    n = len(series)
    nonzero = [v for v in series if v > 0]

    if not nonzero:
        return DemandProfile(
            n_periods=n, n_nonzero=0, adi=None, cv2=None,
            pattern="no_demand", pattern_vi=_PATTERN_VI["no_demand"],
            mean_nonzero=None,
        )

    adi = n / len(nonzero)
    mean_nz = sum(nonzero) / len(nonzero)

    if len(nonzero) < 2 or mean_nz == 0:
        cv2 = 0.0
    else:
        sd = statistics.pstdev(nonzero)
        cv2 = (sd / mean_nz) ** 2

    if adi < ADI_CUTOFF:
        pattern = "smooth" if cv2 < CV2_CUTOFF else "erratic"
    else:
        pattern = "intermittent" if cv2 < CV2_CUTOFF else "lumpy"

    return DemandProfile(
        n_periods=n, n_nonzero=len(nonzero),
        adi=round(adi, 4), cv2=round(cv2, 4),
        pattern=pattern, pattern_vi=_PATTERN_VI[pattern],
        mean_nonzero=round(mean_nz, 4),
    )


# ---------------------------------------------------------------------------
# Croston / SBA
# ---------------------------------------------------------------------------

def croston(
    series: Sequence[float],
    alpha: float = 0.1,
    variant: str = "sba",
) -> float:
    """
    Dự báo nhu cầu mỗi kỳ cho chuỗi gián đoạn.

    Làm trơn RIÊNG hai đại lượng: lượng nhu cầu mỗi lần phát sinh (z) và khoảng
    cách giữa hai lần phát sinh (p). Dự báo mỗi kỳ = z / p.

    variant:
      "classic" — Croston gốc, ước lượng dư ~15-20%
      "sba"     — hiệu chỉnh Syntetos-Boylan, nhân thêm (1 - alpha/2). MẶC ĐỊNH.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha phải nằm trong khoảng (0, 1)")

    nonzero_idx = [i for i, v in enumerate(series) if v > 0]
    if not nonzero_idx:
        return 0.0

    first = nonzero_idx[0]
    z_hat = float(series[first])
    p_hat = float(first + 1)          # số kỳ tính tới lần phát sinh đầu tiên
    gap = 1

    for value in series[first + 1:]:
        if value > 0:
            z_hat = alpha * float(value) + (1 - alpha) * z_hat
            p_hat = alpha * gap + (1 - alpha) * p_hat
            gap = 1
        else:
            gap += 1

    if p_hat <= 0:
        return 0.0

    forecast = z_hat / p_hat
    if variant == "sba":
        forecast *= (1 - alpha / 2)
    return forecast


def moving_average(series: Sequence[float], window: int = 4) -> float:
    """Trung bình trượt — dùng cho chế độ 'smooth', nơi Croston không có lợi thế."""
    if not series:
        return 0.0
    window = min(window, len(series))
    return sum(series[-window:]) / window


# ---------------------------------------------------------------------------
# Đo sai số
# ---------------------------------------------------------------------------

def mase(actual: Sequence[float], predicted: Sequence[float]) -> Optional[float]:
    """
    Mean Absolute Scaled Error.

    Mẫu số là MAE của dự báo ngây thơ trong mẫu (y_t so với y_{t-1}).
      < 1 : tốt hơn dự báo ngây thơ
      = 1 : ngang
      > 1 : tệ hơn — nên xem lại

    Trả None khi chuỗi phẳng hoàn toàn (mẫu số = 0), lúc đó MASE không định nghĩa.
    """
    if len(actual) < 2 or len(actual) != len(predicted):
        return None

    naive = sum(abs(actual[i] - actual[i - 1]) for i in range(1, len(actual)))
    naive_mae = naive / (len(actual) - 1)
    if math.isclose(naive_mae, 0.0):
        return None

    mae = sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)
    return round(mae / naive_mae, 4)


def _backtest_mase(series: Sequence[float], alpha: float, variant: str) -> Optional[float]:
    """
    Dự báo một bước liên tục trên chính chuỗi lịch sử để ước lượng sai số.

    Bắt đầu từ kỳ thứ 4 để mô hình có tối thiểu vài quan sát trước khi bị chấm.
    """
    if len(series) < 6:
        return None

    start = 4
    preds, actuals = [], []
    for t in range(start, len(series)):
        preds.append(croston(series[:t], alpha=alpha, variant=variant))
        actuals.append(float(series[t]))
    return mase(actuals, preds)


# ---------------------------------------------------------------------------
# API chính
# ---------------------------------------------------------------------------

def forecast_demand(
    series: Sequence[float],
    alpha: float = 0.1,
    variant: str = "sba",
) -> ForecastResult:
    """
    Chọn phương pháp theo chế độ nhu cầu rồi dự báo.

    Trả kèm mức tin cậy và cảnh báo — người mua hàng phải biết con số này đáng
    tin đến đâu, không chỉ biết con số.
    """
    profile = classify_demand(series)
    warnings: list[str] = []

    if profile.pattern == "no_demand":
        return ForecastResult(
            per_period=0.0, method="none", profile=profile, mase=None,
            confidence="thấp",
            warnings=["Chưa có nhu cầu nào trong kỳ xét — không đủ cơ sở để dự báo."],
        )

    if profile.pattern == "smooth":
        per_period = moving_average(series)
        method = "moving_average"
    else:
        per_period = croston(series, alpha=alpha, variant=variant)
        method = f"croston_{variant}"

    error = _backtest_mase(series, alpha, variant) if method.startswith("croston") else None

    # --- mức tin cậy -------------------------------------------------------
    if profile.n_periods < 12:
        confidence = "thấp"
        warnings.append(
            f"Chỉ có {profile.n_periods} kỳ lịch sử — cần ít nhất 12 kỳ để dự báo đáng tin."
        )
    elif profile.n_nonzero < 3:
        confidence = "thấp"
        warnings.append(
            f"Chỉ {profile.n_nonzero} kỳ thực sự phát sinh nhu cầu — mẫu quá mỏng."
        )
    elif profile.pattern == "lumpy":
        confidence = "thấp"
        warnings.append(
            "Nhu cầu vừa gián đoạn vừa dao động mạnh — mọi phương pháp đều sai số lớn. "
            "Nên nâng tồn an toàn thay vì tin vào con số dự báo."
        )
    elif profile.pattern in ("intermittent", "erratic"):
        confidence = "trung bình"
    else:
        confidence = "cao"

    if error is not None and error > 1.0:
        warnings.append(
            f"MASE = {error} (>1) — dự báo đang TỆ HƠN cách ngây thơ 'lấy kỳ trước'. "
            "Nên xem lại dữ liệu đầu vào hoặc dùng quy tắc thủ công."
        )
        confidence = "thấp"

    return ForecastResult(
        per_period=round(per_period, 4),
        method=method,
        profile=profile,
        mase=error,
        confidence=confidence,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Điểm đặt hàng lại
# ---------------------------------------------------------------------------

def reorder_point(
    series: Sequence[float],
    lead_time_periods: float,
    service_level: float = 0.95,
    current_stock: Optional[float] = None,
    review_periods: float = 0.0,
    alpha: float = 0.1,
) -> dict:
    """
    Tính điểm đặt hàng lại và lượng cần nhập.

        ROP = nhu cầu trong thời gian chờ hàng + tồn an toàn
        tồn an toàn = z * độ_lệch_chuẩn_mỗi_kỳ * sqrt(thời_gian_chờ)

    `review_periods` > 0 nghĩa là chỉ xem xét đặt hàng theo chu kỳ (ví dụ mỗi
    tuần); khi đó phải cộng thêm nhu cầu phát sinh trong chính chu kỳ đó.

    Trả về dict đã cấu trúc hoá kèm toàn bộ số trung gian — LLM diễn giải từ đây,
    mọi con số nó nói ra đều truy ngược được.
    """
    if lead_time_periods < 0:
        raise ValueError("lead_time_periods không được âm")

    z = SERVICE_LEVEL_Z.get(round(service_level, 2))
    if z is None:
        raise ValueError(
            f"service_level phải là một trong {sorted(SERVICE_LEVEL_Z)}"
        )

    forecast = forecast_demand(series, alpha=alpha)
    per_period = forecast.per_period

    sigma = statistics.pstdev(series) if len(series) > 1 else 0.0
    horizon = lead_time_periods + review_periods

    lead_demand = per_period * horizon
    safety_stock = z * sigma * math.sqrt(horizon) if horizon > 0 else 0.0
    rop = lead_demand + safety_stock

    suggested_qty = None
    should_order = None
    if current_stock is not None:
        should_order = current_stock <= rop
        suggested_qty = max(0.0, math.ceil(rop - current_stock)) if should_order else 0.0

    return {
        "reorder_point": round(rop, 2),
        "lead_time_demand": round(lead_demand, 2),
        "safety_stock": round(safety_stock, 2),
        "demand_per_period": per_period,
        "demand_std_per_period": round(sigma, 4),
        "service_level": service_level,
        "z_factor": z,
        "horizon_periods": horizon,
        "current_stock": current_stock,
        "should_order": should_order,
        "suggested_qty": suggested_qty,
        "forecast": {
            "method": forecast.method,
            "mase": forecast.mase,
            "confidence": forecast.confidence,
            "pattern": forecast.profile.pattern,
            "pattern_vi": forecast.profile.pattern_vi,
            "adi": forecast.profile.adi,
            "cv2": forecast.profile.cv2,
            "n_periods": forecast.profile.n_periods,
            "n_nonzero": forecast.profile.n_nonzero,
        },
        "warnings": forecast.warnings,
    }


__all__ = [
    "DemandProfile",
    "ForecastResult",
    "classify_demand",
    "croston",
    "moving_average",
    "mase",
    "forecast_demand",
    "reorder_point",
    "SERVICE_LEVEL_Z",
]
