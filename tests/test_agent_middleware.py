"""
tests/test_agent_middleware.py — lớp mỏng giữa CoderAgent và định dạng workflow.

VÌ SAO ĐÁNG VIẾT DÙ CHỈ 47 DÒNG
-------------------------------
File này từng TỰ ĐỊNH NGHĨA một danh mục node riêng (`google_sheet_read`,
`discord_notify`, khoá `params`, không có `position`) — định dạng THỨ BA trong
repo, mâu thuẫn với prompt (n8n) và với lớp validate (n8n). Workflow sinh ra
theo bản đó không import vào n8n được (ARCHITECTURE.md §11.1).

Bản 27/07/2026 gỡ sạch, chỉ còn chuyển tiếp sang `workflow_schema`. Nhưng
"chỉ còn chuyển tiếp" là một tính chất phải được GIỮ, không phải một sự thật
vĩnh viễn: thêm một `return {...}` viết tay vào đây là dựng lại đúng định dạng
thứ ba, và lần này không ai nhớ vì sao nó sai.

Nên các test dưới đây kiểm ĐỒNG NHẤT với nguồn sự thật, chứ không kiểm nội dung
trả về — nội dung là việc của `test_workflow_schema.py`.
"""

from __future__ import annotations

from src.core import workflow_schema
from src.core.agent_middleware import AgentMiddleware


def test_danh_muc_node_lay_tu_nguon_su_that():
    """Lệch một ký tự nghĩa là có nơi thứ hai định nghĩa danh mục node."""
    assert AgentMiddleware().get_workflow_tools() == workflow_schema.render_node_catalog()


def test_vi_du_few_shot_lay_tu_nguon_su_that():
    assert AgentMiddleware().get_workflow_examples() == workflow_schema.render_examples()


def test_json_schema_lay_tu_nguon_su_that():
    """
    Lược đồ này đi thẳng vào `guided_json` của vLLM. Một bản sao lệch ở đây ép
    model sinh đúng theo bản sao, rồi lớp validate lại chấm theo bản gốc — và
    mọi workflow đều trượt mà không ai hiểu vì sao.
    """
    assert AgentMiddleware().get_workflow_json_schema() == workflow_schema.build_workflow_schema()


def test_validate_dung_chung_ham_voi_route_chat():
    """
    `/chat` gọi `workflow_schema.validate_workflow`. Nếu middleware chấm bằng
    luật khác thì cùng một workflow sẽ hợp lệ ở chỗ này và hỏng ở chỗ kia.
    """
    hong = {"payload": {"nodes": []}}
    assert AgentMiddleware.validate(hong) == workflow_schema.validate_workflow(hong)


def test_bao_dung_dang_chay_catalog_du_phong_hay_khong():
    """
    False = `typeVersion` có thể lệch với n8n thật của Body, workflow import vào
    sẽ lỗi. Đây là thông tin chẩn đoán, không được đoán bừa.
    """
    assert AgentMiddleware().using_real_templates() is workflow_schema.is_using_real_templates()


def test_khong_giu_trang_thai():
    """
    Hai lần dựng phải cho cùng kết quả. Có trạng thái ở đây nghĩa là danh mục
    node phụ thuộc thứ tự gọi — thứ không thể lần ra khi nó sai.
    """
    a, b = AgentMiddleware(), AgentMiddleware()
    assert a.get_workflow_tools() == b.get_workflow_tools()
    assert a.__dict__ == {} == b.__dict__


def test_khong_dinh_nghia_lai_gi_trong_file_nay():
    """
    Chốt chặn thẳng vào mã nguồn: file này không được chứa tên node hay khoá
    định dạng nào. Có là dấu hiệu định dạng thứ ba đang quay lại.
    """
    import ast
    import inspect

    from src.core import agent_middleware

    # Bỏ MỌI docstring rồi mới soi. Tài liệu ở file này cố ý nhắc tên định dạng
    # cũ để giải thích vì sao không được làm thế — soi cả docstring thì chốt
    # chặn bắt nhầm chính lời cảnh báo của nó.
    cay = ast.parse(inspect.getsource(agent_middleware))
    for node in ast.walk(cay):
        than_node = getattr(node, "body", None)
        if isinstance(than_node, list) and than_node:
            dau = than_node[0]
            if (isinstance(dau, ast.Expr) and isinstance(dau.value, ast.Constant)
                    and isinstance(dau.value.value, str)):
                than_node.pop(0)
    than = ast.unparse(cay)

    for dau_hieu in ("google_sheet", "discord_notify", '"params"', "'params'",
                     '"nodes"', "typeVersion"):
        assert dau_hieu not in than, (
            f"{dau_hieu!r} xuất hiện trong agent_middleware.py — định dạng "
            "workflow phải chỉ được định nghĩa ở workflow_schema.py (P4)."
        )
