"""
src/agents/coder.py — sinh workflow n8n.

BẢN 27/07/2026. Thay đổi so với bản Ngày 7:

  - Định dạng đích là n8n THẬT ("connections" khoá theo tên node), không phải
    "edges" như bản cũ. Workflow bản cũ sinh ra KHÔNG import vào n8n được.
  - Bật guided decoding: output bị ép khớp JSON Schema ở tầng sampling, nên JSON
    sai cấu trúc là bất khả thi. Vòng retry vì thế chỉ còn để bắt lỗi NGHIỆP VỤ
    (thiếu trigger, node mồ côi, SQL ghi dữ liệu), không còn để bắt lỗi cú pháp.
  - Danh mục node + few-shot lấy từ workflow_schema (rút từ template n8n THẬT của
    Body khi có N8N_TEMPLATES_DIR) thay vì hardcode ở đây.
  - max_new_tokens 1200 -> 1600: workflow n8n thật dài hơn dạng "edges" rút gọn vì
    có connections đầy đủ và typeVersion từng node.
"""

from src.agents.base import BaseAgent
from src.core.agent_middleware import AgentMiddleware
from src.core.prompts import Prompts


class CoderAgent(BaseAgent):
    def __init__(self, engine, memory):
        super().__init__(engine, "coder")
        self.middleware = AgentMiddleware()

    async def write_code(self, task: str, plan: str, feedback: str = ""):
        """
        Sinh workflow n8n từ PLAN.

        `feedback` do chat.py truyền vào ở lần retry, chứa lý do lỗi cụ thể từ
        `validate_workflow()`. Feedback cụ thể sửa đúng hơn nhiều so với việc chỉ
        bảo model "thử lại".
        """
        system = Prompts.CODER_SYSTEM.format(
            tools=self.middleware.get_workflow_tools(),
            example=self.middleware.get_workflow_examples(),
        )

        user = f"YÊU CẦU: {task}\nKẾ HOẠCH: {plan}"
        if feedback:
            user += (
                f"\n\nLỖI LẦN TRƯỚC: {feedback}\n"
                "Sửa đúng lỗi đó rồi xuất lại workflow."
            )

        return await self.generate_chat(
            system=system,
            user=user,
            max_new_tokens=1600,
            temperature=0.1,
            json_schema=self.middleware.get_workflow_json_schema(),
        )
