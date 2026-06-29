import json
import logging

from sqlalchemy import create_engine, text

from src.core.config import Config

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self):
        self.config = Config()
        try:
            self.engine = create_engine(self.config.DB_URL)
        except Exception:
            logger.error("Failed to create database engine", exc_info=True)
            self.engine = None

    def get_conn(self):
        if not self.engine:
            raise RuntimeError("Database engine is not configured")
        return self.engine.connect()

    def _get_active_session(self, conn, user_id):
        # Always try to grab the latest session for this user
        row = conn.execute(text("SELECT id FROM chat_sessions WHERE user_id = :uid ORDER BY last_active DESC LIMIT 1"), {"uid": str(user_id)}).fetchone()
        if row:
            return row[0]

        # If none, create one
        res = conn.execute(text("INSERT INTO chat_sessions (user_id, workspace_id, title) VALUES (:uid, '1', 'New Session') RETURNING id"), {"uid": str(user_id)}).fetchone()
        return res[0]

    def save_attachment(self, user_id, workspace_id, filename, filetype, analysis):
        try:
            with self.get_conn() as conn:
                sid = self._get_active_session(conn, user_id)

                logger.info("Saving attachment user_id=%s session=%s file=%s", user_id, sid, filename)
                conn.execute(text("INSERT INTO chat_attachments (session_id, file_name, file_type, analysis_summary) VALUES (:sid, :f, :t, :a)"),
                             {"sid": sid, "f": filename, "t": filetype, "a": analysis})

                # Bump session activity
                conn.execute(text("UPDATE chat_sessions SET last_active = CURRENT_TIMESTAMP WHERE id = :sid"), {"sid": sid})
                conn.commit()
        except Exception:
            logger.error("DB error saving attachment user_id=%s file=%s", user_id, filename, exc_info=True)

    def add_message(self, user_id, workspace_id, role, content):
        try:
            with self.get_conn() as conn:
                sid = self._get_active_session(conn, user_id)
                conn.execute(text("INSERT INTO chat_messages (session_id, role, content) VALUES (:sid, :role, :content)"),
                             {"sid": sid, "role": role, "content": str(content)})
                conn.commit()
        except Exception:
            logger.error("DB error saving message user_id=%s role=%s", user_id, role, exc_info=True)

    def get_context_string(self, user_id, limit=6):
        try:
            with self.get_conn() as conn:
                # 1. Get Visual Context (Latest attachment in active session)
                sid = self._get_active_session(conn, user_id)

                att_row = conn.execute(text("SELECT file_name, analysis_summary FROM chat_attachments WHERE session_id = :sid ORDER BY created_at DESC LIMIT 1"), {"sid": sid}).fetchone()

                vision_context = ""
                if att_row:
                    vision_context = f"\n[SYSTEM: The user just uploaded an image named '{att_row[0]}'.]\n[IMAGE ANALYSIS]: {att_row[1]}\n(Use this analysis to answer questions about 'the image'.)\n"

                # 2. Get Text History
                rows = conn.execute(text("SELECT role, content FROM chat_messages WHERE session_id = :sid ORDER BY created_at DESC LIMIT :lim"), {"sid": sid, "lim": limit}).fetchall()
                history = "\n".join([f"{r[0]}: {r[1]}" for r in reversed(rows)])

                return vision_context + "\n" + history
        except Exception:
            logger.error("DB error fetching context user_id=%s", user_id, exc_info=True)
            return ""

    def get_user_workspaces(self, uid):
        if not self.engine:
            return []
        try:
            with self.get_conn() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT w.id, w.name
                        FROM workspaces w
                        JOIN user_workspaces uw ON uw.workspace_id = w.id
                        WHERE uw.user_id = :uid
                        ORDER BY w.id
                        """
                    ),
                    {"uid": str(uid)},
                ).fetchall()
            return [{"id": row[0], "name": row[1]} for row in rows]
        except Exception:
            logger.error("DB error fetching workspaces user_id=%s", uid, exc_info=True)
            return []

    def get_user_stores(self, uid):
        workspaces = self.get_user_workspaces(uid)
        return [
            {
                "id": ws.get("id"),
                "name": ws.get("name", f"Store {ws.get('id')}"),
                "industry": "Retail",
                "location": "Unknown",
            }
            for ws in workspaces
        ]

    def get_store_details(self, store_id):
        if not self.engine:
            return None
        try:
            with self.get_conn() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT id, name
                        FROM workspaces
                        WHERE id = :sid
                        LIMIT 1
                        """
                    ),
                    {"sid": store_id},
                ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1] or f"Store {row[0]}",
                "industry": "Retail",
                "location": "Unknown",
                "lat": 10.8231,
                "lon": 106.6297,
            }
        except Exception:
            logger.error("DB error fetching store details store_id=%s", store_id, exc_info=True)
            return None

    def save_workflow(self, wid, name, data):
        if not self.engine:
            return None
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        try:
            with self.get_conn() as conn:
                row = conn.execute(
                    text(
                        """
                        INSERT INTO workflows (workspace_id, name, json_data)
                        VALUES (:wid, :name, CAST(:payload AS jsonb))
                        RETURNING id
                        """
                    ),
                    {"wid": wid, "name": name, "payload": payload},
                ).fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception:
            logger.error("DB error saving workflow workspace_id=%s name=%s", wid, name, exc_info=True)
            return None
