"""
tests/test_logistics_branch.py — nhánh LOGISTICS: router, trích xuất, webhook.

Chạy ở ENV=LOCAL (không cần GPU): router lớp từ khoá + mock engine.
"""

import json

import pytest

from src.agents.manager import SemanticRouter
from src.core.schemas import QUOTE_REQUIRED_FIELDS, QuoteExtraction

# ===========================================================================
# Router — câu logistics phải vào đúng nhánh ngay từ lớp từ khoá
# ===========================================================================

ROUTER = SemanticRouter()   # ENV dev không có torch -> chạy chế độ từ khoá, đủ cho test


@pytest.mark.parametrize("query", [
    "báo giá xe 5 tấn từ Hữu Nghị đi Hải Phòng",
    "cho anh giá cước chuyến hàng lạnh đi Bắc Giang",
    "cần một đầu kéo đi Hải Phòng thứ 3 tuần sau",
    "khách hỏi thuê xe 3 tấn đi Bắc Ninh ngày mai",
    "giá cước tuyến Hà Nội - Hải Phòng giờ bao nhiêu",
])
def test_router_keyword_hits_logistics(query):
    out = ROUTER.route_with_score(query)
    assert out["route"] == "LOGISTICS", f"{query!r} -> {out}"
    assert out["method"] == "keyword"


@pytest.mark.parametrize("query,expected", [
    # "tạo quy trình" vẫn phải vào TECHNICAL dù nói về báo cáo
    ("tạo quy trình tự động gửi báo cáo doanh số mỗi tối", "TECHNICAL"),
    # thuế vẫn vào RETRIEVAL
    ("thuế GTGT 8% tính thế nào", "RETRIEVAL"),
])
def test_logistics_rule_does_not_steal_other_routes(query, expected):
    assert ROUTER.route_with_score(query)["route"] == expected


# ===========================================================================
# Schema trích xuất
# ===========================================================================

def test_quote_extraction_schema_all_optional():
    """Guided_json cần mọi field nullable — model không bị ép đoán trường thiếu."""
    q = QuoteExtraction()   # không trường nào -> vẫn hợp lệ
    assert q.origin is None

    schema = QuoteExtraction.model_json_schema()
    assert set(QUOTE_REQUIRED_FIELDS) <= set(schema["properties"])


def test_quote_required_fields_have_vietnamese_labels():
    """Nhãn tiếng Việt dùng để HỎI LẠI người dùng — phải có đủ."""
    for field, label in QUOTE_REQUIRED_FIELDS.items():
        assert label and not label.isascii(), f"{field} thiếu nhãn tiếng Việt"


# ===========================================================================
# _handle_logistics_quote — các nhánh phản hồi
# ===========================================================================

@pytest.mark.asyncio
async def test_missing_fields_asks_back(monkeypatch):
    """Trích xuất thiếu trường bắt buộc -> hỏi lại, nêu ĐÚNG tên trường thiếu."""
    from src.api.routes import chat as chat_mod

    async def fake_extract(msg):
        return json.dumps({"origin": "Hữu Nghị", "destination": None,
                           "vehicle_type": "5T"})

    class FakeManager:
        extract_quote_request = staticmethod(fake_extract)

    monkeypatch.setattr(chat_mod, "runtime", None, raising=False)  # không dùng module-level
    from src.api import dependencies
    monkeypatch.setattr(dependencies.runtime, "manager", FakeManager())

    out = await chat_mod._handle_logistics_quote("...", "req-test")
    assert "điểm giao hàng" in out
    assert "điểm lấy hàng" not in out          # trường đã có thì không đòi


