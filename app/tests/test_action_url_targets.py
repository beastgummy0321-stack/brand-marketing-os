# -*- coding: utf-8 -*-
"""Prevent new interrupt and job action URLs from bypassing the SPA basename."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "app" / "ads",
    ROOT / "app" / "core" / "prototype_phase.py",
    ROOT / "app" / "brand_web" / "routes_library.py",
    ROOT / "app" / "brand_web" / "routes_products.py",
    ROOT / "app" / "intake" / "routes_api.py",
    ROOT / "app" / "intake" / "persona_generation.py",
]


def _action_url_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "action_url":
                    yield keyword.value
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "action_url":
                    yield value


class ActionUrlTargetsTest(unittest.TestCase):
    def test_literal_action_urls_target_the_spa(self):
        offenders = []
        files = []
        for source in SOURCES:
            files.extend(source.rglob("*.py") if source.is_dir() else [source])
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for value in _action_url_nodes(tree):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if value.value.startswith("/") and not value.value.startswith("/app/"):
                        offenders.append(f"{path.relative_to(ROOT)}:{value.lineno}:{value.value}")
                elif isinstance(value, ast.JoinedStr):
                    literal = "".join(
                        part.value for part in value.values
                        if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    )
                    if literal.startswith("/") and not literal.startswith("/app/"):
                        offenders.append(f"{path.relative_to(ROOT)}:{value.lineno}:{literal}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()


class ApiNotFoundShapeTest(unittest.TestCase):
    """/api 底下的 404 一律回 JSON——回 HTML 的話新殼 fetch 會炸在 res.json()。"""

    def test_api_404_is_json_not_html(self):
        from fastapi.testclient import TestClient

        import app.main as main

        client = TestClient(main.app)
        response = client.post("/api/brands/nope/assets", files={"file": ("a.png", b"x", "image/png")})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(set(response.json().keys()), {"detail"})
