"""
src/server.py — Backward-compatibility shim.

The monolith has been refactored into:
  - src/api/main.py          (app factory, lifespan, middleware)
  - src/api/dependencies.py  (RuntimeState, auth, helpers)
  - src/api/routes/chat.py   (POST /chat, GET /api/v1/task/{task_id})
  - src/api/routes/documents.py (POST /upload, POST /ocr)

This file re-exports `app` so that existing `uvicorn src.server:app`
commands and test imports continue to work without modification.
"""

from src.api.main import app  # noqa: F401

__all__ = ["app"]
