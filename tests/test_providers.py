"""
tests/test_providers.py — chỗ cắm model cho benchmark.

VÌ SAO ĐÁNG VIẾT
----------------
Lớp này không tính toán gì, nó chỉ dựng tham số rồi gọi đi. Nhưng nó nằm đúng
chỗ mà một cái sai không báo lỗi: sai ở đây thì benchmark vẫn chạy trọn 40 phút,
vẫn in ra một bảng đầy đủ, và bảng đó sai theo kiểu không nhìn ra được.

Ba cái sai loại đó, mỗi cái một test bên dưới:

  1. Chuyển `temperature` sang Anthropic — Claude Opus 5 đã GỠ tham số này, gửi
     lên là 400. Cả phiên đo chết ngay câu đầu, và thông báo lỗi không nhắc gì
     tới nhiệt độ.
  2. Không đổi tên lý do dừng — `max_tokens` của Anthropic không phải `"length"`
     của vLLM. Tầng chấm điểm chỉ so đúng chữ `"length"`, nên mọi câu CẮT CỤT sẽ
     bị tính thành JSON hỏng, và báo cáo nói "model bịa số" đúng vào lúc model
     mới chỉ chưa nói hết câu.
  3. Khai `rang_buoc` sai — `compare_runs.py` dựa vào trường này để cảnh báo hai
     lần chạy bị ép JSON bằng hai cơ chế khác nhau. Khai sai thì cảnh báo im, và
     chênh lệch do cơ chế bị đọc thành chênh lệch năng lực.

Các test ở đây KHÔNG cần GPU, KHÔNG cần mạng, KHÔNG cần SDK — vì phần dựng tham
số đã tách khỏi phần gọi đi. Đó là lý do nó tách.
"""

from __future__ import annotations

import json

import pytest

from offline_training.providers import (
    KHOA_CAU_TRUC_KHONG_DO,
    KHOA_KHONG_DO,
    Anthropic,
    OpenAITuongThich,
    VLLMTrongTienTrinh,
    doi_ly_do_dung,
    dong_luoc_do,
    dung_provider,
    payload_openai,
    tach_spec,
    tham_so_anthropic,
)

