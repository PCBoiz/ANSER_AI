"""
src/core/saas_api.py — Tra cứu dữ liệu nghiệp vụ trực tiếp từ DB của Body.

⚠️ SCHEMA MAP (ngay dưới): tên bảng/cột PHẢI khớp core/db/connection.py bên Body.
   Nếu Body đặt tên khác, CHỈ sửa khối hằng số dưới đây — toàn bộ SQL tự đúng theo.
   (Bản cũ truy vấn bảng 'items' + cột JSON 'metadata' — KHÔNG tồn tại trong Body.)
"""
import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.core.config import Config

logger = logging.getLogger(__name__)

# =====================================================================
# SCHEMA MAP — đối chiếu với Body/core/db/connection.py rồi chỉnh nếu cần
# =====================================================================
PRODUCTS_TABLE = "products"
P_ID = "id"
P_NAME = "name"
P_PRICE = "price"
P_STOCK = "stock_quantity"      # value-chain của Body có products.stock_quantity
P_WORKSPACE = "workspace_id"

SALES_TABLE = "sales"
S_AMOUNT = "amount"             # tổng tiền 1 giao dịch POS
S_DATE = "created_at"           # cột thời gian (bản cũ dùng 'date' — KIỂM TRA lại)
S_WORKSPACE = "workspace_id"
# =====================================================================


def _period_filter(period: str) -> str:
    """
    Trả về điều kiện WHERE theo kỳ (PostgreSQL — môi trường production Neon).
    SQLite (dev) không có date_trunc/INTERVAL; chỉ 'today' chạy được trên SQLite.
    """
    period = (period or "today").lower()
    if period == "week":
        return f"{S_DATE} >= date_trunc('week', CURRENT_DATE)"
    if period == "month":
        return f"{S_DATE} >= date_trunc('month', CURRENT_DATE)"
    # mặc định / 'today'
    return f"date({S_DATE}) = CURRENT_DATE"


# =====================================================================
#  ĐỌC KỲ TỪ CÂU HỎI
# ---------------------------------------------------------------------
#  Đặt CẠNH `_period_filter` có chủ đích: danh sách kỳ đọc được và danh
#  sách kỳ truy vấn được phải luôn khớp nhau. Tách ra hai file thì thêm
#  một kỳ ở bên này mà quên bên kia, và biểu hiện là số của kỳ SAI —
#  loại lỗi không có triệu chứng.
# =====================================================================

SUPPORTED_PERIODS = ("today", "week", "month")

# Kỳ KHÔNG truy vấn được — phải khớp TRƯỚC, vì "tháng vừa rồi" và "tháng
# này" chỉ khác nhau một từ mà ra hai con số hoàn toàn khác.
_KY_CHUA_CO = (
    ("hôm qua", re.compile(r"hôm qua|ngày hôm qua|bữa qua", re.I)),
    ("tuần trước", re.compile(r"tuần (trước|rồi|vừa rồi|qua)", re.I)),
    ("tháng trước", re.compile(r"tháng (trước|rồi|vừa rồi|qua)", re.I)),
    ("quý", re.compile(r"quý\s*(này|trước|vừa rồi|rồi|[1-4]|i{1,3}v?|iv)", re.I)),
    ("năm", re.compile(r"năm (nay|ngoái|trước|vừa rồi|qua)|cả năm", re.I)),
)

_KY_CO = (
    ("today", "hôm nay", re.compile(r"hôm nay|bữa nay|ngày hôm nay", re.I)),
    ("week", "tuần này", re.compile(r"tuần (này|nay)", re.I)),
    ("month", "tháng này", re.compile(r"tháng (này|nay)", re.I)),
)


@dataclass(frozen=True)
class KyHoi:
    """Kỳ người dùng đang hỏi. `ho_tro=False` -> chưa truy vấn được kỳ đó."""

    period: str        # khoá đưa vào `_period_filter`; rỗng khi chưa hỗ trợ
    nhan: str          # tên tiếng Việt để dán vào ngữ cảnh và câu trả lời
    ho_tro: bool


def parse_period(question: str) -> KyHoi:
    """
    Đọc kỳ từ câu hỏi. Không nhắc kỳ nào -> hôm nay.

    VÌ SAO CẦN: `chat.py` từng đóng cứng `period="today"` bất kể người dùng hỏi
    kỳ nào. Hỏi "tháng trước bán được bao nhiêu" thì model chỉ nhận được số HÔM
    NAY, và chốt chặn neo số liệu KHÔNG bắt được — con số ấy có thật trong ngữ
    cảnh. Đúng số, sai câu hỏi: loại sai tệ nhất vì không có dấu hiệu gì.
    """
    q = question or ""
    for nhan, mau in _KY_CHUA_CO:
        if mau.search(q):
            return KyHoi("", nhan, False)
    for period, nhan, mau in _KY_CO:
        if mau.search(q):
            return KyHoi(period, nhan, True)
    return KyHoi("today", "hôm nay", True)


