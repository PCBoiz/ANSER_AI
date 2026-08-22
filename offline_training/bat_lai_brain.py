"""
bat_lai_brain.py — tắt Brain cũ, nạp bản vá, bật lại, mở hầm. Cho Colab.

CHẠY BẰNG `%run -i`, KHÔNG PHẢI `!python`:

    !cd /content/ANSER_AI && git fetch -q origin feat/lop-provider-cho-benchmark \
        && git reset -q --hard FETCH_HEAD
    %run -i /content/ANSER_AI/offline_training/bat_lai_brain.py

`%run -i` thực thi ngay trong không gian tên notebook, nên `BRAIN_URL` và `proc`
còn lại sau khi chạy, và script đọc được `AWQ` mà ô 4.2 đã đặt. `!python` thì
mọi thứ chết theo tiến trình con — kể cả uvicorn.

VÌ SAO PHẢI RESTART UVICORN, KHÔNG CHỈ `git pull`:
bản vá định tuyến (`soat_hoa_don_logistics`) và giới hạn đồng thời nằm trong mã
ĐÃ NẠP VÀO BỘ NHỚ tiến trình đang chạy. `git pull` đổi file trên đĩa, không đổi
được tiến trình. Đổi lại: model phải nạp lại, mất 1–3 phút ở câu chat đầu.

Đo VRAM ba mốc kèm PID đang giữ — để giải ẩn số 7.8GB trong tiến trình uvicorn
(ngoài 12.7GB của `VLLM::EngineCore`).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "/content/ANSER_AI"
DUONG_LOG = "/content/brain.log"
DUONG_DO = "/content/ai_metrics.jsonl"


def _vram(nhan: str) -> None:
    tong = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
         "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    ai = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
         "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    print(f"  ── {nhan}\n     tổng: {tong}")
    for dong in (ai.splitlines() or ["(không tiến trình nào giữ VRAM)"]):
        print(f"     {dong}")


def _vram_mb() -> int:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().splitlines()
    return int(r[0]) if r else -1


def _health(giay: float = 3.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=giay) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None


def _van(tok: str) -> str:
    return f"{tok[:4]}…{tok[-4:]}"


print("=" * 74)
print("  MỐC 1 — trước khi tắt uvicorn cũ (model đang nằm trong VRAM)")
print("=" * 74)
_vram("mốc-1")

# --- Tắt uvicorn cũ. PHẢI xong trước khi bật cái mới, không thì OOM. --------
print("\n▸ tắt uvicorn cũ…")
subprocess.run(["pkill", "-f", "src.api.main:app"])
for _ in range(45):
    time.sleep(2)
    if _vram_mb() < 1500:
        break
print("\n" + "=" * 74)
print("  MỐC 2 — sau khi tắt (VRAM phải về ~0; còn dư nhiều = rò)")
print("=" * 74)
_vram("mốc-2")

# --- Không tin `git` nói xong là xong: kiểm ĐÚNG dòng mã cần có mặt --------
print("\n▸ HEAD:", subprocess.run(["git", "-C", REPO, "log", "--oneline", "-1"],
                                  capture_output=True, text=True).stdout.strip())
with open(f"{REPO}/src/api/routes/chat.py", encoding="utf-8") as f:
    _chat = f.read()
with open(f"{REPO}/src/core/tool_planner.py", encoding="utf-8") as f:
    _plan = f.read()
if "soat_hoa_don_logistics" not in _chat or "def la_cau_soat_hoa_don" not in _plan:
    raise SystemExit(
        "THIẾU bản vá định tuyến. Chạy dòng `git fetch … && git reset --hard` "
        "ở ngay trên rồi %run lại file này."
    )
print("  ✓ có bản vá định tuyến (soat_hoa_don_logistics + la_cau_soat_hoa_don)")

# --- Bật Brain mới ---------------------------------------------------------
AWQ = globals().get("AWQ") or "/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-awq"
if not os.path.isdir(AWQ):
    raise SystemExit(f"Không thấy {AWQ} — chạy ô 26/28 trước")
if not os.environ.get("API_AUTH_TOKEN"):
    raise SystemExit("Chưa có API_AUTH_TOKEN — chạy ô 4.1 trước")

env = {
    **os.environ,
    "ENV": "SERVER",
    "TEXT_MODEL_ID": AWQ,
    "PYTHONPATH": REPO,
    "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
    # MỘT generate MỘT LÚC. Không phải tối ưu hoá — vLLM V1 `LLM.generate` KHÔNG
    # thread-safe, hai request chồng nhau là mọi câu bò ~10 phút, GPU-Util 0%.
    "ANSER_TEXT_MAX_CONCURRENT": "1",
    # Để `chay_thu_live.py` đọc được route/tool_plan/tool_calls thật của từng lượt.
    # KHÔNG bật AI_METRICS_LOG_CONTENT: nội dung tin nhắn là dữ liệu khách (R2/P2).
    "AI_METRICS_PATH": DUONG_DO,
}
print(f"\n▸ bật uvicorn mới · token {_van(env['API_AUTH_TOKEN'])} · log {DUONG_LOG}")
_log = open(DUONG_LOG, "w")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"],
    cwd=REPO, env=env, stdout=_log, stderr=subprocess.STDOUT)

health = None
for _ in range(60):
    if proc.poll() is not None:
        with open(DUONG_LOG, encoding="utf-8") as f:
            print(f.read()[-3000:])
        raise SystemExit(f"uvicorn chết sớm, mã thoát {proc.returncode}")
    health = _health()
    if health:
        break
    time.sleep(5)
if not health:
    raise SystemExit(f"Brain không trả lời /health sau 5 phút — xem {DUONG_LOG}")
if not health.get("auth_enabled"):
    raise SystemExit("Brain KHÔNG kiểm token — API_AUTH_TOKEN rỗng lúc uvicorn khởi động")
print("  ✓ /health:", json.dumps(health, ensure_ascii=False)[:180])

# --- Chốt chặn danh tính. Body HỢP LỆ, không phải {}. ----------------------
# FastAPI validate body TRƯỚC khi chạy thân hàm, nên `{}` luôn nhận 422 và
# `require_api_token` không bao giờ chạy tới — đèn xanh cho cả token bịa.
_req = urllib.request.Request(
    "http://127.0.0.1:8000/tools/vat",
    data=b'{"items":[],"stated_total":0}',
    headers={"Content-Type": "application/json", "X-API-Token": env["API_AUTH_TOKEN"]},
    method="POST")
try:
    urllib.request.urlopen(_req, timeout=10).read()
    _ma = 200
except urllib.error.HTTPError as e:
    _ma = e.code
if _ma == 401:
    proc.terminate()
    raise SystemExit("Cổng 8000 KHÔNG phải server vừa bật (401). Restart runtime rồi làm lại.")
if _ma == 422:
    print("  ⚠ 422 — lược đồ VatRequest đã đổi, phép thử này không kiểm được auth nữa")
print(f"  ✓ token phiên này được chấp nhận (/tools/vat -> {_ma})")

print("\n" + "=" * 74)
print("  MỐC 3 — uvicorn sống, model CHƯA nạp (nạp lười ở câu chat đầu)")
print("=" * 74)
_vram("mốc-3")
print(f"     engine_ready={health.get('engine_ready')}  <- phải là False")

# --- Đường hầm: tái dùng hầm cũ nếu còn sống -------------------------------
from pyngrok import conf, ngrok  # noqa: E402

_tok = os.environ.get("NGROK_AUTHTOKEN", "").strip()
if _tok:
    ngrok.set_auth_token(_tok)
conf.get_default().region = "ap"

# `get_tunnels()` ném lỗi khi chưa có tiến trình ngrok nào (runtime mới) —
# đó là trạng thái BÌNH THƯỜNG, không phải hỏng.
try:
    _cu = [t for t in ngrok.get_tunnels() if str(t.config.get("addr", "")).endswith(":8000")]
except Exception:
    _cu = []
if _cu:
    BRAIN_URL = _cu[0].public_url
    print("\n▸ tái dùng hầm cũ — URL KHÔNG đổi, Body không phải sửa .env.local")
else:
    BRAIN_URL = ngrok.connect(8000).public_url
    print("\n▸ mở hầm mới — URL ĐỔI, phải dán lại vào Body")
os.environ["BRAIN_URL"] = BRAIN_URL

print("=" * 74)
print("  HAI DÒNG CHO  frontend/.env.local  CỦA BODY")
print("=" * 74)
print(f"BRAIN_URL={BRAIN_URL}")
print(f"BRAIN_API_TOKEN={os.environ['API_AUTH_TOKEN']}")
print("=" * 74)
print("\n▸ Xong. Chạy tiếp:  !python offline_training/chay_thu_live.py")
print("  (câu đầu nạp model, 1–3 phút)")