CHAT = [
    {"role": "system", "content": "Bạn là trợ lý."},
    {"role": "user", "content": "Báo giá Hà Nội đi Hải Phòng."},
]
LUOC_DO = {
    "type": "object",
    "properties": {"origin": {"type": "string"}},
    "required": ["origin"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Phân giải --model
# ---------------------------------------------------------------------------

def test_khong_co_tien_to_thi_van_la_vllm_trong_tien_trinh():
    """
    Mọi lệnh cũ trong notebook và RUNBOOK truyền thẳng đường dẫn hoặc HF id.
    Đổi nghĩa của dạng không-tiền-tố là làm hỏng mọi ô Colab đang chạy được.
    """
    assert tach_spec("Qwen/Qwen3-8B") == ("vllm", "", "Qwen/Qwen3-8B")
    assert tach_spec("/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-awq") == (
        "vllm", "", "/content/drive/MyDrive/ANSER_AI_Logistics/anser-v3-awq"
    )


def test_dang_openai_tach_base_url_va_ten_model():
    assert tach_spec("openai:http://127.0.0.1:8001/v1#anser-v3") == (
        "openai", "http://127.0.0.1:8001/v1", "anser-v3"
    )


def test_dang_openai_tach_o_dau_thang_CUOI_CUNG():
    """
    URL có thể chứa `#`. Tách ở dấu thăng đầu tiên là cắt nhầm URL và báo một
    tên model vô nghĩa — mà lỗi chỉ lộ ra lúc endpoint trả 404.
    """
    assert tach_spec("openai:http://host/v1#x#anser-v3") == (
        "openai", "http://host/v1#x", "anser-v3"
    )


def test_dang_anthropic_lay_ten_model():
    assert tach_spec("anthropic:claude-opus-5") == ("anthropic", "", "claude-opus-5")


@pytest.mark.parametrize("spec", [
    "openai:http://127.0.0.1:8001/v1",   # thiếu #model
    "openai:#anser-v3",                  # base_url rỗng
    "openai:http://host/v1#",            # model rỗng
    "anthropic:",                        # thiếu tên model
])
def test_spec_hong_bao_ngay_chu_khong_chay_roi_moi_hong(spec):
    """
    Dừng ở khâu phân giải, trước khi nạp model. Một spec hỏng mà lọt qua đây sẽ
    nổ sau khi đã nạp 6GB weights — tức là sau vài phút, vì một lỗi đánh máy.
    """
    with pytest.raises(SystemExit):
        tach_spec(spec)


# ---------------------------------------------------------------------------
# Anthropic — dựng tham số
# ---------------------------------------------------------------------------

def test_KHONG_gui_temperature_sang_anthropic():
    """
    Cái sai số 1 trong docstring đầu file. Benchmark gọi mọi nhánh với
    `temperature=0.0`; chuyển thẳng sang đây là 400 ngay câu đầu.
    """
    kw = tham_so_anthropic("claude-opus-5", CHAT, None, 256)
    assert "temperature" not in kw
    assert "top_p" not in kw
    assert "top_k" not in kw
    assert "budget_tokens" not in kw


def test_tin_nhan_he_thong_tach_khoi_messages():
    """
    Anthropic không nhận `role: "system"` trong `messages` như khuôn OpenAI —
    nó phải nằm ở tham số `system` riêng. Để nguyên trong `messages` là 400.
    """
    kw = tham_so_anthropic("claude-opus-5", CHAT, None, 256)
    assert kw["system"] == "Bạn là trợ lý."
    assert [m["role"] for m in kw["messages"]] == ["user"]


def test_nhieu_tin_nhan_he_thong_thi_noi_lai():
    chat = [
        {"role": "system", "content": "A"},
        {"role": "system", "content": "B"},
        {"role": "user", "content": "hỏi"},
    ]
    assert tham_so_anthropic("claude-opus-5", chat, None, 256)["system"] == "A\n\nB"


def test_luoc_do_di_vao_output_config_format():
    """
    `output_config={"format": ...}` — KHÔNG phải `output_format`, tham số đó đã
    bỏ. Sai tên thì lược đồ bị lờ đi trong im lặng: model vẫn trả lời, chỉ là
    không theo lược đồ, và điểm rơi xuống trông y hệt một model dở.
    """
    kw = tham_so_anthropic("claude-opus-5", CHAT, LUOC_DO, 256)
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": LUOC_DO}
    assert "output_format" not in kw


def test_khong_co_luoc_do_thi_khong_dung_output_config():
    """Nhánh narration chạy văn xuôi, không ràng buộc gì."""
    assert "output_config" not in tham_so_anthropic("claude-opus-5", CHAT, None, 1100)


def test_effort_nam_chung_output_config_voi_format():
    """
    Cả hai cùng trong `output_config`. Đặt `effort` ra ngoài là tham số lạ ở cấp
    cao nhất.
    """
    kw = tham_so_anthropic("claude-opus-5", CHAT, LUOC_DO, 256, effort="low")
    assert kw["output_config"]["effort"] == "low"
    assert "format" in kw["output_config"]


# ---------------------------------------------------------------------------
# OpenAI-compatible — dựng payload
# ---------------------------------------------------------------------------

def test_payload_openai_giu_temperature():
    """
    Ngược với Anthropic: endpoint vLLM vẫn nhận `temperature`, và benchmark đo ở
    0.0 để kết quả lặp lại được. Bỏ đi là đo một thứ khác.
    """
    p = payload_openai("anser-v3", CHAT, LUOC_DO, 256, 0.0)
    assert p["temperature"] == 0.0
    assert p["guided_json"] == LUOC_DO
    assert p["messages"] == CHAT      # giữ nguyên cả tin nhắn system


def test_payload_openai_khong_luoc_do_thi_khong_guided_json():
    assert "guided_json" not in payload_openai("anser-v3", CHAT, None, 1100, 0.2)


# ---------------------------------------------------------------------------
# Lý do dừng
# ---------------------------------------------------------------------------

def test_cham_tran_token_doi_thanh_length():
    """
    Cái sai số 2. `score_n8n`/`score_narration` chỉ so đúng chữ `"length"`; sai
    một chữ là CẮT CỤT biến mất khỏi báo cáo và hiện lại dưới dạng "bịa số".
    """
    assert doi_ly_do_dung("max_tokens") == "length"


def test_tu_choi_GIU_NGUYEN_ten_khong_gop_vao_stop():
    """
    Model từ chối trả lời là chuyện khác hẳn với model trả lời sai. Gộp vào
    `stop` thì câu đó chỉ còn là một JSON không đọc được, không ai biết vì sao.
    """
    assert doi_ly_do_dung("refusal") == "refusal"


@pytest.mark.parametrize("ly_do", ["end_turn", "stop_sequence", "tool_use", "pause_turn"])
def test_cac_ly_do_ket_thuc_binh_thuong_ve_stop(ly_do):
    assert doi_ly_do_dung(ly_do) == "stop"


def test_ly_do_la_hoac_None_ve_stop_chu_khong_no():
    """
    API thêm lý do dừng mới là chuyện xảy ra. Ném ngoại lệ ở đây là giết cả
    phiên đo vì một chuỗi lạ; coi như kết thúc bình thường thì cùng lắm mất một
    nhãn chẩn đoán.
    """
    assert doi_ly_do_dung(None) == "stop"
    assert doi_ly_do_dung("ly_do_moi_toanh") == "stop"


# ---------------------------------------------------------------------------
# Hợp đồng chung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lop, mong_doi", [
    (VLLMTrongTienTrinh, "guided_json"),
    (OpenAITuongThich, "guided_json"),
    (Anthropic, "structured_output"),
])
def test_moi_ban_dung_khai_dung_rang_buoc(lop, mong_doi):
    """
    Cái sai số 3. `compare_runs.py` so hai trường này để cảnh báo; khai sai thì
    cảnh báo im lặng và người đọc quy hết chênh lệch cho năng lực model.
    """
    assert lop.rang_buoc == mong_doi


