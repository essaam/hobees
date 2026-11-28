"""hobees Web Application (Phase 7).

Serves the Workbench, Studio and Trace Explorer SPA via FastAPI.
Zero-Node runtime: static assets are bundled inside the Python wheel.
"""

from __future__ import annotations

from .app import create_web_app

__all__ = ["create_web_app"]