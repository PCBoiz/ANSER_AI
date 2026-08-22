"""
chay_thu_live.py — chạy thử LIVE ba câu qua đúng đường Body đi.

KHÁC `benchmark_integration.py`: bộ kia chấm 6 ca theo tiêu chí nội dung. Bộ
này chỉ hỏi MỘT câu duy nhất — *đường đi có đúng không* — và trả lời bằng số đo
chứ không bằng chữ. Nó đọc `ai_metrics.jsonl` để thấy `route` / `tool_plan` /
`tool_calls` THẬT của từng lượt, thay vì đoán qua câu trả lời.

Vì sao cần: hoá đơn VẬN TẢI bị luật từ khoá bắt thành LOGISTICS chỉ vì TÊN DÒNG
HÀNG chứa chữ "vận chuyển" — đó là DỮ LIỆU trong tờ hoá đơn, không phải Ý ĐỊNH
người hỏi. Trước bản vá `soat_hoa_don_logistics` (chat.py), kế hoạch ["vat"]
không bao giờ chạy: người dùng đòi SOÁT hoá đơn lại nhận luồng BÁO GIÁ. Câu trả
lời trông vẫn trôi chảy, nên lỗi này KHÔNG tự lộ ra khi đọc bằng mắt.

CHẠY (sau khi Brain đã lên và ngrok đã mở):
    BRAIN_URL=https://xxx.ngrok-free.dev \
    BRAIN_API_TOKEN=... \
    AI_METRICS_PATH=/content/ai_metrics.jsonl \
    python offline_training/chay_thu_live.py

Trên Colab, ba biến này đã nằm sẵn trong `os.environ` nên chỉ cần:
    !python offline_training/chay_thu_live.py

Mã thoát: 0 = đường đi đúng, 1 = sai (hoặc không đo được).
"""
import json
import os
import subprocess
import sys
import time

import httpx

BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:8000").rstrip("/")
TOKEN = (os.environ.get("BRAIN_API_TOKEN") or os.environ.get("API_AUTH_TOKEN") or "").strip()
DUONG_DO = os.environ.get("AI_METRICS_PATH", "/content/ai_metrics.jsonl")
GIO_CAU_DAU = float(os.environ.get("LIVE_TIMEOUT_DAU", "420"))   # nạp model lười
GIO_CON_LAI = float(os.environ.get("LIVE_TIMEOUT_SAU", "180"))

HEADERS = {"ngrok-skip-browser-warning": "true"}
if TOKEN:
    HEADERS["X-API-Token"] = TOKEN

# Hoá đơn cố ý SAI: 5.000.000 + 500.000 = 5.500.000. Kể cả VAT 10% cũng chỉ
# 6.050.000. Ghi 6.500.000 là sai ở MỌI thuế suất — không còn đường nào để một
# câu trả lời đúng bỏ qua được, nên ca này không thể "đạt" nhờ may.
HOA_DON = ('Kiểm tra hoá đơn này giúp tôi: {"Cước vận chuyển HN-HP": 5000000, '
           '"Phụ phí xăng dầu": 500000}, tổng ghi 6.500.000đ có đúng không?')

CAU = [
    ("Xin chào, bạn giúp được gì cho công việc kho vận?", "chat thường", None),
    (HOA_DON, "SOÁT HOÁ ĐƠN", "vat"),
    ("Báo giá xe 5 tấn đi Hải Phòng ngày mai", "báo giá", None),
]


def vram(nhan: str) -> None:
    """In VRAM + tiến trình đang giữ. Im lặng bỏ qua nếu máy không có nvidia-smi."""
    try:
        tong = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=15).stdout.strip()
        ai = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=15).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return
    print(f"\n  ── VRAM [{nhan}]  tổng: {tong}")
    for dong in (ai.splitlines() or ["(không tiến trình nào giữ VRAM)"]):
        print(f"     {dong}")