@pytest.mark.parametrize("lop", [VLLMTrongTienTrinh, OpenAITuongThich, Anthropic])
def test_moi_ban_dung_deu_co_sinh_va_cung_chu_ky(lop):
    """
    `sinh` phải trả 2-tuple `(văn_bản, lý_do_dừng)`. Không kiểm được kiểu trả về
    mà không gọi thật, nên ít nhất chốt chữ ký: bốn tham số, đúng tên, vì
    `benchmark_v3` gọi bằng keyword (`max_tokens=`, `temperature=`).
    """
    import inspect

    tham_so = list(inspect.signature(lop.sinh).parameters)
    assert tham_so == ["self", "chats", "json_schema", "max_tokens", "temperature"]


def test_ban_dung_anthropic_nhan_temperature_roi_bo_di():
    """
    Chữ ký phải giống ba bản để `benchmark_v3` gọi chung một kiểu, nhưng thân
    hàm KHÔNG được chuyển nó đi tiếp. `del temperature` trong thân là chủ đích,
    không phải code thừa — test này giữ nó khỏi bị dọn nhầm.
    """
    import inspect

    than = inspect.getsource(Anthropic.sinh)
    assert "del temperature" in than
    assert "temperature=temperature" not in than


try:  # pragma: no cover - phụ thuộc môi trường
    import anthropic  # noqa: F401
    CO_SDK_ANTHROPIC = True
except ImportError:
    CO_SDK_ANTHROPIC = False


@pytest.mark.skipif(CO_SDK_ANTHROPIC, reason="chỉ kiểm thông báo lúc THIẾU SDK")
def test_thieu_sdk_thi_noi_ro_cach_cai_chu_khong_nem_ImportError():
    """
    CI không cài `anthropic` (nặng và không cần cho phần còn lại). Người chạy
    phiên đo gặp lỗi này lúc 11 giờ đêm thì cần đọc được ngay phải làm gì.
    """
    with pytest.raises(SystemExit, match="pip install anthropic"):
        dung_provider("anthropic:claude-opus-5")


