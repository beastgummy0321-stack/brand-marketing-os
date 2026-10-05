"""Guard router-relative links and the single SPA prefix boundary."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def prefix_literals(source):
    tree = ast.parse(source)
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and (node.value == "/app" or node.value.startswith("/app/"))]


class ActionUrlTargetsTest(unittest.TestCase):
    def test_prefix_is_only_owned_by_web(self):
        offenders = []
        for path in (ROOT / "app").rglob("*.py"):
            if "tests" in path.parts or path == ROOT / "app/shared/web.py":
                continue
            for line in prefix_literals(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(offenders, [])

    def test_detector_finds_literals_and_fstrings(self):
        self.assertEqual(prefix_literals('x = "/app/brands/a"'), [1])
        self.assertEqual(prefix_literals('x = f"/app/brands/{b}"'), [1])
        self.assertEqual(prefix_literals('x = "/app"'), [1])
        self.assertEqual(prefix_literals('x = "/brands/a"'), [])

    def test_builders_separate_router_and_browser_paths(self):
        from app.shared.web import app_path, app_url
        self.assertEqual(app_path("/brands/b/library", tab="customer voice"), "/brands/b/library?tab=customer+voice")
        self.assertEqual(app_url("/"), "/app/")
        self.assertEqual(app_url(app_path("/accept-invite", token="a&b")), "/app/accept-invite?token=a%26b")
        for bad in ("https://example.com", "//example.com", "/app/brands/b", "/app"):
            with self.assertRaises(ValueError):
                app_path(bad)


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
