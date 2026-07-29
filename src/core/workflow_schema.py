"""
src/core/workflow_schema.py — NGUỒN SỰ THẬT DUY NHẤT cho định dạng workflow n8n.

VÌ SAO CÓ FILE NÀY
------------------
Trước bản này, định dạng workflow được định nghĩa ở BỐN nơi với BA định dạng khác
nhau (ARCHITECTURE.md §11.1):

  1. src/data/blueprints/*.json   -> Make.com   (dữ liệu fine-tune)
  2. prompts.py::CODER_SYSTEM     -> n8n rút gọn, dùng "edges"
  3. agent_middleware.py          -> engine nội bộ Body, dùng "params"
  4. chat.py::_validate_workflow  -> n8n rút gọn

Model được fine-tune trên (1), prompt bằng (2), đưa danh mục (3), validate theo (4).
Đó là nguyên nhân gốc khiến JSON workflow hỏng liên tục — KHÔNG phải model yếu.

CATALOG PHẢI RÚT RA TỪ WORKFLOW THẬT, KHÔNG ĐƯỢC BỊA
----------------------------------------------------
Body đã có sẵn n8n self-hosted (Docker) kèm một số workflow đang chạy thật. Danh
mục node và ví dụ few-shot PHẢI lấy từ đó, vì:

  - Node type và typeVersion phụ thuộc phiên bản n8n mà Body đang chạy. Đoán sai
    typeVersion là workflow không import được.
  - Workflow thật đã dùng đúng credential, đúng biến môi trường, đúng quy ước đặt
    tên của Body. Few-shot từ ví dụ thật dạy được những thứ đó; ví dụ bịa thì không.
  - Body là nguồn sự thật về việc n8n instance đó làm được gì.

Vì repo Body chưa merge vào đây, module hoạt động theo hai chế độ:

  * CÓ template  -> quét thư mục, rút node type + typeVersion + ví dụ THẬT đang dùng
  * CHƯA có      -> dùng DEFAULT_NODE_CATALOG bên dưới, và GHI LOG CẢNH BÁO

Trỏ `N8N_TEMPLATES_DIR` tới thư mục `workflow_templates/` của Body là module tự
cấu hình lại. Không phải sửa code.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("projecta.workflow_schema")


# ---------------------------------------------------------------------------
# Catalog dự phòng — CHỈ dùng khi chưa có template thật
# ---------------------------------------------------------------------------
# Cố tình giữ ngắn. Mỗi node thừa làm giảm độ chính xác chọn node của model và tốn
# token prompt. Khi Body merge vào, catalog thật sẽ thay thế toàn bộ phần này.

DEFAULT_NODE_CATALOG: dict[str, dict[str, Any]] = {
    "n8n-nodes-base.scheduleTrigger": {
        "trigger": True,
        "typeVersion": 1.2,
        "desc": "Chạy theo lịch (mỗi N giờ/ngày, hoặc giờ cố định)",
        "example": {"rule": {"interval": [{"field": "hours", "hoursInterval": 4}]}},
    },
    "n8n-nodes-base.webhook": {
        "trigger": True,
        "typeVersion": 2,
        "desc": "Nhận HTTP request từ ANSER Body hoặc hệ thống ngoài",
        "example": {"path": "anser-hook", "httpMethod": "POST"},
    },
    "n8n-nodes-base.httpRequest": {
        "trigger": False,
        "typeVersion": 4.2,
        "desc": "Gọi HTTP. Dùng cho MỌI thao tác ghi dữ liệu (qua API Body), gọi tool ANSER, và gửi Discord",
        "example": {
            "url": "={{$env.ANSER_API}}/api/n8n/internal/low-stock",
            "method": "GET",
        },
    },
    "n8n-nodes-base.postgres": {
        "trigger": False,
        "typeVersion": 2.4,
        "desc": "Truy vấn CSDL. CHỈ SELECT — mọi lệnh ghi đều bị từ chối",
        "example": {
            "operation": "executeQuery",
            "query": "SELECT name, stock_quantity FROM products WHERE stock_quantity < 15",
        },
    },
    "n8n-nodes-base.googleSheets": {
        "trigger": False,
        "typeVersion": 4.5,
        "desc": "Đọc/ghi Google Sheets",
        "example": {"operation": "append", "documentId": "SHEET_ID", "sheetName": "Sheet1"},
    },
    "n8n-nodes-base.gmail": {
        "trigger": False,
        "typeVersion": 2.1,
        "desc": "Gửi email (ví dụ: gửi báo giá vận tải cho khách)",
        "example": {
            "operation": "send",
            "sendTo": "khach@example.com",
            "subject": "Báo giá vận chuyển",
            "message": "={{$json.body}}",
        },
    },
    "n8n-nodes-base.if": {
        "trigger": False,
        "typeVersion": 2,
        "desc": "Rẽ nhánh theo điều kiện. Nhánh true = output 0, false = output 1",
        "example": {
            "conditions": {
                "number": [
                    {"value1": "={{$json.stock_quantity}}", "operation": "smaller", "value2": 15}
                ]
            }
        },
    },
    "n8n-nodes-base.set": {
        "trigger": False,
        "typeVersion": 3.4,
        "desc": "Gán/đổi tên trường dữ liệu",
        "example": {
            "assignments": {
                "assignments": [
                    {"name": "message", "value": "={{$json.name}}", "type": "string"}
                ]
            }
        },
    },
    "n8n-nodes-base.splitInBatches": {
        "trigger": False,
        "typeVersion": 3,
        "desc": "Lặp qua từng item của mảng",
        "example": {"batchSize": 1},
    },
    "n8n-nodes-base.noOp": {
        "trigger": False,
        "typeVersion": 1,
        "desc": "Node rỗng — dùng làm điểm hợp nhánh",
        "example": {},
    },
}

# Node bị chặn dù có xuất hiện trong template thật.
# `code` cho phép chạy JS tuỳ ý trong n8n -> vượt qua mọi luật an toàn ta đặt ở
# tầng trên. Nếu Body thực sự cần, gỡ khỏi đây một cách có chủ đích.
BLOCKED_NODE_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.ssh",
}

_TRIGGER_HINT = re.compile(r"trigger$|^n8n-nodes-base\.webhook$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Rút catalog từ workflow n8n thật
# ---------------------------------------------------------------------------

def _iter_template_files(template_dir: Path):
    for path in sorted(template_dir.glob("*.json")):
        try:
            yield path, json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Bỏ qua template không đọc được %s: %s", path.name, exc)


def load_catalog_from_templates(template_dir: str | Path) -> dict[str, dict[str, Any]]:
    """
    Quét workflow n8n thật, rút ra node type + typeVersion + parameters mẫu.

    Chỉ giữ typeVersion CAO NHẤT gặp được cho mỗi type — template cũ có thể còn
    typeVersion lỗi thời, sinh theo bản cũ thì n8n cảnh báo deprecated.
    """
    template_dir = Path(template_dir)
    if not template_dir.is_dir():
        return {}

    catalog: dict[str, dict[str, Any]] = {}

    for path, data in _iter_template_files(template_dir):
        nodes = data.get("nodes")
        if not isinstance(nodes, list):
            continue

        for node in nodes:
            if not isinstance(node, dict):
                continue
            ntype = node.get("type")
            if not isinstance(ntype, str) or ntype in BLOCKED_NODE_TYPES:
                continue

            tversion = node.get("typeVersion")
            if not isinstance(tversion, (int, float)):
                continue

            existing = catalog.get(ntype)
            if existing and existing["typeVersion"] >= tversion:
                continue

            params = node.get("parameters")
            catalog[ntype] = {
                "trigger": bool(_TRIGGER_HINT.search(ntype)),
                "typeVersion": tversion,
                "desc": f"Dùng trong template thật: {path.stem}",
                "example": params if isinstance(params, dict) else {},
            }

    if catalog:
        logger.info(
            "Catalog rút từ %d template thật tại %s — %d node type",
            len(list(template_dir.glob("*.json"))), template_dir, len(catalog),
        )
    return catalog


def _sanitize_example_node(node: dict) -> dict:
    """
    Cắt node thật về ĐÚNG hình dạng mà schema sinh cho phép.

    Node trong workflow thật mang thêm `id`, `retryOnFail`, `maxTries`,
    `waitBetweenTries`... Schema sinh đặt additionalProperties=False — nếu
    few-shot dạy model các field đó, grammar sẽ CHẶN đúng token mà ví dụ vừa dạy,
    model bị ép rẽ sang nhánh kém hơn giữa chừng. Ví dụ và grammar phải khớp nhau
    tuyệt đối.
    """
    return {
        "name": node.get("name", ""),
        "type": node.get("type", ""),
        "typeVersion": node.get("typeVersion", 1),
        "position": node.get("position", [0, 0]),
        "parameters": node.get("parameters", {}),
    }


def load_examples_from_templates(template_dir: str | Path, limit: int = 2) -> list[dict]:
    """
    Lấy vài workflow thật làm few-shot, ưu tiên workflow nhỏ.

    Thực tế đo trên 32 template của Body: 69/262 node là `code` (bị chặn khi
    SINH) — lọc bỏ cả workflow chứa code thì gần như không còn ứng viên. Vì vậy
    thay vì bỏ cả workflow, ta THAY node code bằng noOp giữ nguyên tên/vị trí:
    cấu trúc luồng (trigger -> gọi API -> rẽ nhánh -> gửi đi) vẫn là của thật,
    còn ví dụ chỉ chứa node mà model được phép sinh.
    """
    template_dir = Path(template_dir)
    if not template_dir.is_dir():
        return []

    candidates = []
    for path, data in _iter_template_files(template_dir):
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not (3 <= len(nodes) <= 7):
            continue

        cleaned = []
        for n in nodes:
            if not isinstance(n, dict):
                break
            node = _sanitize_example_node(n)
            if node["type"] in BLOCKED_NODE_TYPES:
                # Giữ chỗ trong luồng, đổi sang node trung tính được phép sinh
                node["type"] = "n8n-nodes-base.noOp"
                node["typeVersion"] = 1
                node["parameters"] = {}
            cleaned.append(node)
        else:
            # Ưu tiên workflow vốn KHÔNG có node bị chặn (ít bị "vá" nhất)
            n_patched = sum(
                1 for orig in nodes
                if isinstance(orig, dict) and orig.get("type") in BLOCKED_NODE_TYPES
            )
            candidates.append((n_patched, len(cleaned), path.stem, data, cleaned))

    candidates.sort(key=lambda c: (c[0], c[1]))
    return [
        {
            "action": "create_workflow",
            "name": data.get("name") or stem,
            "payload": {
                "nodes": cleaned,
                "connections": data.get("connections", {}),
            },
        }
        for _, _, stem, data, cleaned in candidates[:limit]
    ]


@lru_cache(maxsize=1)
def _active() -> tuple[dict[str, dict[str, Any]], list[dict], bool]:
    """
    (catalog, few_shot_examples, from_real_templates)

    Cache vì được gọi mỗi lần dựng prompt. Đổi N8N_TEMPLATES_DIR lúc chạy thì gọi
    reload_catalog().
    """
    template_dir = os.getenv("N8N_TEMPLATES_DIR", "").strip()

    if template_dir:
        from_templates = load_catalog_from_templates(template_dir)
        if from_templates:
            # HỢP NHẤT: mặc định + template thật, template THẮNG khi trùng type.
            #
            # Vì sao không dùng template-only: 32 workflow thật của Body chỉ chạm
            # 6 node type (mọi thứ đi qua httpRequest gọi service nội bộ). Nhưng
            # gmail/set/googleSheets vẫn có sẵn trong mọi bản n8n chuẩn và cần
            # cho nghiệp vụ chưa có template (gửi email báo giá logistics).
            # Vì sao template thắng: typeVersion của chúng là số ĐÃ CHẠY THẬT
            # trên n8n instance của Body (httpRequest 4.4, if 1 — khác hẳn số
            # tôi đoán), còn số trong DEFAULT chỉ là ước đoán.
            catalog = {**DEFAULT_NODE_CATALOG, **from_templates}
            examples = load_examples_from_templates(template_dir)
            if not examples:
                examples = [_default_example()]
            return catalog, examples, True
        logger.warning(
            "N8N_TEMPLATES_DIR=%s không có workflow n8n hợp lệ — dùng catalog dự phòng",
            template_dir,
        )
    else:
        logger.warning(
            "Chưa đặt N8N_TEMPLATES_DIR — dùng catalog DỰ PHÒNG. "
            "typeVersion có thể không khớp n8n instance của Body. "
            "Trỏ biến này tới workflow_templates/ của Body sau khi merge."
        )

    return DEFAULT_NODE_CATALOG, [_default_example()], False


def reload_catalog() -> None:
    """Xoá cache — gọi sau khi đổi N8N_TEMPLATES_DIR hoặc thêm template."""
    _active.cache_clear()


def get_node_catalog() -> dict[str, dict[str, Any]]:
    return _active()[0]


def is_using_real_templates() -> bool:
    """Cho /health biết đang chạy catalog thật hay dự phòng."""
    return _active()[2]


def allowed_types() -> list[str]:
    return sorted(get_node_catalog().keys())


def catalog_fingerprint() -> str:
    """
    Vân tay của danh mục node đang dùng (type + typeVersion).

    CODER_SYSTEM được dựng TỪ catalog này, nên dữ liệu fine-tune mang theo
    system prompt của catalog lúc sinh data. Nếu lúc serve `N8N_TEMPLATES_DIR`
    trỏ chỗ khác, prompt đổi mà model không biết — mọi thứ vẫn "chạy" nhưng
    kém đi một cách âm thầm. Dataset ghi lại vân tay này; `preflight_check.py`
    và `/health` đối chiếu.
    """
    import hashlib

    catalog = get_node_catalog()
    payload = "|".join(
        f"{t}@{catalog[t]['typeVersion']}" for t in sorted(catalog)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def trigger_types() -> set[str]:
    return {t for t, meta in get_node_catalog().items() if meta.get("trigger")}


def _default_example() -> dict:
    return {
        "action": "create_workflow",
        "name": "Cảnh báo tồn kho thấp",
        "payload": {
            "nodes": [
                {
                    "name": "Mỗi 4 tiếng",
                    "type": "n8n-nodes-base.scheduleTrigger",
                    "typeVersion": 1.2,
                    "position": [0, 0],
                    "parameters": {
                        "rule": {"interval": [{"field": "hours", "hoursInterval": 4}]}
                    },
                },
                {
                    "name": "Lấy hàng sắp hết",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 4.2,
                    "position": [220, 0],
                    "parameters": {
                        "url": "={{$env.ANSER_API}}/api/n8n/internal/low-stock",
                        "method": "GET",
                    },
                },
                {
                    "name": "Báo Discord",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 4.2,
                    "position": [440, 0],
                    "parameters": {
                        "url": "={{$env.DISCORD_WEBHOOK_URL}}",
                        "method": "POST",
                        "sendBody": True,
                        "bodyParameters": {
                            "parameters": [{"name": "content", "value": "={{$json.message}}"}]
                        },
                    },
                },
            ],
            "connections": {
                "Mỗi 4 tiếng": {
                    "main": [[{"node": "Lấy hàng sắp hết", "type": "main", "index": 0}]]
                },
                "Lấy hàng sắp hết": {
                    "main": [[{"node": "Báo Discord", "type": "main", "index": 0}]]
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# JSON Schema — đưa vào vLLM guided_json
# ---------------------------------------------------------------------------
# Guided decoding ép cấu trúc ở tầng SAMPLING: JSON sai schema trở thành bất khả
# thi, thay vì "hy vọng model làm đúng rồi retry". Vì vậy schema phải chặt nhất
# có thể ở phần diễn tả được.
#
# `connections` để tự do vì khoá của nó là TÊN NODE (động, không biết trước) —
# JSON Schema không ràng buộc được. Phần đó do validate_workflow() lo.

def build_workflow_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create_workflow"]},
            "name": {"type": "string", "minLength": 1, "maxLength": 120},
            "payload": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1, "maxLength": 60},
                                "type": {"type": "string", "enum": allowed_types()},
                                "typeVersion": {"type": "number"},
                                "position": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "minItems": 2,
                                    "maxItems": 2,
                                },
                                "parameters": {"type": "object"},
                            },
                            "required": [
                                "name", "type", "typeVersion", "position", "parameters",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "connections": {"type": "object"},
                },
                "required": ["nodes", "connections"],
                "additionalProperties": False,
            },
        },
        "required": ["action", "name", "payload"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Sinh phần prompt — dẫn xuất, không viết tay
# ---------------------------------------------------------------------------

def render_node_catalog() -> str:
    """Chuỗi mô tả node nhét vào prompt CoderAgent."""
    lines = []
    for node_type, meta in get_node_catalog().items():
        tag = " [TRIGGER]" if meta.get("trigger") else ""
        example = json.dumps(meta.get("example", {}), ensure_ascii=False)
        if len(example) > 400:                      # ví dụ dài quá thì cắt
            example = example[:400] + "…"
        lines.append(
            f'- {node_type} (typeVersion {meta["typeVersion"]}){tag}\n'
            f'    {meta.get("desc", "")}\n'
            f'    parameters mẫu: {example}'
        )
    return "\n".join(lines)


def render_examples() -> str:
    """Few-shot. Ví dụ THẬT của Body nếu có, ngược lại ví dụ dự phòng."""
    return "\n\n".join(
        json.dumps(ex, ensure_ascii=False) for ex in _active()[1]
    )


# ---------------------------------------------------------------------------
# Validate — lớp an toàn cuối
# ---------------------------------------------------------------------------
# Khi guided_json đã bật, hàm này hiếm khi bắt lỗi CẤU TRÚC. Nó tồn tại để bắt
# thứ JSON Schema không diễn tả được: toàn vẹn tham chiếu giữa connections và
# nodes, số lượng trigger, node mồ côi, và các luật an toàn.

_DANGEROUS_SQL = re.compile(
    r"\b(DROP|TRUNCATE|DELETE|ALTER|UPDATE|INSERT|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)


def _collect_sql(node: dict) -> list[str]:
    params = node.get("parameters") or {}
    return [
        params[key]
        for key in ("query", "sql", "statement")
        if isinstance(params.get(key), str)
    ]


def validate_workflow(obj: Any) -> tuple[bool, str]:
    """
    Kiểm tra workflow n8n. Trả (ok, lý_do_lỗi).

    Lý do lỗi viết tiếng Việt, CỤ THỂ — nó được đưa thẳng vào feedback retry, và
    feedback cụ thể sửa đúng hơn nhiều so với "thử lại đi".
    """
    catalog = get_node_catalog()

    if not isinstance(obj, dict):
        return False, "output không phải object JSON"
    if obj.get("action") != "create_workflow":
        return False, 'thiếu hoặc sai "action" (phải là "create_workflow")'

    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, 'thiếu "name" của workflow'

    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return False, 'thiếu "payload"'

    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False, '"payload.nodes" rỗng hoặc không phải mảng'

    node_names: set[str] = set()
    trigger_count = 0

    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            return False, f"node[{idx}] không phải object"

        nname = node.get("name")
        if not isinstance(nname, str) or not nname.strip():
            return False, f'node[{idx}] thiếu "name"'
        if nname in node_names:
            return False, (
                f'trùng tên node: "{nname}". '
                "n8n định tuyến theo TÊN nên tên phải là duy nhất"
            )
        node_names.add(nname)

        ntype = node.get("type")
        if ntype in BLOCKED_NODE_TYPES:
            return False, (
                f'node "{nname}" dùng "{ntype}" — bị chặn vì cho phép chạy mã tuỳ ý. '
                "Dùng httpRequest gọi API của ANSER Body thay thế."
            )
        if ntype not in catalog:
            return False, (
                f'node "{nname}" dùng type không được phép: "{ntype}". '
                f"Chỉ được dùng: {', '.join(allowed_types())}"
            )

        if not isinstance(node.get("typeVersion"), (int, float)):
            return False, (
                f'node "{nname}" thiếu "typeVersion" '
                f'(đúng phải là {catalog[ntype]["typeVersion"]})'
            )

        pos = node.get("position")
        if (
            not isinstance(pos, list)
            or len(pos) != 2
            or not all(isinstance(v, (int, float)) for v in pos)
        ):
            return False, f'node "{nname}" có "position" sai — phải là mảng 2 số [x, y]'

        if not isinstance(node.get("parameters"), dict):
            return False, f'node "{nname}" thiếu "parameters" (object, có thể rỗng {{}})'

        if catalog[ntype].get("trigger"):
            trigger_count += 1

        # Luật an toàn: postgres chỉ đọc
        if ntype == "n8n-nodes-base.postgres":
            for sql in _collect_sql(node):
                hit = _DANGEROUS_SQL.search(sql)
                if hit:
                    return False, (
                        f'node "{nname}" chứa lệnh SQL ghi dữ liệu ({hit.group(0).upper()}). '
                        "Node postgres CHỈ được SELECT; muốn ghi thì dùng httpRequest "
                        "gọi API của ANSER Body."
                    )
                if "SELECT" not in sql.upper():
                    return False, f'node "{nname}" phải là câu SELECT'

    if trigger_count == 0:
        return False, (
            "workflow không có node trigger. Phải có đúng 1 trong: "
            + ", ".join(sorted(trigger_types()))
        )
    if trigger_count > 1:
        return False, f"workflow có {trigger_count} node trigger, chỉ được đúng 1"

    connections = payload.get("connections")
    if not isinstance(connections, dict):
        return False, '"payload.connections" phải là object'
    if len(nodes) > 1 and not connections:
        return False, "workflow nhiều node nhưng connections rỗng — các node không nối với nhau"

    linked: set[str] = set()

    for src, outputs in connections.items():
        if src not in node_names:
            return False, f'connections trỏ từ node không tồn tại: "{src}"'
        if not isinstance(outputs, dict):
            return False, f'connections["{src}"] phải là object có khoá "main"'

        main = outputs.get("main")
        if not isinstance(main, list):
            return False, f'connections["{src}"].main phải là mảng'

        for branch in main:
            if not isinstance(branch, list):
                return False, (
                    f'connections["{src}"].main phải là MẢNG CỦA MẢNG '
                    "(mỗi output một mảng đích)"
                )
            for link in branch:
                if not isinstance(link, dict):
                    return False, f'connections["{src}"] có phần tử không phải object'
                dest = link.get("node")
                if dest not in node_names:
                    return False, f'connections["{src}"] trỏ tới node không tồn tại: "{dest}"'
                linked.add(dest)
                linked.add(src)

    if len(nodes) > 1:
        orphans = node_names - linked
        if orphans:
            return False, (
                "node không được nối vào luồng nào: "
                + ", ".join(f'"{o}"' for o in sorted(orphans))
            )

    return True, ""


__all__ = [
    "DEFAULT_NODE_CATALOG",
    "BLOCKED_NODE_TYPES",
    "load_catalog_from_templates",
    "load_examples_from_templates",
    "reload_catalog",
    "get_node_catalog",
    "is_using_real_templates",
    "allowed_types",
    "catalog_fingerprint",
    "trigger_types",
    "build_workflow_schema",
    "render_node_catalog",
    "render_examples",
    "validate_workflow",
]