# ---------------------------------------------------------------------------
# dong_luoc_do — hai lỗi 400 THẬT gặp ngày 23/08/2026
# ---------------------------------------------------------------------------
#
# Anthropic từ chối lược đồ theo hai kiểu khác nhau, và hai kiểu đó phải được
# xử khác nhau:
#
#   "For 'object' type, 'additionalProperties' must be explicitly set to false"
#   "For 'number' type, property 'minimum' is not supported"
#
# Cái thứ nhất KHÔNG phải lúc nào cũng vá được — object tự do mà đóng lại là cấm
# sạch nội dung. Cái thứ hai vá được vô hại — nó ràng buộc giá trị, không ràng
# buộc hình dạng, mà tầng chấm điểm vốn đã tự kiểm lại giá trị bằng pydantic.


def test_object_co_truong_thi_dong_duoc():
    """Đóng ở đây chỉ cấm trường KHÔNG khai — trường đã khai vẫn qua."""
    dong, mo, _ = dong_luoc_do({
        "type": "object",
        "properties": {"ten": {"type": "string"}},
    })
    assert mo == []
    assert dong["additionalProperties"] is False


def test_object_TU_DO_thi_KHONG_dong_duoc():
    """
    `properties` rỗng nghĩa là mọi khoá đều hợp lệ. Đóng nó là cấm sạch — và
    bảng kết quả sẽ đọc thành "model kém" trong khi hỏng là khung đo.
    """
    dong, mo, _ = dong_luoc_do({"type": "object", "properties": {}})
    assert dong is None
    assert mo == ["$"]


def test_bao_dung_DUONG_DAN_cua_object_tu_do():
    """
    Phải gọi đích danh chỗ hỏng. "Lược đồ không đóng được" mà không nói chỗ nào
    thì người đọc lúc 11 giờ đêm không có gì để lần.
    """
    dong, mo, _ = dong_luoc_do({
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"parameters": {"type": "object", "properties": {}}},
                },
            },
        },
    })
    assert dong is None
    assert mo == ["$.properties.nodes.items.properties.parameters"]


def test_dong_ca_trong_defs_va_items():
    dong, mo, _ = dong_luoc_do({
        "type": "object",
        "properties": {"ds": {"type": "array", "items": {"$ref": "#/$defs/X"}}},
        "$defs": {"X": {"type": "object", "properties": {"a": {"type": "string"}}}},
    })
    assert mo == []
    assert dong["additionalProperties"] is False
    assert dong["$defs"]["X"]["additionalProperties"] is False


def test_giu_nguyen_additionalProperties_da_khai():
    """Người viết lược đồ đã quyết định rồi thì đừng quyết hộ."""
    dong, mo, _ = dong_luoc_do({
        "type": "object", "properties": {}, "additionalProperties": True,
    })
    assert mo == []
    assert dong["additionalProperties"] is True


def test_type_la_danh_sach_van_nhan_ra_object():
    """`{"type": ["object", "null"]}` là object — Pydantic sinh ra dạng này."""
    dong, mo, _ = dong_luoc_do({"type": ["object", "null"], "properties": {}})
    assert dong is None and mo == ["$"]


def test_loc_khoa_rang_buoc_gia_tri():
    """
    `exclusiveMinimum` trên `carrier_cost` chính là khoá làm hỏng lần chạy đầu.
    Bỏ nó không làm sai phép đo: `_kiem_tham_so` vẫn kiểm lại bằng pydantic thật.
    """
    dong, mo, da_loc = dong_luoc_do({
        "type": "object",
        "properties": {"gia": {"type": "number", "exclusiveMinimum": 0}},
    })
    assert mo == []
    assert "exclusiveMinimum" not in dong["properties"]["gia"]
    assert da_loc == {"exclusiveMinimum"}
    assert dong["properties"]["gia"]["type"] == "number"   # phần hình dạng còn nguyên


def test_KHONG_loc_ten_truong_trung_ten_khoa():
    """
    Một trường tên `pattern` là TÊN NGƯỜI DÙNG ĐẶT, không phải khoá kiểm tra.
    Lọc theo tên mà không nhìn vị trí là xoá mất trường thật của người ta.
    """
    dong, _, da_loc = dong_luoc_do({
        "type": "object",
        "properties": {"pattern": {"type": "string"}, "format": {"type": "string"}},
    })
    assert set(dong["properties"]) == {"pattern", "format"}
    assert da_loc == set()


