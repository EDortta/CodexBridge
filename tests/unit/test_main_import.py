from __future__ import annotations


def test_main_app_imports() -> None:
    from gateway.app.main import app

    assert app.title == "CodexBridge Gateway"
