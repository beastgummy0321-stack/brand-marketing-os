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


def invalid_action_urls(source):
    """Check statically known prefixes; computed values are covered at producer boundaries."""
    tree = ast.parse(source)
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            values.extend(k.value for k in node.keywords if k.arg == "action_url")
        elif isinstance(node, ast.Dict):
            values.extend(value for key, value in zip(node.keys, node.values)
                          if isinstance(key, ast.Constant) and key.value == "action_url")
    bad = []
    for value in values:
        prefix = None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            prefix = value.value
        elif isinstance(value, ast.JoinedStr) and value.values:
            first = value.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                prefix = first.value
        if prefix is not None and (not prefix.startswith("/") or prefix.startswith("//")
                                   or prefix == "/app" or prefix.startswith("/app/")):
            bad.append(value.lineno)
    return bad


class ActionUrlTargetsTest(unittest.TestCase):
    def test_prefix_is_only_owned_by_web(self):
        offenders = []
        for path in (ROOT / "app").rglob("*.py"):
            if "tests" in path.parts or path == ROOT / "app/shared/web.py":
                continue
            source = path.read_text(encoding="utf-8")
            for line in prefix_literals(source) + invalid_action_urls(source):
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertEqual(offenders, [])

    def test_detector_finds_literals_and_fstrings(self):
        self.assertEqual(prefix_literals('x = "/app/brands/a"'), [1])
        self.assertEqual(prefix_literals('x = f"/app/brands/{b}"'), [1])
        self.assertEqual(prefix_literals('x = "/app"'), [1])
        self.assertEqual(prefix_literals('x = "/brands/a"'), [])

    def test_action_urls_reject_non_router_prefixes(self):
        for value in ('"brands/b/library"', '"https://example.com"', '"//example.com"',
                      'f"brands/{b}/library"', 'f"https://{host}"', '"/app/brands/b"'):
            self.assertEqual(invalid_action_urls(f"send(action_url={value})"), [1])
            self.assertEqual(invalid_action_urls(f'row = {{"action_url": {value}}}'), [1])
        for value in ('"/brands/b/library"', 'f"/brands/{b}/library"', 'None', 'path'):
            self.assertEqual(invalid_action_urls(f"send(action_url={value})"), [])

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
