"""
src/core/agent_middleware.py — cầu nối giữa CoderAgent và định dạng workflow.

BẢN 27/07/2026 — VIẾT LẠI HOÀN TOÀN.

Bản cũ TỰ ĐỊNH NGHĨA một danh mục node của engine nội bộ Body
(`google_sheet_read`, `discord_notify`, dùng khoá `params`, không có `position`).
Đó là định dạng THỨ BA trong repo, mâu thuẫn với prompt (n8n) và với lớp validate
(n8n) — xem ARCHITECTURE.md §11.1.

Nay file này KHÔNG còn định nghĩa gì cả. Nó chỉ chuyển tiếp từ
`workflow_schema.py` — nguồn sự thật duy nhất, và nguồn đó lại rút ra từ workflow
n8n THẬT của Body khi có biến môi trường `N8N_TEMPLATES_DIR`.

Giữ lại class `AgentMiddleware` để `coder.py` và code cũ không gãy.
"""

from src.core import workflow_schema


class AgentMiddleware:
    """Lớp mỏng chuyển tiếp tới workflow_schema. Không giữ trạng thái."""

    def get_db_schema(self) -> str:
        # Ở chế độ Agentic, Body gửi schema kèm user context. Trả placeholder để
        # tránh định nghĩa lược đồ ở nơi thứ hai (P4).
        return "Schema provided in user context."

    def get_workflow_tools(self) -> str:
        """Danh mục node cho prompt CoderAgent."""
        return workflow_schema.render_node_catalog()

    def get_workflow_examples(self) -> str:
        """Few-shot — workflow thật của Body nếu có."""
        return workflow_schema.render_examples()

    def get_workflow_json_schema(self) -> dict:
        """JSON Schema đưa vào vLLM guided_json."""
        return workflow_schema.build_workflow_schema()

    def using_real_templates(self) -> bool:
        """False = đang chạy catalog dự phòng, typeVersion có thể lệch n8n của Body."""
        return workflow_schema.is_using_real_templates()

    @staticmethod
    def validate(obj) -> tuple[bool, str]:
        return workflow_schema.validate_workflow(obj)
