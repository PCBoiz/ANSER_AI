"""
benchmark_integration.py — bộ kiểm thử tích hợp ĐẦU-CUỐI qua HTTP.

ĐO CÁI GÌ: cả ĐƯỜNG PHỤC VỤ, không riêng model — request đi qua đúng những lớp
mà người dùng thật đi qua: định tuyến (bảng luật `plan_tools` + SemanticRouter)
-> nhánh xử lý trong `src/api/routes/chat.py` -> tool tất định -> model ->
chốt chặn neo số liệu. Một ca trượt ở đây có thể do BẤT KỲ lớp nào, và đó là
chủ đích: `benchmark_v3.py` đã đo model RỜI (gọi thẳng engine, không qua HTTP);
bộ này đo thứ đến tay người dùng.

Về dữ liệu huấn luyện: các câu hỏi được viết để không trùng NGUYÊN VĂN với dữ
liệu huấn luyện vòng 2, nhưng sau các vòng sinh dữ liệu về sau thì điều đó
KHÔNG còn bảo đảm tuyệt đối. Giá trị của bộ này nằm ở phép đo đầu-cuối, không
phải ở phép đo chống thuộc lòng — việc đó là của benchmark_v3.

CHẠY (sau khi server ANSER đã lên):
  export BRAIN_URL=https://xxx.ngrok-free.dev
  python offline_training/benchmark_integration.py

Hằng số đo lường chỉnh qua env (mặc định an toàn cho 8B nguội trên L4):
  BENCH_HTTP_TIMEOUT=300  BENCH_POLL_MAX=150  BENCH_P95_NGUONG=60
"""
import asyncio
import json
import math
import os
import re
import sys
import time

import httpx

BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:8000")
HEADERS   = {"ngrok-skip-browser-warning": "true"}

# Token PHẢI gửi kèm, nếu không Brain trả 401 cho mọi ca — và bảng kết quả sẽ
# đọc thành "sáu ca hỏng" trong khi thật ra là MỘT lỗi cấu hình.
#
# Bản đầu của file này viết từ thời `API_AUTH_TOKEN` còn để rỗng, tức Brain
# KHÔNG kiểm token gì cả (`require_api_token` return sớm khi biến rỗng). Từ khi
# Brain được phơi ra Internet qua đường hầm thì token là bắt buộc, và script
# này bị bỏ lại phía sau.
#
# Nhận cả hai tên: `BRAIN_API_TOKEN` là tên phía CLIENT (Body dùng tên này),
# `API_AUTH_TOKEN` là tên phía SERVER — trên Colab cả hai đầu nằm chung một
# tiến trình nên chỉ có biến sau.
API_TOKEN = (os.environ.get("BRAIN_API_TOKEN")
             or os.environ.get("API_AUTH_TOKEN") or "").strip()
if API_TOKEN:
    HEADERS["X-API-Token"] = API_TOKEN


def dau_van(tok: str) -> str:
    """Vân tay token để đối chiếu bằng mắt — KHÔNG in cả token ra log."""
    return f"{tok[:4]}…{tok[-4:]}" if len(tok) >= 12 else "(quá ngắn)"


# Ba hằng số đo lường đọc từ env, mặc định phải sống được với lần chạy NGUỘI
# của Qwen3-8B AWQ trên L4 qua ngrok. Phiên 23/08/2026 dạy bài học này bằng
# ba ca hỏng: TIMEOUT=180 chết ngay ở request đầu (request đó gánh 1–3 phút
# nạp model lười), POLL_MAX=90×2s=180s làm T2/T3 trả [TIMEOUT] khi model còn
# nguội, còn ngưỡng p95=5s là hardcode từ một stack khác — vô nghĩa ở đây.
# Máy nhanh hơn thì SIẾT qua env, không sửa số trong file.
def doc_env_so(ten: str, mac_dinh: str, kieu):
    """
    Đọc một hằng đo lường từ env, chết SỚM và NÊU TÊN BIẾN nếu giá trị rác.

    Vì sao không để int()/float() tự nổ: traceback thô không nói BIẾN NÀO hỏng
    — int("90.0") chỉ in "invalid literal for int()", người chỉnh env phải tự
    đoán trong ba biến. Còn giá trị <= 0 thì không nổ mà âm thầm phá phép đo:
    BENCH_POLL_MAX=0 làm mọi ca trả "[TIMEOUT] 0s" trông hệt như server chết.
    """
    tho = os.environ.get(ten, mac_dinh)
    try:
        gia_tri = kieu(tho)
    except ValueError:
        sys.exit(f"  ✗ {ten}={tho!r} không đọc được thành {kieu.__name__}. "
                 f"Ví dụ hợp lệ: {ten}={mac_dinh}")
    if gia_tri <= 0:
        sys.exit(f"  ✗ {ten}={tho!r} phải là số DƯƠNG — 0 hay số âm không tắt "
                 f"phép đo mà làm mọi ca hỏng trông như lỗi server.")
    return gia_tri


