"""app/tests/test_identity_auth.py — 票 03-1 done-check 1：JWT／dev token 驗證路徑。

conftest.py 的 `TestClient` 已經 monkeypatch 成預設帶 dev token 的 Authorization header
（`IDENTITY_DEV_TOKEN`），本檔大多數測試需要「沒有 token」或「別的 token」，所以逐一
自己覆寫 `headers`，不依賴那個預設值。
"""

import os
import re
import threading
import unittest
from pathlib import Path
from unittest import mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.core import config
from app.identity import repository as identity_repo

from .identity_test_helpers import flatten_routes, mint_hs256

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

# 通用 sweep 送不出「符合形狀」的 body 時，各自補一份最小合法 body（Pydantic 型別
# route 專用）。
_MINIMAL_BODIES = {
    ("/api/identity/orgs/current/rename", "POST"): {"name": "x"},
    ("/api/identity/invites", "POST"): {"email": "x@x.com", "role": "member"},
    ("/api/meta/token", "POST"): {"token": "x"},  # 票 04
}

# route 真的沒辦法用泛用打法打通、又不是本票要驗的行為，才准列在這裡（同票 03-1
# done-check 2「route-table tenant test」的逃生門精神）：
# - 設定頁一族（/api/settings*、meta-mcp）：全站設定目前仍是全域（未分組織）作用域，
#   identity-inventory.md「Migration note（slice ④）」明文記錄這批要等設定頁改分組織
#   的後續票才會補登入要求，不是本票 03-1 的遺漏。
# - 檔案上傳三條：body 是 multipart/form-data（`File(...)`），這個 sweep 只送 JSON，
#   422 是「body 形狀不對」不是「沒驗證登入」——這三條路由原始碼裡都已經有
#   `require_actor(request)`，讀原始碼可以核對，不是安全缺口。
# - handoff/{provider}：provider 名稱檢查（僅收 claude／chatgpt）寫在 require_actor()
#   之前，用假的 provider 名稱會先 404；真正的 provider 值仍然會先驗證登入，不可被
#   利用來繞過租戶界線（require_brand 檢查在 provider 合法時一定會跑到）。
_SWEEP_SKIP: dict[tuple[str, str], str] = {
    ("/api/settings", "GET"): "設定頁全域作用域，slice ④ 才分組織（identity-inventory.md）",
    ("/api/settings/api-key/clear-db", "POST"): "同上，設定頁全域作用域",
    ("/api/settings/test-connection", "POST"): "同上，測試連線不落地資料",
    ("/api/brands/{brand_id}/assets", "POST"): "multipart 檔案上傳，route 內已有 require_actor",
    ("/api/intake/photos", "POST"): "multipart 檔案上傳，route 內已有 require_actor",
    ("/api/brands/{brand_id}/orders/import", "POST"):
        "multipart 檔案上傳，route 內已有 require_actor",
    ("/api/intake/brands/{brand_id}/handoff/{provider}", "GET"):
        "provider 名稱檢查在 require_actor() 之前，合法 provider 值仍會驗證登入",
}

_PATH_PARAM = re.compile(r"\{[^}]+\}")

# 泛用填值試這三組（依序），只要有一組讓這條路由真的走到 handler（不是被型別驗證
# 擋在半路），就算 sweep 通過——避免要為每個 int／UUID 型別的路徑參數各寫一條例外。
_FILLER_CANDIDATES = ("x", "1", "00000000-0000-0000-0000-000000000099")


def _filled_paths(template: str) -> list:
    return [_PATH_PARAM.sub(filler, template) for filler in _FILLER_CANDIDATES]


