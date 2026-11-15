from __future__ import annotations

import ast
from pathlib import Path

import video_caster.core.api as api

SOURCE = ast.parse(Path(api.__file__).read_text())


def _engine_uses() -> list[ast.Attribute]:
    return [
        node for node in ast.walk(SOURCE)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "engine"
    ]


def test_api_only_calls_engine_methods():
    called = {
        id(node.func) for node in ast.walk(SOURCE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    reached_past = sorted({use.attr for use in _engine_uses() if id(use) not in called})
    assert reached_past == []


def test_api_imports_no_device_library():
    imported = {
        alias.name for node in ast.walk(SOURCE) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in ast.walk(SOURCE) if isinstance(node, ast.ImportFrom)}
    assert not [name for name in imported if name.split(".")[0] in {"pychromecast", "pyatv", "async_upnp_client"}]