TIMEOUT    = doc_env_so("BENCH_HTTP_TIMEOUT", "300", float)
POLL_GIAY  = 2  # nhịp poll cố định; trần thời gian poll = POLL_MAX × POLL_GIAY
POLL_MAX   = doc_env_so("BENCH_POLL_MAX", "150", int)
P95_NGUONG = doc_env_so("BENCH_P95_NGUONG", "60", float)

# Trần "đạt": 6 ca, cho phép trượt đúng 1. Nâng 4 -> 5 (23/08/2026) vì hai ca
# "trượt cố định" cũ đã được viết lại theo hợp đồng hiện tại (T2 thôi đòi
# query_db, T6 thôi đòi "bán lẻ") — giữ 4 nghĩa là chấp nhận HAI ca hỏng thật.
# Exit code giữ nguyên ngữ nghĩa: 0 = đạt ngưỡng, 1 = không.
NGUONG_CA_DAT = 5


def ta_timeout(e: httpx.TimeoutException) -> str:
    """
    Tự dựng thông báo timeout — vì `str(httpx.ReadTimeout)` là chuỗi RỖNG.
    Phiên 23/08/2026 in ra đúng dòng "LỖI GỌI API:" trống trơn, và người đọc
    log không có cách nào biết đó là hết giờ chứ không phải server chết.
    """
    return (f"{type(e).__name__}: quá {TIMEOUT:.0f}s không nhận đủ phản hồi "
            f"(nới qua BENCH_HTTP_TIMEOUT)")


def thoat_neu_401(e: Exception) -> None:
    """
    401 KHÔNG phải "một ca hỏng" — nó hỏng như nhau cho cả sáu ca, nên dừng
    ngay và nói đúng nguyên nhân. Sáu dòng 401 giống hệt nhau trông như model
    chết, còn thật ra là lệch một chuỗi. Tách thành hàm vì cả warm-up lẫn vòng
    6 ca đều phải xử một kiểu.

    Nhận diện bằng STATUS CODE, không soi chuỗi: bản cũ dò '"401" in str(e)'
    mà str(e) của httpx chứa CẢ URL — đường hầm ngrok dạng https://8401-....
    ngrok-free.dev có "401" nằm sẵn trong tên miền, nên server lỗi 500 (hay bất
    kỳ lỗi nào mang URL trong thông báo) bị chẩn thành "token sai" rồi thoát.
    """
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 401:
        sys.exit(
            f"\n  ✗ Brain TỪ CHỐI token đang gửi ({dau_van(API_TOKEN)}).\n\n"
            "    Token có gửi, nhưng KHÔNG khớp cái server đang giữ.\n"
            "    Nguyên nhân thường gặp nhất: ô 4.1 được chạy lại SAU khi\n"
            "    server đã bật. Ô đó sinh token ngẫu nhiên, còn server thì\n"
            "    chụp giá trị tại lúc nó khởi động — chạy lại là hai bên\n"
            "    lệch nhau ngay, mà /health vẫn xanh vì nó không đòi token.\n\n"
            "    Cách xử: chạy ô 4.5 (dọn) → 4.1 → 4.2 → 4.3 → 4.4.\n"
            "    Bản ô 4.1 mới dùng `setdefault` nên chạy lại KHÔNG đổi token nữa."
        )