class NoAuthorizationSweepTest(unittest.TestCase):
    """done-check 1 前半：沒帶 Authorization 的 /api/* 一律 401 信封，除了 health。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.client.headers.pop("Authorization", None)

    def test_health_does_not_require_auth(self):
        response = self.client.get("/api/identity/health")
        self.assertEqual(response.status_code, 200)

    def test_every_other_api_route_401s_without_authorization(self):
        routes = flatten_routes(main.app)
        failures = []
        checked = 0
        skip_used = set()
        for route in routes:
            path = route.path
            if not path.startswith("/api/") or path == "/api/identity/health":
                continue
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue
                key = (path, method)
                if key in _SWEEP_SKIP:
                    skip_used.add(key)
                    continue
                body = _MINIMAL_BODIES.get(key, {})
                checked += 1
                passed = False
                attempts = []
                for filled in _filled_paths(path):
                    response = self.client.request(method, filled, json=body)
                    if response.status_code == 401 and set(response.json()) == {"error"}:
                        passed = True  # 有一組填值真的走到 401 信封，這條算過
                        break
                    attempts.append((filled, response.status_code))
                if not passed:
                    failures.append(f"{method} {path} -> {attempts} (body={body})")
        # 外殼切片（2026-08-28）：`app/ads/` 刪掉後路由總數從 130 降到 99，門檻跟著下修
        # 到 90（保留一成餘裕）。這個數字守的是「註冊迴圈壞掉、整批路由沒掛上」，不是
        # 「路由只能增加」；程式碼真的縮小時要跟著改，否則它永遠紅。
        self.assertGreater(checked, 90, "route sweep looks too small; registration broken?")
        stale_skips = set(_SWEEP_SKIP) - skip_used
        self.assertEqual(stale_skips, set(), f"逃生門清單裡這些已經用不到了，清掉：{stale_skips}")
        self.assertEqual(failures, [], "以下 route 沒有在缺 Authorization 時回 401 信封：\n"
                          + "\n".join(failures))


class TokenVerificationTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _me(self, token: str | None):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["Authorization"] = ""
        return self.client.get("/api/identity/me", headers=headers)

    def test_expired_token_is_401(self):
        token = mint_hs256(exp_delta=-10)
        response = self._me(token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(set(response.json()), {"error"})

    def test_wrong_signature_is_401(self):
        token = mint_hs256(secret="totally-the-wrong-secret-but-still-long-enough")
        response = self._me(token)
        self.assertEqual(response.status_code, 401)

    def test_garbage_token_is_401(self):
        response = self._me("not-a-jwt-at-all")
        self.assertEqual(response.status_code, 401)

    def test_valid_token_unknown_user_auto_creates_personal_org(self):
        user_id = uuid4()
        email = f"newuser-{user_id.hex[:8]}@example.com"
        token = mint_hs256(sub=str(user_id), email=email)
        response = self._me(token)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["user"]["id"], str(user_id))
        self.assertEqual(body["user"]["email"], email)
        self.assertEqual(body["org"]["kind"], "personal")
        self.assertEqual(body["org"]["role"], "owner")
        self.assertEqual(len(body["orgs"]), 1)
        # 冪等：第二次用同一個 sub 打，不會重複建人／重複建組織
        response2 = self._me(token)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["org"]["id"], body["org"]["id"])

    def test_dev_token_maps_to_seed_dev_user_in_org_dev(self):
        response = self.client.get(
            "/api/identity/me", headers={"Authorization": "Bearer test-dev-token"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["user"]["id"], str(_DEV_USER_ID))
        self.assertEqual(body["org"]["id"], "org_dev")
        self.assertEqual(body["org"]["role"], "owner")

    def test_x_org_id_of_org_user_is_not_in_is_403(self):
        user_id = uuid4()
        token = mint_hs256(sub=str(user_id), email=f"iso-{user_id.hex[:8]}@example.com")
        # 先觸發一次首登（建個人組織），再用一個確定不是他的組織 id 打
        self._me(token)
        response = self.client.get(
            "/api/identity/me",
            headers={"Authorization": f"Bearer {token}", "X-Org-Id": "org_dev"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden_org")

    def test_user_removed_from_org_then_403(self):
        user_id = uuid4()
        email = f"removed-{user_id.hex[:8]}@example.com"
        token = mint_hs256(sub=str(user_id), email=email)
        first = self._me(token)
        org_id = first.json()["org"]["id"]
        # 直接動資料庫模擬「被踢出組織」（membership 被刪）
        identity_repo.remove_membership(web.conn, org_id, user_id)
        web.conn.commit()
        response = self.client.get(
            "/api/identity/me",
            headers={"Authorization": f"Bearer {token}", "X-Org-Id": org_id},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden_org")


class ConcurrentFirstLoginTest(unittest.TestCase):
    """票 03-1 r1 defect 3：先查後插的競態。用 barrier 逼真兩個 thread 幾乎同時打
    `POST`/`GET`（這裡用 `/api/identity/me`）——`starlette.testclient` 每次呼叫各開
    一個獨立 portal（背景 event loop thread），兩個真正的 python thread 各自送一個
    request 真的會平行跑到 `app.identity.repository.create_user`，barrier 逼兩邊
    同時卡在那個呼叫點，模擬「兩個 request 幾乎同時抵達」的最壞情況。"""

    def setUp(self):
        # raise_server_exceptions=False: TestClient 預設把 500 也重新 raise 到呼叫端
        # （方便單一同步請求的測試直接看到堆疊），但這裡兩個 request 各自跑在自己的
        # portal thread 裡，raise 出來的例外會變成背景 thread 自己吃掉、main thread
        # 完全看不到（pytest 只會印一條 warning，斷言照樣「通過」）——關掉這個旗標，
        # 500 老實變成一個平常的 response，才能在 main thread 用 assertEqual 斷言。
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_two_concurrent_logins_same_sub_yield_one_user_one_org(self):
        user_id = uuid4()
        email = f"race-{user_id.hex[:8]}@example.com"
        token = mint_hs256(sub=str(user_id), email=email)

        barrier = threading.Barrier(2, timeout=5)
        original_create_user = identity_repo.create_user

        def synced_create_user(conn, uid, em):
            barrier.wait()
            return original_create_user(conn, uid, em)

        responses = {}

        def worker(key):
            responses[key] = self.client.get(
                "/api/identity/me", headers={"Authorization": f"Bearer {token}"}
            )

        with mock.patch("app.identity.repository.create_user", side_effect=synced_create_user):
            threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        for key, resp in responses.items():
            self.assertEqual(resp.status_code, 200, f"thread {key}: {resp.text}")

        n_users = web.conn.execute(
            "SELECT count(*) AS n FROM app_user WHERE id = %s", (str(user_id),)
        ).fetchone()["n"]
        n_memberships = web.conn.execute(
            "SELECT count(*) AS n FROM membership WHERE user_id = %s", (str(user_id),)
        ).fetchone()["n"]
        n_personal_orgs = web.conn.execute(
            "SELECT count(*) AS n FROM organisation o JOIN membership m ON m.org_id = o.id"
            " WHERE m.user_id = %s AND o.kind = 'personal'", (str(user_id),)
        ).fetchone()["n"]
        self.assertEqual(n_users, 1, "app_user 應該只有一列")
        self.assertEqual(n_memberships, 1, "membership 應該只有一列")
        self.assertEqual(n_personal_orgs, 1, "個人組織應該只有一個")


class Hs256StartupGuardTest(unittest.TestCase):
    """票 02-env-flag-and-settings done-check 6：兩半都要證——`app.core.config.settings()`
    真的會在非本機 + HS256 開著時炸掉（ADR 0062：這道檢查原本住在 `register()`，這張票
    搬進 settings() 的開機檢查——跑進閘門的東西），`.env.example` 出廠真的沒有把後門打開
    （擋回歸的模板）。單一測試同時證兩件事，不多開第二支。"""

    def test_settings_refuses_non_local_hs256_and_env_example_ships_it_closed(self):
        with mock.patch.dict(
            os.environ,
            {
                "BRAND_OS_ENV": "production",
                "IDENTITY_ALLOW_HS256": "1",
                "IDENTITY_DEV_TOKEN": "",  # 只想測 HS256 這一半，先關掉 dev-token 那一半的檢查
            },
        ):
            with self.assertRaises(RuntimeError):
                config.settings()

        env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn(
            "\nIDENTITY_ALLOW_HS256=1", env_example, ".env.example 出廠不該打開 HS256 後門",
        )
        self.assertNotIn(
            "super-secret-jwt-token-with-at-least-32-characters-long", env_example,
            ".env.example 出廠不該帶 Supabase 本機示範密鑰",
        )
        self.assertNotIn(
            "\nBRAND_OS_ENV=local", env_example,
            ".env.example 出廠不該把 BRAND_OS_ENV 設成 local——這個範本檔會被複製到雲端",
        )


class BootCheckReportsAllViolationsTest(unittest.TestCase):
    """票 02-env-flag-and-settings done-check 3／ADR 0062「一次列出全部違規，不是抓到
    第一條就停」——這是舊版兩段各自獨立的 RuntimeError 拿掉之後，唯一沒有既有測試覆蓋
    的行為，也是最容易被後續「簡化」悄悄弄丟的地方。三種違規（兩個必填缺漏＋一個禁止
    後門有值）混在一起餵，斷言三個變數名同時出現在同一個 RuntimeError 訊息裡——只抓到
    第一條的話，這裡會斷在少了另外兩個。"""

    def test_three_violations_all_named_in_one_message(self):
        with mock.patch.dict(
            os.environ,
            {
                "BRAND_OS_ENV": "production",
                "DATABASE_URL": "",
                "SUPABASE_URL": "",
                "IDENTITY_DEV_TOKEN": "x",
            },
        ):
            with self.assertRaises(RuntimeError) as cm:
                config.settings()
        message = str(cm.exception)
        self.assertIn("DATABASE_URL", message)
        self.assertIn("SUPABASE_URL", message)
        self.assertIn("IDENTITY_DEV_TOKEN", message)


class CodexCliProviderIsLocalOnlyTest(unittest.TestCase):
    """`BRAND_OS_LLM_PROVIDER=codex_cli` 指的是本機那支 codex CLI（ADR 0032），雲端主機上
    沒有這支程式，設下去每一次 AI 呼叫都會安靜失敗。禁的是**這一個值**，不是這個變數——
    所以兩半都要證：codex_cli 在 production 會炸，別的供應商值不會被誤傷。"""

    def test_codex_cli_forbidden_outside_local_but_other_providers_pass(self):
        base = {
            "BRAND_OS_ENV": "production",
            "DATABASE_URL": "postgresql://x/y",
            "SUPABASE_URL": "https://x",
            "SUPABASE_SERVICE_ROLE_KEY": "k",
            "IDENTITY_DEV_TOKEN": "",
            "IDENTITY_ALLOW_HS256": "",
            "BRAND_OS_TODAY": "",
        }
        with mock.patch.dict(os.environ, {**base, "BRAND_OS_LLM_PROVIDER": "codex_cli"}):
            config.settings.cache_clear()
            with self.assertRaises(RuntimeError) as cm:
                config.settings()
        self.assertIn("BRAND_OS_LLM_PROVIDER", str(cm.exception))

        with mock.patch.dict(os.environ, {**base, "BRAND_OS_LLM_PROVIDER": "anthropic"}):
            config.settings.cache_clear()
            self.assertEqual(config.settings().brand_os_llm_provider, "anthropic")


if __name__ == "__main__":
    unittest.main()
