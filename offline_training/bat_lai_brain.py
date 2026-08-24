"""
bat_lai_brain.py — dọn GPU, nạp bản vá, bật lại Brain, hâm nóng, mở hầm.

CHẠY BẰNG `%run -i`, KHÔNG PHẢI `!python`:

    !cd /content/ANSER_AI && git fetch -q origin feat/lop-provider-cho-benchmark \
        && git reset -q --hard FETCH_HEAD
    %run -i /content/ANSER_AI/offline_training/bat_lai_brain.py

`%run -i` thực thi trong không gian tên notebook nên `BRAIN_URL`/`proc` còn lại
sau khi chạy, và đọc được `AWQ` mà ô 4.2 đã đặt. `!python` thì uvicorn chết theo
tiến trình con.

--------------------------------------------------------------------------
BA LỖI CỦA BẢN TRƯỚC (phiên 23/08/2026) — lý do file này được viết lại
--------------------------------------------------------------------------
1. `pkill -f "src.api.main:app"` CHỈ giết được tiến trình cha. vLLM spawn
   `VLLM::EngineCore` thành TIẾN TRÌNH RIÊNG, dòng lệnh của nó không chứa chuỗi
   đó. Nó sống sót thành mồ côi ôm 12.7GB; server mới xin 12.7GB trong khi chỉ
   còn ~10.3GB nên engine hỏng, và POST /chat trả 503 "Text runtime
   unavailable". Nay giết theo **PID mà nvidia-smi báo** — không khớp chuỗi nữa.

2. Vòng chờ VRAM chạy 90s rồi IM LẶNG đi tiếp khi VRAM không về. Một cái kiểm
   không bao giờ chặn được gì. Nay **dừng hẳn** và nói phải làm gì.

3. `raise SystemExit(...) from e` trong `%run` làm bộ định dạng traceback của
   IPython vỡ (AttributeError trên f_lineno), chôn mất dòng thông báo thật.
   Nay không raise: mọi lỗi in ra rõ rồi `return None`.

Và khi engine hỏng thì đọc `engine_error` trong /health + đuôi brain.log —
nguyên nhân nằm sẵn ở đó ngay từ đầu, bản trước không thèm đọc.

--------------------------------------------------------------------------
NGÂN SÁCH VRAM trên L4 23034 MiB (đo thật 23/08/2026)
--------------------------------------------------------------------------
  vLLM (VLLM::EngineCore, tiến trình riêng) . 12706 MiB  = 0.55 x 23034
  VLM Qwen2.5-VL-3B (TRONG tiến trình cha) ..  7876 MiB  <- "ẩn số 7.8GB"
  ------------------------------------------------------------------
  tổng ...................................... 20582 / 23034, dư ~2.4GB

`engine.py:219` nạp VLM thẳng vào tiến trình cha bằng transformers
(device_map="cuda"), NGOÀI pool của vLLM — comment ở đó đã dự báo "~7,5GB".
Không phải rò rỉ. Nhưng sát trần, nên **phải dọn sạch trước khi bật lại**.
Lưu ý: `RUNTIME_PROFILE=text-only` KHÔNG bỏ được VLM (nó chỉ chặn VisionAgent,
engine vẫn nạp) — muốn nhẹ thì `VISION_MODEL_ID=Qwen/Qwen2-VL-2B-Instruct`.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "/content/ANSER_AI"
DUONG_LOG = "/content/brain.log"
DUONG_DO = "/content/ai_metrics.jsonl"
NGUONG_SACH_MB = 1024          # dưới mức này coi như GPU đã trống

# SIGKILL chỉ có trên POSIX. Colab là Linux nên luôn có; khai kiểu này để mypy
# chạy được cả trên máy Windows của dev mà không phải bỏ qua dòng nào.
SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _vram(nhan: str) -> None:
    tong = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
         "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    ai = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
         "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    print(f"  -- {nhan}\n     tổng: {tong}")
    for dong in (ai.splitlines() or ["(không tiến trình nào giữ VRAM)"]):
        print(f"     {dong}")


def _vram_mb() -> int:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().splitlines()
    return int(r[0]) if r else -1


def _pid_giu_vram() -> list[int]:
    """PID đang giữ VRAM, TRỪ chính tiến trình notebook."""
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid",
                          "--format=csv,noheader"],
                         capture_output=True, text=True).stdout
    toi = os.getpid()
    return [int(x) for x in out.split() if x.strip().isdigit() and int(x) != toi]


def _cho_vram_ve(giay: float) -> bool:
    han = time.time() + giay
    while time.time() < han:
        if _vram_mb() < NGUONG_SACH_MB:
            return True
        time.sleep(2)
    return _vram_mb() < NGUONG_SACH_MB


def _don_gpu() -> bool:
    """Giết mọi tiến trình đang giữ VRAM. Trả False nếu KHÔNG dọn được."""
    # uvicorn có thể chưa cấp phát VRAM nào -> nvidia-smi không thấy. Vẫn phải giết.
    subprocess.run(["pkill", "-f", "src.api.main:app"])

    for ten_tin, sig in (("SIGTERM", signal.SIGTERM), ("SIGKILL", SIGKILL)):
        pids = _pid_giu_vram()
        if not pids and _vram_mb() < NGUONG_SACH_MB:
            return True
        if pids:
            print(f"  > {ten_tin} tới {pids}")
            for pid in pids:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    print(f"    ! không có quyền giết PID {pid}")
        if _cho_vram_ve(30):
            return True
    return False


def _health(giay: float = 3.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=giay) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return None


def _duoi_log(n: int = 2500) -> str:
    try:
        with open(DUONG_LOG, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return "(không đọc được log)"


def _bao_loi_engine() -> None:
    """Engine hỏng thì nguyên nhân nằm ở /health + brain.log. In cả hai."""
    h = _health()
    print("\n" + "!" * 74)
    print("  ENGINE KHÔNG DỰNG ĐƯỢC — nguyên nhân:")
    print("!" * 74)
    if h:
        for khoa in ("engine_error", "kb_error", "vision_error"):
            if h.get(khoa):
                print(f"  {khoa}: {h[khoa]}")
    print(f"\n  --- đuôi {DUONG_LOG} ---")
    print(_duoi_log())


def _van(tok: str) -> str:
    return f"{tok[:4]}...{tok[-4:]}"


def _chay():
    """Trả dict khi xong, None khi hỏng. KHÔNG raise — `%run` không chịu nổi."""
    print("=" * 74)
    print("  MỐC 1 — trước khi dọn")
    print("=" * 74)
    _vram("mốc-1")

    print("\n> dọn GPU (giết theo PID nvidia-smi báo, không khớp chuỗi dòng lệnh)...")
    if not _don_gpu():
        print("\n" + "!" * 74)
        print("  KHÔNG DỌN ĐƯỢC GPU — DỪNG Ở ĐÂY, KHÔNG ĐI TIẾP.")
        print("!" * 74)
        _vram("còn kẹt")
        print("\n  Bật server mới lúc này chắc chắn hỏng: vLLM xin "
              f"{0.55 * 23034 / 1024:.1f}GB mà GPU không đủ trống.")
        print("  Làm: Runtime > Restart runtime, rồi chạy lại ô 4, 4.1 và ô này.")
        print("  (restart sinh API_AUTH_TOKEN MỚI -> phải dán lại .env.local của Body)")
        return None

    print("\n" + "=" * 74)
    print("  MỐC 2 — sau khi dọn (phải ~0)")
    print("=" * 74)
    _vram("mốc-2")

    # --- Không tin `git` nói xong là xong: kiểm ĐÚNG dòng mã cần có mặt ----
    print("\n> HEAD:", subprocess.run(["git", "-C", REPO, "log", "--oneline", "-1"],
                                      capture_output=True, text=True).stdout.strip())
    with open(f"{REPO}/src/api/routes/chat.py", encoding="utf-8") as f:
        ma_chat = f.read()
    with open(f"{REPO}/src/core/tool_planner.py", encoding="utf-8") as f:
        ma_plan = f.read()
    if "soat_hoa_don_logistics" not in ma_chat or "def la_cau_soat_hoa_don" not in ma_plan:
        print("\n  x THIẾU bản vá định tuyến. Chạy dòng `git fetch ... && git reset --hard`"
              " ở ngay trên rồi %run lại file này.")
        return None
    print("  v có bản vá định tuyến (soat_hoa_don_logistics + la_cau_soat_hoa_don)")

    # --- Bật Brain mới -----------------------------------------------------
    awq = globals().get("AWQ") or "/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-awq"
    if not os.path.isdir(awq):
        print(f"\n  x Không thấy {awq} — chạy ô 26/28 trước.")
        return None
    if not os.environ.get("API_AUTH_TOKEN"):
        print("\n  x Chưa có API_AUTH_TOKEN — chạy ô 4.1 trước.")
        return None

    env = {
        **os.environ,
        "ENV": "SERVER",
        "TEXT_MODEL_ID": awq,
        "PYTHONPATH": REPO,
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        # MỘT generate MỘT LÚC: vLLM V1 `LLM.generate` KHÔNG thread-safe.
        "ANSER_TEXT_MAX_CONCURRENT": "1",
        # Để chay_thu_live.py đọc được route/tool_plan/tool_calls thật.
        # KHÔNG bật AI_METRICS_LOG_CONTENT — nội dung tin nhắn là dữ liệu khách (R2/P2).
        "AI_METRICS_PATH": DUONG_DO,
    }
    print(f"\n> bật uvicorn mới · token {_van(env['API_AUTH_TOKEN'])} · log {DUONG_LOG}")
    log_f = open(DUONG_LOG, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app",
         "--host", "0.0.0.0", "--port", "8000"],
        cwd=REPO, env=env, stdout=log_f, stderr=subprocess.STDOUT)

    health = None
    for _ in range(60):
        if proc.poll() is not None:
            print(f"\n  x uvicorn chết sớm, mã thoát {proc.returncode}")
            print(_duoi_log())
            return None
        health = _health()
        if health:
            break
        time.sleep(5)
    if not health:
        print(f"\n  x Brain không trả lời /health sau 5 phút — xem {DUONG_LOG}")
        proc.terminate()
        return None
    if not health.get("auth_enabled"):
        print("\n  x Brain KHÔNG kiểm token — API_AUTH_TOKEN rỗng lúc uvicorn khởi động.")
        proc.terminate()
        return None
    print("  v /health:", json.dumps(health, ensure_ascii=False)[:180])

    # --- Chốt chặn danh tính: body HỢP LỆ, không phải {} -------------------
    # FastAPI validate body TRƯỚC thân hàm, nên `{}` luôn 422 và
    # `require_api_token` không bao giờ chạy tới — đèn xanh cho cả token bịa.
    rq = urllib.request.Request(
        "http://127.0.0.1:8000/tools/vat",
        data=b'{"items":[],"stated_total":0}',
        headers={"Content-Type": "application/json", "X-API-Token": env["API_AUTH_TOKEN"]},
        method="POST")
    try:
        urllib.request.urlopen(rq, timeout=10).read()
        ma = 200
    except urllib.error.HTTPError as e:
        ma = e.code
    if ma == 401:
        print("\n  x Cổng 8000 KHÔNG phải server vừa bật (401). Restart runtime rồi làm lại.")
        proc.terminate()
        return None
    if ma == 422:
        print("  ! 422 — lược đồ VatRequest đã đổi, phép thử này không kiểm được auth nữa")
    print(f"  v token phiên này được chấp nhận (/tools/vat -> {ma})")

    print("\n" + "=" * 74)
    print("  MỐC 3 — uvicorn sống, model CHƯA nạp")
    print("=" * 74)
    _vram("mốc-3")
    print(f"     engine_ready={health.get('engine_ready')}  <- phải là False")

    # --- HÂM NÓNG ----------------------------------------------------------
    # `POST /chat` KHÔNG trả ngay: chat.py:438 await `ensure_text_runtime()`
    # TRƯỚC khi tạo `task_id`, nên nó chờ trọn 1-3 phút nạp model. Mà Body ghim
    # TIMEOUT_MS.chat — câu ĐẦU TIÊN người dùng gõ vào UI sau mỗi lần Brain khởi
    # động lại sẽ timeout, và hiện ra đúng như "model không chạy". Chịu ở đây.
    print("\n> hâm nóng: ép nạp model ngay (1-3 phút — chịu ở đây để người dùng khỏi chịu)...")
    t0 = time.time()
    rq2 = urllib.request.Request(
        "http://127.0.0.1:8000/chat",
        data=json.dumps({"user_id": "ham-nong", "store_id": "1",
                         "message": "Xin chào"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Token": env["API_AUTH_TOKEN"]},
        method="POST")
    try:
        with urllib.request.urlopen(rq2, timeout=900) as resp:
            tid = json.loads(resp.read())["task_id"]
    except urllib.error.HTTPError as e:
        print(f"\n  x POST /chat trả {e.code}: {e.read()[:200]!r}")
        if e.code == 503:
            _bao_loi_engine()
        proc.terminate()
        return None
    giay_nap = time.time() - t0
    print(f"  v model nạp xong sau {giay_nap:.0f}s")

    ans = None
    for _ in range(150):
        time.sleep(2)
        with urllib.request.urlopen(
                f"http://127.0.0.1:8000/api/v1/task/{tid}", timeout=15) as rp:
            tt = json.loads(rp.read())
        if tt.get("status") == "completed":
            kq = tt.get("result") or {}
            ans = kq.get("answer") if isinstance(kq, dict) else str(kq)
            break
        if tt.get("status") == "failed":
            ans = f"[THẤT BẠI] {tt.get('error')}"
            break
    tong = time.time() - t0
    print(f"  v câu trả lời đầu sau tổng {tong:.0f}s ({tong - giay_nap:.0f}s sinh chữ):")
    print(f"    {str(ans)[:220]}")

    print("\n" + "=" * 74)
    print("  MỐC 4 — model ĐÃ nạp (so mốc 3: 7.9GB là VLM trong tiến trình cha)")
    print("=" * 74)
    _vram("mốc-4")

    # --- Đường hầm: tái dùng hầm cũ nếu còn sống ---------------------------
    from pyngrok import conf, ngrok

    tok = os.environ.get("NGROK_AUTHTOKEN", "").strip()
    if tok:
        ngrok.set_auth_token(tok)
    conf.get_default().region = "ap"
    # `get_tunnels()` ném lỗi khi chưa có tiến trình ngrok nào (runtime mới) —
    # đó là trạng thái BÌNH THƯỜNG, không phải hỏng.
    try:
        cu = [t for t in ngrok.get_tunnels()
              if str(t.config.get("addr", "")).endswith(":8000")]
    except Exception:
        cu = []
    if cu:
        url = cu[0].public_url
        print("\n> tái dùng hầm cũ — URL KHÔNG đổi, Body không phải sửa .env.local")
    else:
        url = ngrok.connect(8000).public_url
        print("\n> mở hầm mới — URL ĐỔI, phải dán lại vào Body")
    os.environ["BRAIN_URL"] = url
    return {"BRAIN_URL": url, "proc": proc}


_kq = _chay()
if _kq is not None:
    BRAIN_URL = _kq["BRAIN_URL"]
    proc = _kq["proc"]
    print("=" * 74)
    print("  HAI DÒNG CHO  frontend/.env.local  CỦA BODY")
    print("=" * 74)
    print(f"BRAIN_URL={BRAIN_URL}")
    print(f"BRAIN_API_TOKEN={os.environ['API_AUTH_TOKEN']}")
    print("=" * 74)
    print("\n> Xong, model ĐÃ nóng. Chạy tiếp:")
    print("  !cd /content/ANSER_AI && python offline_training/chay_thu_live.py")
else:
    print("\n> DỪNG. Không bật được Brain — đọc khối lỗi ở trên, đừng chạy ô sau.")