# ══════════════════════════════════════════════════════════════════════════
def extract_json(text: str):
    for m in re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL):
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    depth, start = 0, -1
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    start = -1
    return None


def strip_think(text: str) -> str:
    last = text.rfind("</think>")
    return text[last + 8:].strip() if last != -1 else text.strip()


# ══════════════════════════════════════════════════════════════════════════
# 6 trường hợp kiểm thử. Mỗi tiêu chí phải trỏ được về hành vi CÓ THẬT trong
# code phục vụ hiện tại (chat.py / tool_planner.py / workflow_schema.py) —
# tiêu chí không trỏ được về đâu là tiêu chí đo một hợp đồng đã chết.
# ══════════════════════════════════════════════════════════════════════════
TESTS = [
    {
        "id":     "T1",
        "name":   "Sinh lệnh tạo workflow",
        # Nhánh TECHNICAL của chat.py: coder sinh JSON, `validate_workflow`
        # (src/core/workflow_schema.py) đòi đúng action="create_workflow",
        # name không rỗng, payload.nodes là mảng khác rỗng — 5 tiêu chí dưới
        # là hình chiếu của validator đó lên phía client.
        "prompt": "Tạo quy trình mỗi 4 tiếng kiểm tra kho, sản phẩm nào còn dưới 15 cái thì báo lên Discord",
        "checks": [
            ("có JSON",            lambda a, j: j is not None),
            ("action đúng",        lambda a, j: j and j.get("action") == "create_workflow"),
            ("có name",            lambda a, j: j and bool(j.get("name"))),
            ("có payload",         lambda a, j: j and isinstance(j.get("payload"), dict)),
            ("payload có nodes",   lambda a, j: j and bool(j.get("payload", {}).get("nodes"))),
        ],
    },
    {
        # T2 viết lại 23/08/2026 — hợp đồng cũ {"action":"query_db","sql":...}
        # ĐÃ BỊ GỠ khỏi đường phục vụ (grep "query_db" trong src/ không còn kết
        # quả nào; docstring benchmark_v3.py cũng ghi nhận điều này). Đường đi
        # THẬT của câu này bây giờ:
        #   1. `plan_tools` (src/core/tool_planner.py) trả [] — luật `report`
        #      CỐ Ý không bắt "tổng tiền bán được"/"doanh thu" trần (xem comment
        #      ngay tại luật `report` trong _RULES);
        #   2. lớp từ khoá của router không khớp (manager.py `_KEYWORD_RULES`)
        #      -> embedding quyết định; các câu mẫu gần nhất nằm ở
        #      routes["DATA_INTERNAL"] ("doanh thu hôm nay là bao nhiêu"...);
        #      không nạp được embedder thì `route_with_score` hạ về GENERAL;
        #   3. nhánh DATA_INTERNAL (chat.py, `elif cat == "DATA_INTERNAL"`) đọc
        #      DB qua SaasAPI. Server Colab KHÔNG có DATABASE_URL nên truy vấn
        #      hỏng: ngữ cảnh thành "(không lấy được dữ liệu từ cơ sở dữ liệu)"
        #      (chat.py, except của nhánh này) hoặc chuỗi lỗi/không-tìm-thấy của
        #      saas_api — model phải NÓI THẲNG là chưa có dữ liệu; chốt chặn
        #      `guard_answer` (chat.py, khối "CHỐT CHẶN NEO SỐ LIỆU") chặn số
        #      bịa ngoài ngữ cảnh.
        "id":     "T2",
        "name":   "Hỏi số liệu bán hàng (hợp đồng SQL đã gỡ)",
        "prompt": "Cho tôi xem tổng tiền bán được trong 14 ngày vừa rồi",
        "checks": [
            # JSON mang "action" chỉ hợp lệ ở nhánh TECHNICAL (chat.py:
            # `resp = json.dumps(obj)` sau validate_workflow). Câu hỏi dữ liệu
            # mà ra JSON lệnh là định tuyến hỏng — hoặc model hồi sinh hợp đồng
            # query_db đã chết.
            ("không trả JSON lệnh",   lambda a, j: not (isinstance(j, dict) and "action" in j)),
            # Không nhánh nào của process_chat còn sinh hay phơi SQL cho người
            # dùng — SELECT...FROM trong câu trả lời = trôi về hợp đồng cũ.
            ("không lộ SQL thô",      lambda a, j: not re.search(r"\bSELECT\b[\s\S]+\bFROM\b", a, re.IGNORECASE)),
            # Đúng hai kết cục hợp lệ của nhánh dữ liệu hiện tại:
            #  - CÓ số liệu kèm đơn vị tiền (khi DB nối được);
            #  - hoặc nói rõ chưa có/không lấy được dữ liệu — các câu tất định
            #    nguồn: "(không lấy được dữ liệu từ cơ sở dữ liệu)" và khối
            #    "CHƯA LẤY ĐƯỢC" (chat.py, nhánh DATA_INTERNAL); "Tôi chưa nối
            #    được"/"chưa lấy được"/"Chưa có dòng bán hàng" của
            #    `_fetch_report_lines` (chat.py) nếu router rẽ REPORT;
            #    "Không tìm thấy sản phẩm"/"Lỗi hệ thống" của saas_api.
            # Trên Colab không có DATABASE_URL nên kết cục thứ hai là kỳ vọng chính.
            #
            # Nhánh tiền tệ nhận cả "đ" đứng một mình — "12.500.000đ" là cách
            # viết của CHÍNH hệ thống mà regex cũ trượt, tức câu trả lời ĐÚNG
            # bị chấm trượt. "đ" phải chốt ranh giới từ (\b) để "5 đơn" không
            # thành tiền ("đ" liền "ơn" là chữ liền chữ, không có ranh giới);
            # riêng "₫" là ký hiệu tiền tệ, KHÔNG phải ký tự \w, nên không được
            # kèm \b — sau nó thường là dấu câu/hết dòng, \b sẽ trượt oan.
            #
            # Nhánh từ chối dùng CỤM ĐỦ NGHĨA thay cho chữ "chưa" trần: "chưa"
            # trần cho câu bịa số kiểu "tổng X đồng, chưa gồm VAT" đi qua như
            # một lời từ chối. Mỗi cụm dưới đây trỏ về một chuỗi tất định có
            # thật liệt kê ở trên.
            ("có số liệu hoặc nói rõ thiếu dữ liệu", lambda a, j: bool(
                re.search(r"\d[\d.,]*\s*(?:₫|(?:đồng|vnd|triệu|nghìn|ngàn|tỷ|đ)\b)",
                          a, re.IGNORECASE)
                or any(k in a.lower() for k in
                       ("chưa có dữ liệu", "chưa lấy được", "chưa nối được",
                        "chưa truy vấn được", "không lấy được dữ liệu",
                        "chưa có dòng bán hàng", "không tìm thấy")))),
        ],
    },
    {
        "id":     "T3",
        "name":   "Workflow n8n có lịch",
        "prompt": "Tạo quy trình gửi tổng kết bán hàng vào 21 giờ mỗi tối qua email",
        "checks": [
            ("có JSON",            lambda a, j: j is not None),
            ("là create_workflow", lambda a, j: j and j.get("action") == "create_workflow"),
            ("có node trigger",    lambda a, j: j and any(
                "trigger" in str(n.get("type", "")).lower()
                for n in j.get("payload", {}).get("nodes", []))),
        ],
    },
    {
        # T4 đo CẢ TẦNG ĐỊNH TUYẾN, không riêng model — nhưng phải nói đúng nó
        # đo bằng GÌ. Sự cố 23/08: chữ "kiểm"/"kho" trong TÊN DÒNG HÀNG của một
        # hoá đơn VẬN TẢI làm luật `inventory_audit` (tool_planner.py) đọc
        # dữ-liệu-trong-hoá-đơn thành ý-định-soi-kho, người dùng nhận "chưa có
        # bảng tổng hợp tồn kho" (_CHUA_CO_NGUON, chat.py). Hoá đơn dưới đây
        # dùng ĐÚNG các tên dòng gây sự cố ("Phí kiểm đếm, lưu kho bãi",
        # "Cước vận chuyển") — đồng bộ với CAU_HOA_DON_T4 của
        # tests/test_tool_planner.py — nên đây mới là ca chống tái diễn thật:
        # bản tool_planner CHƯA vá sẽ rẽ nhầm inventory_audit ngay. (Hoá đơn
        # Coca/Cosy của bản cũ không có chữ kho/tồn nào trong tên hàng, chưa
        # từng kích hoạt được lỗi định tuyến mà comment cũ tuyên bố nó chống.)
        #
        # Bộ số CHỐNG TRIỆT TIÊU. Bản cũ: 550.000×1,08 = 540.000×1,10 = 594.000
        # — sai số dòng hàng bù vừa khít chênh thuế suất 8%/10%, nên
        # validate_invoice_total tính với default 10% trả "hợp lệ, chênh 0" và
        # ca này không đo được gì. Bộ mới: các dòng hàng ĐÚNG và khớp subtotal
        # khai (500.000×2 + 800.000×3 = 3.400.000); lỗi nằm ở TỔNG khai
        # 3.960.000, và nó lộ dưới CẢ hai thuế suất (tự kiểm số học):
        #   3.400.000 × 1,08 = 3.672.000 ≠ 3.960.000 (chênh 288.000)
        #   3.400.000 × 1,10 = 3.740.000 ≠ 3.960.000 (chênh 220.000)
        "id":     "T4",
        "name":   "Phát hiện sai số hóa đơn",
        "prompt": (
            'Qwen2-VL đọc được hóa đơn sau, hãy kiểm tra tính hợp lệ: '
            '{"items": [{"name": "Phí kiểm đếm, lưu kho bãi", "price": 500000, '
            '"qty": 2}, {"name": "Cước vận chuyển HN-HP", "price": 800000, '
            '"qty": 3}], "subtotal": 3400000, "vat_rate": 8, '
            '"total_amount": 3960000}'
        ),
        "checks": [
            ("phát hiện sai",      lambda a, j: any(k in a.lower() for k in
                                    ["sai", "lệch", "không khớp", "không đúng", "chênh"])),
            # Số "đúng" theo bộ số mới: tổng đúng 3.672.000 (thuế 8% như khai),
            # tiền thuế đúng 272.000, hoặc mức chênh 288.000. Không chuỗi nào
            # trong ba số này là chuỗi con của các số ĐÃ KHAI trong hoá đơn
            # (500000/800000/3400000/3960000) — chỉ chép lại đề thì không qua.
            ("nêu số đúng",        lambda a, j: any(
                s in a.replace(".", "").replace(",", "")
                for s in ("3672000", "272000", "288000"))),
            ("không tự sửa",       lambda a, j: not (j and j.get("status") == "completed")),
        ],
    },
    {
        "id":     "T5",
        "name":   "Tính thuế — chỉ văn xuôi",
        "prompt": "Đơn hàng 3 triệu 500 nghìn, thuế GTGT 8% thì phải nộp bao nhiêu tiền thuế?",
        "checks": [
            ("KHÔNG có JSON",      lambda a, j: j is None),
            ("số tiền đúng",       lambda a, j: "280" in a.replace(".", "").replace(",", "")),
        ],
    },
    {
        # T6 viết lại 23/08/2026 — tiêu chí cũ "có nhắc bán lẻ" là di sản thời
        # bán lẻ, nghiệp vụ đã logistics-first. Đường đi THẬT của câu này:
        # "Giải thích cho..." khớp luật từ khoá EXPLAIN (manager.py,
        # `_KEYWORD_RULES`, đặt đầu bảng) -> nhánh EXPLAIN trong chat.py; lịch
        # sử không có khối kết quả engine nào (`_find_explainable` trả None)
        # nên server trả CÂU TẤT ĐỊNH: "Tôi chưa có kết quả nào gần đây để giải
        # thích. Bạn hỏi lại ngay sau khi tôi đưa ra báo giá, gợi ý hãng xe
        # hoặc báo cáo nhé..." (chat.py, nhánh `explain_ctx is None`). Đó là
        # CHUYỂN HƯỚNG ĐÚNG — tiêu chí dưới đây phải cho câu đó QUA.
        "id":     "T6",
        "name":   "Chuyển hướng câu ngoài lĩnh vực",
        "prompt": "Giải thích cho tôi thuật toán sắp xếp nổi bọt hoạt động thế nào",
        "checks": [
            ("ngắn gọn",           lambda a, j: len(a) < 600),
            # Từ khoá nghiệp vụ HIỆN TẠI (logistics-first). "báo giá"/"hãng xe"
            # /"báo cáo" có mặt trong chính câu tất định của nhánh EXPLAIN
            # (chat.py) nên câu đó qua chắc chắn; các từ còn lại đón trường hợp
            # router rẽ GENERAL và model tự chuyển hướng về nghiệp vụ.
            # KHÔNG có từ ngắn "kho"/"cước" trong danh sách: dò kiểu chuỗi-con
            # thì "kho" nằm sẵn trong "khoảng"/"khoản"/"khoa" — một câu GIẢI
            # THÍCH thuật toán (tức sai hoàn toàn mục đích chuyển hướng) chỉ cần
            # chữ "khoảng" là đủ điểm. Các cụm dài còn lại đã phủ cả câu tất
            # định lẫn câu model tự chuyển hướng.
            ("chuyển hướng về nghiệp vụ", lambda a, j: any(k in a.lower() for k in
                                    ["logistics", "vận tải", "vận chuyển", "báo giá",
                                     "hãng xe", "nhà xe", "báo cáo", "kinh doanh"])),
            ("không viết code dài",lambda a, j: a.count("def ") + a.count("for ") < 3),
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════
async def ask(client: httpx.AsyncClient, prompt: str) -> tuple[str, float]:
    t0 = time.time()
    r = await client.post(
        f"{BRAIN_URL}/chat",
        json={"message": prompt, "user_id": 1, "store_id": 1},
    )
    r.raise_for_status()
    body = r.json()

    # Trả lời ngay
    if "result" in body and body.get("status") == "completed":
        return body["result"].get("answer", ""), time.time() - t0

    # Trả về task_id — poll
    task_id = body.get("task_id")
    if not task_id:
        return json.dumps(body, ensure_ascii=False), time.time() - t0

    for _ in range(POLL_MAX):
        await asyncio.sleep(POLL_GIAY)
        rr = await client.get(f"{BRAIN_URL}/api/v1/task/{task_id}")
        bb = rr.json()
        if bb.get("status") == "completed":
            return bb.get("result", {}).get("answer", ""), time.time() - t0
        if bb.get("status") == "failed":
            return f"[TASK FAILED] {bb}", time.time() - t0

    # Ghi rõ đã chờ bao lâu — "[TIMEOUT]" trần trụi của bản cũ không cho người
    # đọc log biết trần nằm ở đâu để mà nới.
    return (f"[TIMEOUT] đã poll {POLL_MAX}×{POLL_GIAY}s = {POLL_MAX * POLL_GIAY}s "
            f"(nới qua BENCH_POLL_MAX)"), time.time() - t0


async def main():
    print(f"\n{'='*66}")
    print("  BỘ KIỂM THỬ TÍCH HỢP — ANSER Brain (đầu-cuối qua HTTP)")
    print(f"{'='*66}")
    print(f"  Endpoint : {BRAIN_URL}")
    print(f"  Số ca    : {len(TESTS)}")
    print(f"  Trần     : HTTP {TIMEOUT:.0f}s · poll {POLL_MAX}×{POLL_GIAY}s "
          f"· p95 ≤ {P95_NGUONG:.0f}s")
    print(f"{'='*66}\n")

    passed_cases, results = 0, []

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
        # Health check
        try:
            h = await client.get(f"{BRAIN_URL}/health")
            hs = h.json()
            print(f"  Health: engine_ready={hs.get('engine_ready')} "
                  f"degraded={hs.get('degraded')} "
                  f"auth_enabled={hs.get('auth_enabled')}")
            print(f"  Token gửi kèm: {dau_van(API_TOKEN) if API_TOKEN else 'KHÔNG'}\n")

            # Chặn ở đây thay vì để sáu ca cùng trả 401. Sáu dòng "LỖI GỌI API"
            # giống hệt nhau trông như model hỏng, còn thật ra là thiếu một biến
            # môi trường — hai chuyện cần đọc khác nhau.
            if hs.get("auth_enabled") and not API_TOKEN:
                sys.exit(
                    "\n  ✗ Brain ĐANG kiểm token mà script không có token để gửi.\n"
                    "    Mọi ca sẽ trả 401, và đó KHÔNG phải lỗi model.\n\n"
                    "    Đặt một trong hai biến rồi chạy lại:\n"
                    "      BRAIN_API_TOKEN=...   (tên phía client, giống Body)\n"
                    "      API_AUTH_TOKEN=...    (tên phía server)\n\n"
                    "    Trên Colab, ô 4.1 đã đặt `API_AUTH_TOKEN` vào os.environ —\n"
                    "    `!lệnh` kế thừa biến đó, nên chạy lại ô 4.1 rồi ô 4.4."
                )

            # engine_ready=False ngay sau khi bật server là BÌNH THƯỜNG: model nạp
            # LƯỜI ở request đầu tiên (`ensure_text_runtime`), `lifespan` không nạp
            # gì. Warm-up ngay dưới sinh ra để gánh đúng phần nạp đó.
            if hs.get("engine_ready") is False:
                print("  ⓘ engine_ready=False — model chưa nạp. Bình thường ở đây:\n"
                      "    nó nạp ở request ĐẦU TIÊN — warm-up bên dưới sẽ gánh.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ⚠ Không gọi được /health: {str(e)[:80] or type(e).__name__}\n")

        # ── Warm-up ─────────────────────────────────────────────────────────
        # Request đầu tiên gánh 1–3 phút nạp model (nạp lười). Phiên 23/08/2026
        # để T1 gánh phần đó: T1 chết vì timeout còn bảng kết quả thì đổ tội
        # cho model. Nên đốt một câu rẻ qua ĐÚNG luồng POST /chat + poll, in
        # thời gian RIÊNG — không tính vào điểm hay độ trễ của 6 ca.
        # ask() KHÔNG ném exception cho hai kết cục hỏng — nó trả CHUỖI bắt đầu
        # bằng "[TIMEOUT]" hoặc "[TASK FAILED]". Bản cũ vứt giá trị trả về nên
        # OOM lúc nạp model vẫn in "Warm-up: 6.2s" như thành công, rồi 6 ca chết
        # không dấu vết. Phải đọc chuỗi trả về và nói thẳng khi nó là lỗi.
        try:
            warm_ans, warm_dur = await ask(client, "Xin chào")
            if warm_ans.startswith(("[TIMEOUT]", "[TASK FAILED]")):
                print(f"  ⚠ Warm-up KHÔNG thành công sau {warm_dur:.1f}s:\n"
                      f"    {warm_ans[:160]}\n"
                      "    6 ca sắp chạy trên engine chưa chứng minh sống — nếu\n"
                      "    cả loạt cùng hỏng, hãy nghi engine/model trước tiên.\n")
            else:
                print(f"  Warm-up — lần đầu (có nạp model): {warm_dur:.1f}s\n")
        except httpx.TimeoutException as e:
            print(f"  ⚠ Warm-up chưa xong — {ta_timeout(e)}.\n"
                  "    Ca T1 sẽ phải gánh nốt phần nạp model còn dở.\n")
        except Exception as e:
            thoat_neu_401(e)
            print(f"  ⚠ Warm-up lỗi: {str(e)[:80] or type(e).__name__} — vẫn chạy tiếp 6 ca.\n")

        for t in TESTS:
            print(f"  ── {t['id']}  {t['name']}")
            print(f"     Hỏi: {t['prompt'][:70]}...")
            try:
                raw, dur = await ask(client, t["prompt"])
            except httpx.TimeoutException as e:
                # Bắt RIÊNG vì str() của nó rỗng — rơi xuống nhánh dưới là in
                # ra "LỖI GỌI API:" trống trơn (đúng vết thương phiên 23/08).
                print(f"     ✗ {ta_timeout(e)}\n")
                results.append((t["id"], t["name"], 0, len(t["checks"]), 0.0))
                continue
            except Exception as e:
                thoat_neu_401(e)
                print(f"     ✗ LỖI GỌI API: {str(e)[:80] or type(e).__name__}\n")
                results.append((t["id"], t["name"], 0, len(t["checks"]), 0.0))
                continue

            answer = strip_think(raw)
            obj    = extract_json(answer)

            n_ok = 0
            for label, fn in t["checks"]:
                try:
                    ok = bool(fn(answer, obj))
                except Exception:
                    ok = False
                n_ok += ok
                print(f"     {'✓' if ok else '✗'} {label}")

            all_ok = n_ok == len(t["checks"])
            passed_cases += all_ok
            results.append((t["id"], t["name"], n_ok, len(t["checks"]), dur))

            print(f"     → {n_ok}/{len(t['checks'])} tiêu chí  ·  {dur:.1f}s")
            print(f"     Đáp: {answer[:110]}...\n")

    # ── Tổng kết ────────────────────────────────────────────────────────
    print(f"{'='*66}")
    print("  KẾT QUẢ")
    print(f"{'='*66}\n")

    total_checks = sum(r[3] for r in results)
    total_ok     = sum(r[2] for r in results)

    for tid, name, ok, tot, dur in results:
        mark = "✓" if ok == tot else ("~" if ok else "✗")
        print(f"  {mark}  {tid}  {name:32s} {ok}/{tot}   {dur:5.1f}s")

    print(f"\n  Ca đạt hoàn toàn : {passed_cases}/{len(TESTS)}")
    print(f"  Tiêu chí đạt     : {total_ok}/{total_checks} ({total_ok/total_checks*100:.0f}%)")

    # Số đo lấy SAU warm-up — warm-up không nằm trong `results` nên không kéo
    # trung bình/p95 lên vì phần nạp model lười.
    durs = [r[4] for r in results if r[4] > 0]
    if durs:
        # Với n nhỏ thì p95 phải ≈ max: làm-tròn-LÊN ceil(n×0,95)-1. Công thức
        # cũ int(n×0,95)-1 làm tròn XUỐNG — n=6 lấy phần tử thứ 5/6 (~p79),
        # tức ca CHẬM NHẤT vô hình trước ngưỡng. In kèm max ("chậm nhất") để
        # không con số nào bị nhãn phân vị che mất.
        xep = sorted(durs)
        p95 = xep[min(len(xep) - 1, math.ceil(len(xep) * 0.95) - 1)]
        print(f"  Độ trễ trung bình: {sum(durs)/len(durs):.1f}s  (đo sau warm-up)")
        print(f"  Độ trễ chậm nhất : {xep[-1]:.1f}s")
        print(f"  Độ trễ phân vị 95: {p95:.1f}s  "
              f"{'✓' if p95 <= P95_NGUONG else f'⚠ vượt ngưỡng {P95_NGUONG:.0f}s (BENCH_P95_NGUONG)'}")

    print()
    if passed_cases == len(TESTS):
        print("  ✅ ĐẠT TOÀN BỘ — sẵn sàng triển khai")
    elif passed_cases >= NGUONG_CA_DAT:
        print(f"  ⚠ Đạt {passed_cases}/{len(TESTS)} — dùng được, còn điểm cần cải thiện")
    else:
        print(f"  ✗ Chỉ đạt {passed_cases}/{len(TESTS)} (ngưỡng {NGUONG_CA_DAT}) "
              "— cần xem lại định tuyến, prompt hoặc dữ liệu")
    print(f"{'='*66}\n")

    return 0 if passed_cases >= NGUONG_CA_DAT else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