@pytest.mark.asyncio
async def test_webhook_not_configured_message(monkeypatch):
    """Đủ trường nhưng chưa cấu hình webhook -> báo rõ, không nuốt lỗi."""
    from src.api import dependencies
    from src.api.routes import chat as chat_mod

    async def fake_extract(msg):
        return json.dumps({"origin": "Hữu Nghị", "destination": "Hải Phòng",
                           "vehicle_type": "5T"})

    class FakeManager:
        extract_quote_request = staticmethod(fake_extract)

    monkeypatch.setattr(dependencies.runtime, "manager", FakeManager())
    monkeypatch.delenv("N8N_QUOTE_WEBHOOK_URL", raising=False)

    out = await chat_mod._handle_logistics_quote("...", "req-test")
    assert "N8N_QUOTE_WEBHOOK_URL" in out


@pytest.mark.asyncio
async def test_unparseable_extraction_gives_guidance(monkeypatch):
    """Model trả rác (LOCAL mock) -> hướng dẫn định dạng, không stack trace."""
    from src.api import dependencies
    from src.api.routes import chat as chat_mod

    async def fake_extract(msg):
        return "xin lỗi tôi không hiểu"

    class FakeManager:
        extract_quote_request = staticmethod(fake_extract)

    monkeypatch.setattr(dependencies.runtime, "manager", FakeManager())
    out = await chat_mod._handle_logistics_quote("...", "req-test")
    assert "Báo giá xe 5 tấn" in out           # câu mẫu hướng dẫn


@pytest.mark.asyncio
async def test_happy_path_calls_webhook(monkeypatch):
    """Đủ trường + webhook cấu hình -> POST đúng payload, trả draft_id."""
    from src.api import dependencies
    from src.api.routes import chat as chat_mod
    from src.core import utils as utils_mod

    async def fake_extract(msg):
        return json.dumps({
            "origin": "Hữu Nghị", "destination": "Hải Phòng",
            "vehicle_type": "5T", "cargo_type": "Hàng lạnh",
            "pickup_date": "2026-07-29",
            "customer_name": "Anh Tuấn", "customer_email": "tuan@minhlong.vn",
        })

    class FakeManager:
        extract_quote_request = staticmethod(fake_extract)

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"ok": True, "draft_id": "QD-TEST-01"}

    class FakeClient:
        async def post(self, url, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResp()

    monkeypatch.setattr(dependencies.runtime, "manager", FakeManager())
    monkeypatch.setenv("N8N_QUOTE_WEBHOOK_URL", "http://n8n.local/webhook/logistics-quote")
    monkeypatch.setattr(utils_mod.HttpClientPool, "get_client", staticmethod(lambda: FakeClient()))

    out = await chat_mod._handle_logistics_quote("báo giá...", "req-test")

    assert captured["url"].endswith("/logistics-quote")
    assert captured["payload"]["vehicle_type"] == "5T"
    assert captured["payload"]["customer_email"] == "tuan@minhlong.vn"
    assert "QD-TEST-01" in out
    assert "duyệt" in out                       # nhắc rõ luồng nháp -> duyệt


# ===========================================================================
# Workflow JSON hợp lệ về cấu trúc n8n
# ===========================================================================

def test_logistics_workflows_are_valid_n8n_structure():
    """4 file JSON phải parse được và connections chỉ trỏ tới node có thật."""
    from pathlib import Path
    wdir = Path("workflows/logistics")
    files = sorted(wdir.glob("*.json"))
    assert len(files) == 4

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        names = {n["name"] for n in data["nodes"]}
        assert len(names) == len(data["nodes"]), f"{f.name}: trùng tên node"
        for n in data["nodes"]:
            assert isinstance(n.get("typeVersion"), (int, float)), f"{f.name}/{n['name']}"
            assert isinstance(n.get("position"), list) and len(n["position"]) == 2
        for src, outs in data["connections"].items():
            assert src in names, f"{f.name}: connections từ node lạ {src!r}"
            for branch in outs["main"]:
                for link in branch:
                    assert link["node"] in names, (
                        f"{f.name}: {src} trỏ tới node lạ {link['node']!r}"
                    )
