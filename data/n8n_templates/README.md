# data/n8n_templates — 32 workflow n8n THẬT của ANSER Body

**Nguồn:** nhánh `dev` của `wikiepeidia/ANSER`, commit `d802987`
(*feat(workflows): 32 workflow n8n — retail(19) manuf(7) shared(6)*).
Trích xuất 27/07/2026 từ `workflows/{retail,manuf,shared}/`.

**Dùng để làm gì:** đây là nguồn cho `N8N_TEMPLATES_DIR` —
[`src/core/workflow_schema.py`](../../src/core/workflow_schema.py) rút node
catalog (type + typeVersion ĐÃ CHẠY THẬT trên n8n instance của Body) và few-shot
cho CoderAgent từ thư mục này. Không đặt biến này thì Brain chạy catalog dự
phòng với typeVersion ước đoán.

```
N8N_TEMPLATES_DIR=data/n8n_templates
```

**Số liệu đo được từ bộ này** (căn cứ cho các quyết định trong workflow_schema):

- 262 node, 7 type: httpRequest(84, v4.4), code(69), respondToWebhook(43),
  if(34, v1), webhook(21), scheduleTrigger(10, v1.2), errorTrigger(1)
- Mẫu tích hợp chủ đạo: **mọi thao tác dữ liệu đi qua httpRequest gọi service
  nội bộ** (`rag_service:8001`, API Body) — không dùng node googleSheets/gmail
  trực tiếp
- `code` chiếm 26% — chủ yếu format Discord embed. Node này BỊ CHẶN khi AI sinh
  workflow (chạy JS tuỳ ý); few-shot thay nó bằng `noOp` giữ nguyên luồng

**Không sửa tay các file này.** Muốn cập nhật: kéo lại từ nhánh `dev` của Body
rồi thay cả thư mục — file ở đây là bản chụp (snapshot), nguồn sự thật nằm bên
repo Body.
