"""
do_ngan_sach_ctx.py — BR-04: dựng vLLM server trên Colab L4, đo ngân sách ngữ cảnh.

Mỗi mức `max_model_len` chạy trọn một vòng, VỚI VISION ĐANG NẠP (SRS BR-04 yêu
cầu 3 — đo lúc vision tắt rồi suy ra là tự cho mình một ngân sách không có):

  1. dọn GPU (giết theo PID nvidia-smi báo, như bat_lai_brain.py)
  2. `vllm serve` ở 127.0.0.1:8001, đọc dòng `GPU KV cache size` trong log
  3. thử `guided_json` trên server THẬT: bản vLLM lệch ghim thì trường này bị
     bỏ qua im lặng (test_ghim_vllm_duoi_0_12...), và chỉ server thật lộ ra
  4. bật Brain `ENV=GPU` + `VLLM_BASE_URL`: text qua server, vision nạp trong
     tiến trình Brain — đúng cấu hình BR-04
  5. một câu hỏi thật qua `POST /chat`, rồi lấy dòng log vLLM ghi nhận request
     của Brain (nghiệm thu BR-03 trên Colab)
  6. p95 ở mức đồng thời suy ra từ KV cache (yêu cầu 5, 6) và ở 4 (NFR-03)

CHẠY (runtime L4, đã mount Drive, đã cài vllm trong khoảng ghim):
    !cd /content/ANSER_AI && python offline_training/do_ngan_sach_ctx.py
    !cd /content/ANSER_AI && python offline_training/do_ngan_sach_ctx.py --muc 32768 --gmu 0.5

`inference_latency_p95` ở đây là độ trễ MỘT lời gọi `/v1/chat/completions` tới
vLLM, đo từ phía client, không gồm vòng agentic của Brain. ARCHITECTURE §13
không định nghĩa chặt hơn; ghi rõ để người đọc bảng không so nhầm.

Kết quả: bảng in ra cuối, JSON ở /content/br04_ket_qua.json, log từng mức ở
/content/br04_logs/. Mã thoát 0 khi mọi mức dựng được và Brain gọi tới nơi.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "offline_training"))
from chay_thu_live import HOA_DON  # noqa: E402  — cùng câu hoá đơn cố ý sai

AWQ_MAC_DINH = "/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-awq"
TEN_MODEL = "anser-v3"                     # trùng --served-model-name của compose
CONG_VLLM, CONG_BRAIN = 8001, 8000
THU_MUC_LOG = "/content/br04_logs"
DUONG_KQ = "/content/br04_ket_qua.json"
CTX_DICH = 32768                           # S2 đòi 32k: đơn vị quy đổi của yêu cầu 5
NGUONG_SACH_MB = 1024
SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------

def _smi(*truong: str) -> list[list[str]]:
    out = subprocess.run(["nvidia-smi", *truong, "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return [[o.strip() for o in d.split(",")] for d in out.strip().splitlines() if d.strip()]


def _vram_mb() -> int:
    r = _smi("--query-gpu=memory.used")
    return int(r[0][0]) if r else -1


def _vram_theo_pid() -> dict[int, int]:
    return {int(p): int(m) for p, m in _smi("--query-compute-apps=pid,used_memory")}


def _to_tien() -> set[int]:
    """PID của chính script và mọi tiến trình cha ông. Chạy bằng `!python` thì
    kernel Colab là ông của script: nó đã `import torch` lên GPU thì nvidia-smi
    liệt kê nó, và giết theo danh sách đó là giết luôn notebook."""
    pids, pid = set(), os.getpid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return pids


def _don_gpu() -> bool:
    """Giết mọi thứ đang giữ VRAM. vLLM V1 tách EngineCore thành tiến trình riêng
    nên khớp chuỗi dòng lệnh là không đủ — giết theo PID nvidia-smi báo."""
    subprocess.run(["pkill", "-f", "src.api.main:app"])
    subprocess.run(["pkill", "-f", "vllm serve"])
    tha = _to_tien()
    for sig in (signal.SIGTERM, SIGKILL):
        for pid in _vram_theo_pid():
            if pid not in tha:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
        han = time.time() + 30
        while time.time() < han:
            if _vram_mb() < NGUONG_SACH_MB:
                return True
            time.sleep(2)
    return False


class DinhVram:
    """Lấy mẫu nvidia-smi mỗi giây trong nền; giữ lại mức cao nhất."""

    def __init__(self):
        self.dinh = 0
        self._dung = threading.Event()
        self._t = threading.Thread(target=self._chay, daemon=True)

    def _chay(self):
        while not self._dung.is_set():
            self.dinh = max(self.dinh, _vram_mb())
            self._dung.wait(1.0)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._dung.set()
        self._t.join(timeout=3)


# ---------------------------------------------------------------------------
# Tiến trình
# ---------------------------------------------------------------------------

def _bat(lenh: list[str], log: str, env: dict) -> subprocess.Popen:
    # Phiên riêng để giết được cả cây tiến trình (EngineCore của vLLM).
    return subprocess.Popen(lenh, cwd=REPO, env=env, stdout=open(log, "w"),
                            stderr=subprocess.STDOUT, start_new_session=True)


def _tat(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    for sig in (signal.SIGTERM, SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=30)
            return
        except subprocess.TimeoutExpired:
            continue


def _doc(duong: str, tu: int = 0) -> str:
    try:
        with open(duong, encoding="utf-8", errors="replace") as f:
            return f.read()[tu:]
    except OSError:
        return ""


def _cho_song(url: str, proc: subprocess.Popen, giay: float) -> bool:
    han = time.time() + giay
    while time.time() < han:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(5)
    return False


# ---------------------------------------------------------------------------
# Đo
# ---------------------------------------------------------------------------

def _doc_kv(log: str) -> tuple[int | None, float | None]:
    """-> (số token KV cache, độ đồng thời vLLM tự báo ở max_model_len)."""
    kv = re.findall(r"GPU KV cache size:\s*([\d,]+)\s*tokens", log)
    dt = re.findall(r"Maximum concurrency for [\d,]+ tokens per request:\s*([\d.]+)x", log)
    return (int(kv[-1].replace(",", "")) if kv else None,
            float(dt[-1]) if dt else None)


def _thu_guided(url: str) -> tuple[bool, str]:
    """Server có THI HÀNH guided_json không. Bị bỏ qua thì đầu ra sẽ là văn xuôi."""
    schema = {"type": "object", "additionalProperties": False,
              "required": ["tool", "ly_do"],
              "properties": {"tool": {"type": "string", "enum": ["vat", "pricing"]},
                             "ly_do": {"type": "string", "maxLength": 80}}}
    try:
        r = httpx.post(f"{url}/v1/chat/completions", timeout=120, json={
            "model": TEN_MODEL, "max_tokens": 128, "temperature": 0.1,
            "repetition_penalty": 1.0, "guided_json": schema,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": "Kể cho tôi một câu chuyện vui."}],
        })
        noi_dung = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        # Server từ chối trường guided_json cũng là "không thi hành" — ghi lại, đo tiếp.
        return False, f"{type(exc).__name__}: {exc}"
    try:
        obj = json.loads(noi_dung)
        return (set(obj) == {"tool", "ly_do"} and obj["tool"] in ("vat", "pricing")), noi_dung
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False, noi_dung


def _hoi_brain(msg: str, gio: float) -> tuple[str, float]:
    """Đúng đường Body: POST /chat -> task_id -> poll. Câu đầu chờ cả lúc nạp vision."""
    goc = f"http://127.0.0.1:{CONG_BRAIN}"
    t0 = time.time()
    # `POST /chat` chờ trọn lúc nạp runtime TRƯỚC khi trả task_id (chat.py), nên
    # `gio` áp cho cả POST. Hết giờ thì trả chuỗi lỗi, không ném: ném ra ngoài là
    # mất luôn đuôi log Brain — thứ duy nhất nói vì sao nó chậm.
    #
    # `X-User-Id` PHẢI khớp `user_id` trong thân: GET /api/v1/task/{id} chỉ trả
    # kết quả cho chủ task, sai hoặc thiếu thì 404 (chat.py). Bản đầu không gửi
    # header này, nhận 404 mỗi lần hỏi và chờ trọn 30 phút trong khi câu trả lời
    # đã nằm sẵn trong Brain (phiên Colab 26/10/2026).
    nguoi = "br04"
    try:
        with httpx.Client(timeout=gio, headers={"X-User-Id": nguoi}) as c:
            r = c.post(f"{goc}/chat", json={"user_id": nguoi, "store_id": "1", "message": msg})
            if r.status_code != 200:
                return f"[POST /chat {r.status_code}] {r.text[:200]}", time.time() - t0
            tid = r.json().get("task_id")
            han = time.time() + gio
            while time.time() < han:
                time.sleep(2)
                rp = c.get(f"{goc}/api/v1/task/{tid}")
                if rp.status_code != 200:
                    # Không hỏi lại: 404 ở đây là sai chủ hoặc task mất, chờ thêm
                    # không làm nó tự đúng.
                    return f"[GET task {rp.status_code}] {rp.text[:200]}", time.time() - t0
                tt = rp.json()
                if tt.get("status") == "completed":
                    kq = tt.get("result") or {}
                    return str(kq.get("answer") if isinstance(kq, dict) else kq), time.time() - t0
                if tt.get("status") == "failed":
                    return f"[THẤT BẠI] {tt.get('error')}", time.time() - t0
    except httpx.HTTPError as exc:
        return f"[LỖI {type(exc).__name__} sau {time.time() - t0:.0f}s] {exc}", time.time() - t0
    return f"[HẾT GIỜ sau {gio:.0f}s]", time.time() - t0


def _tai_truoc_model() -> None:
    """Kéo về cache HF các model Brain nạp lúc /chat đầu: vision, embedder, reranker.

    Không tải trước thì phút tải 10GB trên runtime mới bị tính vào phiên đo, và
    câu /chat đầu vượt mọi trần thời gian (26/10/2026: quá 15 phút ở mức 8192).
    Đọc tên model từ chính `Config` (R4), không chép lại ở đây.
    """
    from huggingface_hub import snapshot_download

    sys.path.insert(0, REPO)
    from src.core.config import Config

    cfg = Config()
    ten = [cfg.vision_model_id, cfg.embedding_model_id, cfg.reranker_model_id]
    for t in dict.fromkeys(t for t in ten if t and not os.path.isdir(t)):
        t0 = time.time()
        print(f"  > tải trước {t} ...", flush=True)
        try:
            snapshot_download(t)
            print(f"    v xong sau {time.time() - t0:.0f}s", flush=True)
        except Exception as exc:  # tải hỏng thì Brain tự tải lại, chỉ chậm hơn
            print(f"    ! không tải trước được: {type(exc).__name__}: {exc}", flush=True)


def _p95(url: str, dong_thoi: int, so_request: int) -> dict:
    """Độ trễ một lời gọi chat tới vLLM, `dong_thoi` lời gọi bay cùng lúc."""
    body = {
        "model": TEN_MODEL, "max_tokens": 384, "temperature": 0.1,
        "repetition_penalty": 1.25, "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": "Bạn là trợ lý kế toán kho vận."},
                     {"role": "user", "content": HOA_DON}],
    }

    def mot(_):
        t0 = time.perf_counter()
        r = httpx.post(f"{url}/v1/chat/completions", json=body, timeout=300)
        return (time.perf_counter() - t0) * 1000, r.status_code

    with ThreadPoolExecutor(dong_thoi) as ex:
        kq = list(ex.map(mot, range(so_request)))
    ms = sorted(t for t, ma in kq if ma == 200)
    if not ms:
        return {"dong_thoi": dong_thoi, "loi": so_request}
    return {"dong_thoi": dong_thoi, "n": len(ms), "loi": so_request - len(ms),
            "p50_ms": round(ms[len(ms) // 2]),
            "p95_ms": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))])}


# ---------------------------------------------------------------------------
# Một mức max_model_len
# ---------------------------------------------------------------------------

def do_mot_muc(muc: int, gmu: float, awq: str, gio_cau_dau: float) -> dict:
    kq: dict = {"max_model_len": muc, "gpu_memory_utilization": gmu, "dung_duoc": False}
    print(f"\n{'=' * 74}\n  max_model_len={muc}  gpu_memory_utilization={gmu}\n{'=' * 74}")

    if not _don_gpu():
        kq["ly_do"] = f"không dọn được GPU (còn {_vram_mb()} MiB) — Restart runtime"
        print("  x", kq["ly_do"])
        return kq

    log_vllm = f"{THU_MUC_LOG}/vllm_{muc}_{gmu}.log"
    log_brain = f"{THU_MUC_LOG}/brain_{muc}_{gmu}.log"
    url_vllm = f"http://127.0.0.1:{CONG_VLLM}"
    vllm = brain = None
    with DinhVram() as dinh:
        try:
            # Không --disable-log-requests (khác compose): ở đây cần log ghi nhận
            # request làm bằng chứng, và câu hỏi là dữ liệu tổng hợp, không phải của khách.
            vllm = _bat(["vllm", "serve", awq, "--served-model-name", TEN_MODEL,
                         "--host", "127.0.0.1", "--port", str(CONG_VLLM),
                         "--max-model-len", str(muc), "--gpu-memory-utilization", str(gmu)],
                        log_vllm, dict(os.environ))
            print(f"  > vllm serve ... (log {log_vllm})")
            if not _cho_song(f"{url_vllm}/health", vllm, 900):
                kq["ly_do"] = "vLLM không dựng nổi"
                print(f"  x {kq['ly_do']} — đuôi log:\n{_doc(log_vllm)[-2500:]}")
                return kq

            kq["kv_tokens"], kq["vllm_dong_thoi_tai_muc"] = _doc_kv(_doc(log_vllm))
            print(f"  v vLLM sống · KV cache {kq['kv_tokens']} token")
            kq["guided_ok"], mau = _thu_guided(url_vllm)
            print(f"  {'v' if kq['guided_ok'] else 'x'} guided_json: {mau[:100]}")

            env = {**os.environ, "ENV": "GPU", "PYTHONPATH": REPO,
                   "VLLM_BASE_URL": f"{url_vllm}/v1", "VLLM_MODEL": TEN_MODEL,
                   "AI_METRICS_PATH": f"{THU_MUC_LOG}/ai_metrics.jsonl"}
            env.pop("API_AUTH_TOKEN", None)          # chỉ nghe 127.0.0.1, không mở hầm
            brain = _bat([sys.executable, "-m", "uvicorn", "src.api.main:app",
                          "--host", "127.0.0.1", "--port", str(CONG_BRAIN)], log_brain, env)
            if not _cho_song(f"http://127.0.0.1:{CONG_BRAIN}/health", brain, 300):
                kq["ly_do"] = "Brain không lên"
                print(f"  x {kq['ly_do']} — đuôi log:\n{_doc(log_brain)[-2500:]}")
                return kq

            moc_log = len(_doc(log_vllm))
            vram_truoc_brain = _vram_mb()
            print(f"  > câu hoá đơn qua POST /chat (lần đầu nạp vision, tới {gio_cau_dau:.0f}s)...",
                  flush=True)
            tra_loi, giay = _hoi_brain(HOA_DON, gio_cau_dau)
            kq["brain_giay"] = round(giay, 1)
            kq["brain_tra_loi"] = tra_loi[:300]
            print(f"  {giay:.0f}s · {tra_loi[:200]}")
            if tra_loi.startswith("["):
                print(f"  --- đuôi {log_brain} ---\n{_doc(log_brain)[-3000:]}")

            dong = [d for d in _doc(log_vllm, moc_log).splitlines()
                    if "/v1/chat/completions" in d or "/v1/completions" in d]
            kq["log_vllm_ghi_nhan"] = dong[:5]
            print(f"  {'v' if dong else 'x'} log vLLM ghi nhận {len(dong)} request của Brain")
            for d in dong[:3]:
                print(f"     {d.strip()[:150]}")

            # Số chính là phần VRAM tăng thêm khi Brain nạp: nvidia-smi trong
            # container không phải lúc nào cũng thấy PID. Số theo PID chỉ để đối chiếu.
            kq["vision_mib"] = _vram_mb() - vram_truoc_brain
            kq["vision_mib_theo_pid"] = _vram_theo_pid().get(brain.pid)
            if kq["vision_mib"] < 4000:
                print(f"  ! Brain chỉ thêm {kq['vision_mib']} MiB — vision CHƯA nạp, "
                      "số đo mức này KHÔNG hợp lệ theo yêu cầu 3")

            kv = kq["kv_tokens"] or 0
            kq["so_request_32k"] = round(kv / CTX_DICH, 2)
            n = max(1, kv // CTX_DICH)
            kq["p95"] = []
            for dt in sorted({n, 4}):
                print(f"  > p95 ở {dt} request đồng thời...")
                kq["p95"].append(_p95(url_vllm, dt, max(20, 5 * dt)))
                print(f"     {kq['p95'][-1]}")
            kq["dung_duoc"] = True
        finally:
            _tat(brain)
            _tat(vllm)
    kq["vram_dinh_mib"] = dinh.dinh
    print(f"  VRAM đỉnh {dinh.dinh} MiB")
    return kq


def _bang(ket_qua: list[dict]) -> str:
    dau = ("| max_model_len | gmu | dựng được | VRAM đỉnh (MiB) | GPU KV cache (token) "
           "| request 32k song song | vision (MiB) | guided_json | p95 (ms) |\n"
           "|---|---|---|---|---|---|---|---|---|")
    dong = []
    for k in ket_qua:
        p95 = "; ".join(f"{p['dong_thoi']}× → {p.get('p95_ms', 'lỗi')}" for p in k.get("p95", []))
        dong.append(
            f"| {k['max_model_len']} | {k['gpu_memory_utilization']} "
            f"| {'có' if k['dung_duoc'] else 'không: ' + k.get('ly_do', '?')} "
            f"| {k.get('vram_dinh_mib', '')} | {k.get('kv_tokens', '')} "
            f"| {k.get('so_request_32k', '')} | {k.get('vision_mib', '')} "
            f"| {'đạt' if k.get('guided_ok') else ('KHÔNG' if 'guided_ok' in k else '')} "
            f"| {p95} |")
    return dau + "\n" + "\n".join(dong)


def _vllm_trong_khoang_ghim() -> tuple[bool, str]:
    """SRS BR-02 yêu cầu 5: server PHẢI nằm trong khoảng ghim của requirements.txt.
    Lệch ra ngoài thì `guided_json` có thể bị bỏ qua im lặng (SRS §8.1)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        v = version("vllm")
    except PackageNotFoundError:
        return False, "chưa cài"
    so = tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    return (0, 10, 2) <= so < (0, 12), v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--muc", default="8192,16384,32768", help="các max_model_len, phẩy ngăn")
    ap.add_argument("--gmu", type=float, default=0.55, help="gpu_memory_utilization")
    ap.add_argument("--awq", default=os.environ.get("AWQ", AWQ_MAC_DINH))
    ap.add_argument("--gio-cau-dau", type=float, default=1800,
                    help="giây chờ câu /chat đầu, gồm cả lúc Brain nạp vision + kho tri thức")
    ap.add_argument("--khong-tai-truoc", action="store_true",
                    help="bỏ bước tải trước model vào cache HF")
    a = ap.parse_args()

    ok, v = _vllm_trong_khoang_ghim()
    if not ok:
        print(f"x vllm {v} nằm ngoài khoảng ghim >=0.10.2,<0.12. Cài lại:\n"
              '    !pip install -q "vllm>=0.10.2,<0.12"')
        return 1
    print(f"v vllm {v} trong khoảng ghim")
    if not os.path.isdir(a.awq):
        print(f"x Không thấy model ở {a.awq} — mount Drive hoặc đặt --awq.")
        return 1
    os.makedirs(THU_MUC_LOG, exist_ok=True)
    if not a.khong_tai_truoc:
        _tai_truoc_model()

    ket_qua = []
    try:
        for muc in (int(x) for x in a.muc.split(",")):
            ket_qua.append(do_mot_muc(muc, a.gmu, a.awq, a.gio_cau_dau))
            with open(DUONG_KQ, "w", encoding="utf-8") as f:   # ghi dần: phiên ngắt vẫn còn số
                json.dump(ket_qua, f, ensure_ascii=False, indent=2)
    finally:
        _don_gpu()

    print(f"\n{'=' * 74}\n  BẢNG NGHIỆM THU BR-04 (dán vào PR)\n{'=' * 74}")
    print(_bang(ket_qua))
    print(f"\n  JSON: {DUONG_KQ} · log: {THU_MUC_LOG}/")
    ok = all(k["dung_duoc"] and k.get("log_vllm_ghi_nhan") for k in ket_qua)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
