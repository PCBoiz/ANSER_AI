"""
src/agents/agentic.py — vòng lặp agentic: model chọn tool, code chạy tool.

VÌ SAO CẦN (ARCHITECTURE §9)
---------------------------
Trước bản này, router chọn cứng MỘT nhánh rồi gọi LLM đúng một lần. Model chưa
bao giờ được tự quyết định dùng công cụ nào. Câu như "tháng này lãi bao nhiêu,
mặt hàng nào lãi nhất, có nên nhập thêm không" cần ba bước nối tiếp — kiến trúc
một-lần-gọi không làm được.

RANH GIỚI (P1 — quan trọng nhất ở file này)
-------------------------------------------
Model chỉ được làm HAI việc:
  1. chọn tool + điền tham số   (ngôn ngữ tự nhiên -> struct)
  2. viết câu trả lời cuối       (struct -> ngôn ngữ tự nhiên)
MỌI phép tính nằm trong tool tất định. Vòng lặp này không cho model đường nào
để tự tính rồi tuyên bố kết quả: `answer` chỉ được viết sau khi đã có kết quả
tool, và benchmark kiểm tra mọi con số trong answer phải có trong kết quả tool.

CHỐNG CHẠY LOẠN
---------------
- `max_steps` (mặc định 4): trần cứng số lần gọi tool.
- Lặp lại đúng (tool, arguments) đã gọi -> chặn ngay, trả lỗi vào bước sau để
  model đổi hướng thay vì quay vòng tới hết trần.
- Guided decoding ép đúng cấu trúc quyết định -> không có "JSON hỏng nên bỏ lượt".
- Tool lỗi KHÔNG làm sập vòng: lỗi đi vào observation, model có cơ hội hỏi lại
  người dùng.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from src.core.prompts import Prompts

logger = logging.getLogger("projecta.agents.agentic")

DEFAULT_MAX_STEPS = 4
# Kết quả tool dài hơn mức này bị cắt trước khi đưa lại vào prompt: bảng xếp
# hạng 100 mặt hàng ăn hết ngân sách ngữ cảnh mà model chỉ cần vài dòng đầu.
MAX_OBSERVATION_CHARS = 3000


def build_decision_schema(tool_names: list[str]) -> dict[str, Any]:
    """
    JSON Schema cho MỘT quyết định của agent — đưa vào guided_json.

    `oneOf` gọi-tool / trả-lời: grammar không cho model xuất nửa vời (vừa gọi
    tool vừa tuyên bố đáp án), thứ hay xảy ra khi chỉ dặn bằng lời trong prompt.
    """
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string", "maxLength": 400},
            "tool": {"type": "string", "enum": tool_names},
            "arguments": {"type": "object"},
            "answer": {"type": "string", "maxLength": 2000},
        },
        "required": ["thought"],
        "oneOf": [
            {"required": ["tool", "arguments"], "not": {"required": ["answer"]}},
            {"required": ["answer"], "not": {"required": ["tool"]}},
        ],
        "additionalProperties": False,
    }


def render_tools(tool_defs: list[dict]) -> str:
    """Danh mục tool cho prompt — dẫn xuất từ manifest, không viết tay (P4)."""
    lines = []
    for tool in tool_defs:
        schema = tool.get("input_schema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        fields = ", ".join(
            f"{name}{'*' if name in required else ''}"
            for name in list(props)[:12]
        )
        lines.append(
            f"- {tool['name']}: {tool.get('description', '').strip()}\n"
            f"    tham số: {fields or '(không có)'}   (* = bắt buộc)"
        )
    return "\n".join(lines)


class AgenticLoop:
    """
    Vòng suy nghĩ - hành động - quan sát.

    `tool_runner(name, arguments) -> dict` do bên gọi cung cấp: ở Brain nó gọi
    thẳng hàm Python của /tools (không đi qua HTTP nội bộ — cùng process, gọi
    thẳng vừa nhanh vừa không cần token).
    """

    def __init__(
        self,
        manager,
        tool_defs: list[dict],
        tool_runner: Callable[[str, dict], Any],
        max_steps: int = DEFAULT_MAX_STEPS,
    ):
        self.manager = manager
        self.tool_defs = tool_defs
        self.tool_runner = tool_runner
        self.max_steps = max_steps
        self._names = [t["name"] for t in tool_defs]

    def _system(self) -> str:
        return Prompts.AGENT_SYSTEM.format(tools=render_tools(self.tool_defs))

    @staticmethod
    def _parse(raw: str) -> Optional[dict]:
        """Bóc quyết định. Guided decoding lo cấu trúc; đây là lưới an toàn."""
        from src.api.routes.chat import _extract_json_block
        obj, _err = _extract_json_block(raw or "")
        return obj if isinstance(obj, dict) else None

    async def run(self, question: str, history: list[dict] | None = None) -> dict:
        """
        Chạy tới khi model đưa `answer` hoặc chạm trần bước.

        Trả {answer, steps[], tool_calls, hit_limit} — `steps` là vết đầy đủ,
        dùng cho xAI ("vì sao ra kết quả này") và cho ai_metrics_log.
        """
        schema = build_decision_schema(self._names)
        system = self._system()
        steps: list[dict] = []
        called: set[str] = set()
        transcript = list(history or [])
        user_turn = question

        for step_no in range(1, self.max_steps + 1):
            raw = await self.manager.generate_chat(
                system=system,
                user=user_turn,
                max_new_tokens=700,
                temperature=0.1,
                json_schema=schema,
                history=transcript,
            )
            decision = self._parse(raw)

            if decision is None:
                logger.warning("Agentic: không đọc được quyết định ở bước %d", step_no)
                steps.append({"step": step_no, "error": "quyết định không đọc được"})
                break

            # --- model kết luận ---
            if decision.get("answer"):
                steps.append({
                    "step": step_no,
                    "thought": decision.get("thought", ""),
                    "answer": decision["answer"],
                })
                return {
                    "answer": decision["answer"],
                    "steps": steps,
                    "tool_calls": len([s for s in steps if "tool" in s]),
                    "hit_limit": False,
                }

            # --- model gọi tool ---
            name = decision.get("tool")
            args = decision.get("arguments") or {}
            if name not in self._names:
                observation = {"error": f"không có tool tên '{name}'"}
            else:
                signature = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                if signature in called:
                    observation = {
                        "error": "đã gọi tool này với đúng tham số này rồi. "
                                 "Đổi tham số, đổi tool, hoặc trả lời/hỏi lại người dùng."
                    }
                else:
                    called.add(signature)
                    try:
                        observation = self.tool_runner(name, args)
                    except Exception as exc:      # tool lỗi -> vào observation
                        logger.warning("Agentic: tool %s lỗi: %s", name, exc)
                        observation = {"error": f"tool lỗi: {exc}"}

            obs_text = json.dumps(observation, ensure_ascii=False, default=str)
            if len(obs_text) > MAX_OBSERVATION_CHARS:
                obs_text = obs_text[:MAX_OBSERVATION_CHARS] + " …(đã cắt bớt)"

            steps.append({
                "step": step_no,
                "thought": decision.get("thought", ""),
                "tool": name,
                "arguments": args,
                "observation": observation,
            })

            # Lượt tiếp: đưa quyết định vừa rồi + kết quả vào đúng khe hội thoại
            transcript.append({"role": "user", "content": user_turn})
            transcript.append({
                "role": "assistant",
                "content": json.dumps(
                    {k: decision.get(k) for k in ("thought", "tool", "arguments")},
                    ensure_ascii=False,
                ),
            })
            user_turn = f"KẾT QUẢ TOOL {name}:\n{obs_text}"

        # --- chạm trần: KHÔNG bịa kết luận ---
        logger.info("Agentic: chạm trần %d bước", self.max_steps)
        return {
            "answer": (
                "Tôi chưa hoàn thành được yêu cầu này trong số bước cho phép. "
                "Bạn tách nhỏ câu hỏi giúp tôi, hoặc nói rõ cần con số nào trước."
            ),
            "steps": steps,
            "tool_calls": len([s for s in steps if "tool" in s]),
            "hit_limit": True,
        }


__all__ = ["AgenticLoop", "build_decision_schema", "render_tools", "DEFAULT_MAX_STEPS"]