class SaasAPI:
    def __init__(self):
        self.config = Config()
        try:
            self.engine = create_engine(self.config.DB_URL)
        except Exception:
            logger.error("Không thể khởi tạo kết nối CSDL", exc_info=True)
            self.engine = None

    def _require_engine(self):
        if not self.engine:
            raise RuntimeError("Kết nối CSDL chưa sẵn sàng")

    def lookup_product(self, query, workspace_id=1):
        self._require_engine()
        try:
            with self.engine.connect() as conn:
                # LOWER(...) LIKE LOWER(...) thay cho ILIKE: `ILIKE` là cú pháp
                # riêng của PostgreSQL, nên mọi lần tra cứu đều ném
                # OperationalError khi `DATABASE_URL` trống và Config lùi về
                # SQLite. Lỗi đó bị `except SQLAlchemyError` nuốt và trả ra "Lỗi
                # hệ thống khi tìm sản phẩm" — trông y hệt một sự cố DB thật.
                # Hai cách viết cho cùng kết quả trên Postgres.
                sql = text(f"""
                    SELECT {P_ID}, {P_NAME}, {P_PRICE}, {P_STOCK}
                    FROM {PRODUCTS_TABLE}
                    WHERE {P_WORKSPACE} = :ws_id
                      AND LOWER({P_NAME}) LIKE LOWER(:query)
                    LIMIT 20
                """)
                rows = conn.execute(
                    sql, {"ws_id": workspace_id, "query": f"%{query}%"}
                ).fetchall()

                if not rows:
                    return f"Không tìm thấy sản phẩm '{query}' trong kho."

                results = []
                for r in rows:
                    price = f"{r[2]:,.0f} VND" if r[2] is not None else "N/A"
                    results.append({
                        "id": r[0],
                        "name": r[1],
                        "price": price,
                        "stock": r[3] if r[3] is not None else "N/A",
                    })
                return json.dumps(results, ensure_ascii=False, indent=2)
        except SQLAlchemyError:
            logger.error(
                "Lỗi truy vấn sản phẩm query='%s' workspace_id=%s",
                query, workspace_id, exc_info=True,
            )
            return f"Lỗi hệ thống khi tìm sản phẩm '{query}'."

    def get_sales_report(self, workspace_id=1, period="today"):
        self._require_engine()
        try:
            with self.engine.connect() as conn:
                sql = text(f"""
                    SELECT COALESCE(SUM({S_AMOUNT}), 0), COUNT(*)
                    FROM {SALES_TABLE}
                    WHERE {S_WORKSPACE} = :ws_id
                      AND {_period_filter(period)}
                """)
                res = conn.execute(sql, {"ws_id": workspace_id}).fetchone()

                revenue = res[0] if res and res[0] else 0
                orders = res[1] if res and res[1] else 0
                return {
                    "period": (period or "today").lower(),
                    "revenue": f"{revenue:,.0f} VND",
                    "orders": orders,
                }
        except SQLAlchemyError:
            logger.error(
                "Lỗi truy vấn báo cáo bán hàng workspace_id=%s period=%s",
                workspace_id, period, exc_info=True,
            )
            return {"period": period, "revenue": "Lỗi", "orders": 0}

    def update_price(self, product_name, new_price, workspace_id=1):
        self._require_engine()
        try:
            with self.engine.connect() as conn:
                sql_find = text(f"""
                    SELECT {P_ID}, {P_PRICE}
                    FROM {PRODUCTS_TABLE}
                    WHERE LOWER({P_NAME}) LIKE LOWER(:name) AND {P_WORKSPACE} = :ws_id
                    LIMIT 1
                """)
                item = conn.execute(
                    sql_find, {"name": f"%{product_name}%", "ws_id": workspace_id}
                ).fetchone()

                if not item:
                    return f"Không tìm thấy sản phẩm '{product_name}'."

                old_price = item[1]
                sql_update = text(f"UPDATE {PRODUCTS_TABLE} SET {P_PRICE} = :price WHERE {P_ID} = :id")
                conn.execute(sql_update, {"price": float(new_price), "id": item[0]})
                conn.commit()

                return f"Đã cập nhật '{product_name}': {old_price} → {new_price} VND"
        except SQLAlchemyError:
            logger.error(
                "Lỗi cập nhật giá product='%s' workspace_id=%s",
                product_name, workspace_id, exc_info=True,
            )
            return f"Lỗi hệ thống khi cập nhật giá '{product_name}'."