def test_giu_nguyen_phan_cau_truc():
    """`enum`, `required`, `anyOf`, `$ref` là hình dạng — lọc là hỏng phép đo."""
    goc = {
        "type": "object",
        "required": ["tool"],
        "properties": {
            "tool": {"type": "string", "enum": ["report"]},
            "x": {"anyOf": [{"type": "number", "minimum": 1}, {"type": "null"}]},
        },
    }
    dong, mo, da_loc = dong_luoc_do(goc)
    assert mo == []
    assert dong["required"] == ["tool"]
    assert dong["properties"]["tool"]["enum"] == ["report"]
    assert [n.get("type") for n in dong["properties"]["x"]["anyOf"]] == ["number", "null"]
    assert da_loc == {"minimum"}


def test_khong_dot_bien_luoc_do_goc():
    """
    Lược đồ gốc còn được đưa vào vLLM ở lần chạy khác trong cùng tiến trình.
    Sửa tại chỗ là lặng lẽ đổi ràng buộc của bản dựng kia.
    """
    goc = {"type": "object", "properties": {"a": {"type": "number", "minimum": 0}}}
    truoc = json.dumps(goc, sort_keys=True)
    dong_luoc_do(goc)
    assert json.dumps(goc, sort_keys=True) == truoc


def test_moi_khoa_trong_KHOA_KHONG_DO_deu_bi_loc():
    for khoa in KHOA_KHONG_DO:
        _, _, da_loc = dong_luoc_do({"type": "object", "properties": {"a": {"type": "string"}},
                                     khoa: 1})
        assert khoa in da_loc, khoa


def test_luoc_do_workflow_n8n_THAT_khong_dong_duoc():
    """
    Bài kiểm hồi quy cho phát hiện 23/08/2026, chạy trên lược đồ THẬT.

    Hai chỗ tự do là `parameters` (cấu hình từng node) và `connections` (khoá là
    TÊN node). Nếu sau này ai đó đóng chúng lại ở `workflow_schema.py`, test này
    đỏ — và đó là tín hiệu đúng: đóng chúng lại là cấm workflow có tham số.
    """
    from src.core import workflow_schema

    dong, mo, _ = dong_luoc_do(workflow_schema.build_workflow_schema())
    assert dong is None, "lược đồ n8n đã đóng hết — kiểm lại workflow_schema.py"
    assert any(d.endswith(".parameters") for d in mo), mo
    assert any(d.endswith(".connections") for d in mo), mo


@pytest.mark.parametrize("khoa", sorted(KHOA_CAU_TRUC_KHONG_DO))
def test_khoa_cau_truc_thi_LUI_chu_khong_loc(khoa):
    """
    Khác hẳn nhóm ràng buộc giá trị: những khoá này quyết định model được
    phép sinh ra HÌNH DẠNG nào. `build_decision_schema` dùng `oneOf` + `not` để
    cấm model vừa gọi tool vừa tuyên bố đáp án — lọc đi là cho phép đúng cái
    lược đồ sinh ra để chặn, rồi vẫn chấm điểm như thể đã chặn.
    """
    dong, mo, da_loc = dong_luoc_do({
        "type": "object", "properties": {"a": {"type": "string"}}, khoa: [{"required": ["a"]}],
    })
    assert dong is None
    assert any(khoa in ly_do for ly_do in mo), mo
    assert khoa not in da_loc


def test_anyOf_KHONG_bi_coi_la_khong_do_duoc():
    """Lỗi 400 gọi đích danh `oneOf`, không gọi `anyOf` — đừng cấm thêm."""
    dong, mo, _ = dong_luoc_do({
        "type": "object",
        "properties": {"x": {"anyOf": [{"type": "number"}, {"type": "null"}]}},
    })
    assert mo == [] and dong is not None


def test_luoc_do_quyet_dinh_agentic_THAT_khong_dien_dat_duoc():
    """
    Hồi quy cho lỗi 400 thứ ba (23/08/2026): `Schema type 'oneOf' is not supported`.
    """
    from src.agents.agentic import build_decision_schema

    dong, mo, _ = dong_luoc_do(build_decision_schema(["report"]))
    assert dong is None
    assert any("oneOf" in ly_do for ly_do in mo), mo