def hoi(msg: str, gio: float) -> tuple[str, float]:
    """Gửi ĐÚNG như Body: POST /chat trả task_id, rồi poll /api/v1/task/{id}."""
    t0 = time.time()
    with httpx.Client(timeout=60.0, headers=HEADERS) as client:
        r = client.post(f"{BRAIN_URL}/chat",
                        json={"user_id": "live-test", "store_id": "1", "message": msg})
        if r.status_code == 401:
            raise SystemExit(
                "401 — Brain từ chối token. Đây là MỘT lỗi cấu hình, không phải "
                "ba câu hỏng. Đối chiếu vân tay BRAIN_API_TOKEN với ô 4.1."
            )
        r.raise_for_status()
        task_id = r.json().get("task_id")
        if not task_id:
            raise SystemExit(f"POST /chat không trả task_id: {r.text[:200]}")

        han = time.time() + gio
        while time.time() < han:
            time.sleep(2)
            trang_thai = client.get(f"{BRAIN_URL}/api/v1/task/{task_id}").json()
            if trang_thai.get("status") == "completed":
                kq = trang_thai.get("result") or {}
                ans = kq.get("answer") if isinstance(kq, dict) else str(kq)
                return str(ans), time.time() - t0
            if trang_thai.get("status") == "failed":
                return f"[THẤT BẠI] {trang_thai.get('error')}", time.time() - t0
    return f"[HẾT GIỜ sau {gio:.0f}s]", time.time() - t0


def main() -> int:
    print("=" * 78)
    print(f"  CHẠY THỬ LIVE — {BRAIN_URL}")
    print(f"  token: {'có (' + TOKEN[:4] + '…' + TOKEN[-4:] + ')' if TOKEN else 'KHÔNG CÓ'}"
          f"   ·   đo: {DUONG_DO}")
    print("=" * 78)

    if not os.path.exists(DUONG_DO):
        print(f"  ⚠ chưa thấy {DUONG_DO} — Brain phải chạy với AI_METRICS_PATH trỏ vào đó,\n"
              "    nếu không bảng bằng chứng bên dưới sẽ trống.")
    truoc = sum(1 for _ in open(DUONG_DO, encoding="utf-8")) if os.path.exists(DUONG_DO) else 0

    for i, (msg, nhan, _) in enumerate(CAU):
        gio = GIO_CAU_DAU if i == 0 else GIO_CON_LAI
        print(f"\n▸ [{nhan}] {msg[:66]}…")
        if i == 0:
            print(f"  (câu đầu nạp model — chờ tới {gio:.0f}s)")
        ans, giay = hoi(msg, gio)
        print(f"  {giay:5.1f}s · {ans[:320]}")
        if i == 0:
            vram("sau khi model đã nạp")

    vram("sau cả ba câu")

    # ---- Bằng chứng: tool nào ĐÃ CHẠY, không phải đoán qua chữ -------------
    print("\n" + "=" * 78)
    print("  ĐO ĐƯỢC, KHÔNG PHẢI ĐOÁN")
    print("=" * 78)
    if not os.path.exists(DUONG_DO):
        print("  ✗ không có file đo — không kết luận được gì. Đặt AI_METRICS_PATH rồi chạy lại.")
        return 1
    with open(DUONG_DO, encoding="utf-8") as f:
        rows = [json.loads(dong) for dong in f if dong.strip()][truoc:]
    if len(rows) < len(CAU):
        print(f"  ✗ chỉ ghi được {len(rows)}/{len(CAU)} lượt — thiếu dữ liệu để kết luận.")
        return 1

    print(f"  {'lượt':<16}{'route':<12}{'tool_plan':<12}{'tool_calls':<12}{'ms':>8}  chặn")
    print("  " + "-" * 72)
    for (_, nhan, _), r in zip(CAU, rows):
        print(f"  {nhan:<16}{str(r.get('route')):<12}{str(r.get('tool_plan')):<12}"
              f"{str(r.get('tool_calls')):<12}{r.get('latency_ms', 0):>8}"
              f"  {r.get('blocked_reason') or '-'}")

    loi = 0
    print()
    for (_, nhan, mong_doi), r in zip(CAU, rows):
        thuc = r.get("tool_plan")
        if mong_doi is None:
            dat = not thuc
            print(f"  {'✓' if dat else '✗'} {nhan}: không dùng tool  (tool_plan={thuc!r})")
        else:
            dat = thuc == mong_doi and (r.get("tool_calls") or 0) >= 1
            print(f"  {'✓' if dat else '✗'} {nhan}: kế hoạch `{mong_doi}` VÀ tool đã chạy  "
                  f"(tool_plan={thuc!r}, tool_calls={r.get('tool_calls')!r})")
        loi += 0 if dat else 1

    print()
    if loi == 0:
        print("  => ĐƯỜNG ĐI ĐÚNG. Soát hoá đơn vào vòng agentic, báo giá giữ luồng n8n.")
    else:
        print(f"  => {loi} MỤC SAI — gửi nguyên bảng này về, đừng sửa gì thêm.")
    return 0 if loi == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
