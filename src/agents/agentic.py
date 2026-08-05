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

KẾ HOẠCH TOOL TẤT ĐỊNH (05/08/2026)
-----------------------------------
Bổ sung `planner`: một hàm luật quyết định trước sẽ chạy tool nào, theo thứ tự
nào (`core/tool_planner.py`). Có kế hoạch thì enum `tool` trong JSON Schema bị
thu về ĐÚNG MỘT tên cho mỗi bước — nên việc "chọn sai tool" không còn là thứ
model có thể làm, chứ không phải thứ ta dặn nó đừng làm. Đó là khác biệt giữa
ràng buộc ở tầng sampling và lời khuyên trong prompt.

Hết kế hoạch thì schema thu tiếp về CHỈ CÒN `answer`: model bắt buộc viết kết
luận từ những gì đã quan sát được, không đi lang thang thêm.

Không có `planner` (hoặc luật không khớp câu nào) thì mọi thứ chạy y như cũ:
model tự chọn trong toàn bộ danh mục.

`data_provider` giải quyết vế còn lại: `report` và `inventory_audit` cần dữ liệu
mà model không có. Thiếu nguồn thì vòng lặp DỪNG và nói thẳng là chưa có dữ
liệu — thà vậy còn hơn để model điền `arguments` bằng số nó tự nghĩ ra.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, Optional

from src.core.prompts import Prompts
from src.core.utils import extract_json_block

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


def build_answer_schema() -> dict[str, Any]:
    """
    Schema chỉ-được-trả-lời — dùng khi kế hoạch tool đã chạy hết.

    Không phải để tiết kiệm bước. Đến đây mọi con số cần thiết đã nằm trong
    observation; cho model gọi thêm tool nữa chỉ mở đường cho nó đi tìm một con
    số vừa ý hơn.
    """
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string", "maxLength": 400},
            "answer": {"type": "string", "maxLength": 2000},
        },
        "required": ["thought", "answer"],
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
        planner: Optional[Callable[[str, list[str]], list[str]]] = None,
        data_provider: Optional[Callable[[str, dict], Any]] = None,
    ):
        self.manager = manager
        self.tool_defs = tool_defs
        self.tool_runner = tool_runner
        self.max_steps = max_steps
        # Chọn tool bằng luật. None = giữ hành vi cũ (model tự chọn).
        self.planner = planner
        # Bơm dữ liệu hệ thống vào `arguments`. Trả (arguments, thiếu_gì|None).
        self.data_provider = data_provider
        self._names = [t["name"] for t in tool_defs]

    def _system(self) -> str:
        return Prompts.AGENT_SYSTEM.format(tools=render_tools(self.tool_defs))

    @staticmethod
    def _parse(raw: str) -> Optional[dict]:
        """Bóc quyết định. Guided decoding lo cấu trúc; đây là lưới an toàn."""
        obj, _err = extract_json_block(raw or "")
        return obj if isinstance(obj, dict) else None

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """
        Cho phép `tool_runner`/`data_provider` là hàm thường HOẶC async.

        `run_tool` bên `routes/tools.py` là async (nó await handler của endpoint),
        còn test dùng lambda đồng bộ. Bắt cả hai ở đây rẻ hơn nhiều so với ép mọi
        chỗ gọi phải giống nhau.
        """
        return await value if inspect.isawaitable(value) else value

    async def run(self, question: str, history: list[dict] | None = None) -> dict:
        """
        Chạy tới khi model đưa `answer` hoặc chạm trần bước.

        Trả {answer, steps[], tool_calls, hit_limit} — `steps` là vết đầy đủ,
        dùng cho xAI ("vì sao ra kết quả này") và cho ai_metrics_log.
        """
        full_schema = build_decision_schema(self._names)
        answer_schema = build_answer_schema()
        system = self._system()
        steps: list[dict] = []
        called: set[str] = set()
        observations: list[dict] = []
        transcript = list(history or [])
        user_turn = question

        # Kế hoạch tất định. Rỗng -> model tự chọn như trước.
        plan = list(self.planner(question, self._names)) if self.planner else []
        co_ke_hoach = bool(plan)
        if co_ke_hoach:
            logger.info("Agentic: kế hoạch tool tất định %s", plan)

        for step_no in range(1, self.max_steps + 1):
            # Ràng buộc ở tầng SAMPLING, không phải trong prompt: còn kế hoạch
            # thì enum chỉ có một tên; hết kế hoạch thì chỉ còn `answer`.
            if plan:
                schema = build_decision_schema([plan[0]])
            elif co_ke_hoach:
                schema = answer_schema
            else:
                schema = full_schema

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
                    "plan": plan,
                    "observations": observations,
                }

            # --- model gọi tool ---
            name = decision.get("tool")
            args = decision.get("arguments") or {}

            # Bơm dữ liệu hệ thống TRƯỚC khi chạy. Thiếu nguồn thì dừng hẳn: để
            # model đi tiếp nghĩa là để nó tự nghĩ ra doanh thu rồi hệ thống tính
            # toán nghiêm túc trên số bịa (xem tool_planner.py).
            if name in self._names and self.data_provider is not None:
                args, thieu = await self._maybe_await(self.data_provider(name, args))
                if thieu:
                    logger.info("Agentic: dừng vì thiếu dữ liệu cho %s", name)
                    steps.append({"step": step_no, "tool": name, "data_missing": thieu})
                    return {
                        "answer": thieu,
                        "steps": steps,
                        "tool_calls": len([s for s in steps if "observation" in s]),
                        "hit_limit": False,
                        "plan": plan,
                        "observations": observations,
                        "data_missing": True,
                    }

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
                        observation = await self._maybe_await(self.tool_runner(name, args))
                        observations.append({"tool": name, "result": observation})
                    except Exception as exc:      # tool lỗi -> vào observation
                        logger.warning("Agentic: tool %s lỗi: %s", name, exc)
                        observation = {"error": f"tool lỗi: {exc}"}

            # Bước theo kế hoạch đã chạy xong -> gạch khỏi danh sách. Chỉ gạch khi
            # ĐÚNG tool đầu kế hoạch, để một lượt hỏng không làm trôi cả kế hoạch.
            if plan and name == plan[0]:
                plan.pop(0)

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
            "plan": plan,
            "observations": observations,
        }


__all__ = [
    "AgenticLoop",
    "build_answer_schema",
    "build_decision_schema",
    "render_tools",
    "DEFAULT_MAX_STEPS",
]
