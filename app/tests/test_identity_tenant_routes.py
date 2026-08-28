"""app/tests/test_identity_tenant_routes.py — 票 03-1 done-check 2：跨租戶隔離的
「路由表證明」。逐一走過 `app.routes` 裡每一條路徑含 `{brand_id}` 的路由，用組織 A 的
有效 token 打組織 B 的品牌，斷言一律 404（GET／POST 都帶最小 body）——不是手寫路由清單，
新增路由自動被本測試看到。

真的沒辦法用「填 brand_id、其餘參數填 x、body 填 {}」這個泛用打法打通的路由，才准列進
`SKIP`（逃生門，同 done-check 2 原文：上限 5 條，每條要寫理由）。
"""

import re
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo

from .identity_test_helpers import flatten_routes, mint_hs256

_PATH_PARAM = re.compile(r"\{[^}]+\}")

# 泛用填值試這兩組（依序），只要有一組讓這條路由真的走到 require_brand()（不是被
# int／UUID 型別的路徑參數擋在半路 422），就算通過——避免逐一列舉型別例外。
_FILLER_CANDIDATES = ("x", "1")

# (path, method) -> 為什麼泛用打法打不通這一條。上限 5（done-check 2 原文）。
SKIP: dict[tuple[str, str], str] = {
    ("/api/brands/{brand_id}/assets", "POST"):
        "multipart 檔案上傳（File(...)），這個 sweep 只送 JSON；route 內已有 require_brand",
    ("/api/brands/{brand_id}/orders/import", "POST"):
        "multipart 檔案上傳（File(...)），這個 sweep 只送 JSON；route 內已有 require_brand",
}


class RouteTableTenantTest(unittest.TestCase):
    def setUp(self):
        # 不能放 setUpClass：conftest.py 的連線綁定（`_bound_connection`）是 function 級
        # autouse fixture，setUpClass 執行時還沒有連線可用。
        self.client = TestClient(main.app)

        a_user = uuid4()
        self.a_token = mint_hs256(sub=str(a_user), email=f"orga-{a_user.hex[:8]}@example.com")
        me_a = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {self.a_token}"}
        )
        self.org_a = me_a.json()["org"]["id"]

        b_user = uuid4()
        b_token = mint_hs256(sub=str(b_user), email=f"orgb-{b_user.hex[:8]}@example.com")
        me_b = self.client.get("/api/identity/me", headers={"Authorization": f"Bearer {b_token}"})
        self.org_b = me_b.json()["org"]["id"]
        self.brand_b = bi_repo.create_brand(
            web.conn, org_id=self.org_b, name="組織B的品牌", client_name=None, actor="測試"
        )["id"]
        web.conn.commit()

    def test_every_brand_scoped_route_404s_for_a_wrong_org_token(self):
        routes = flatten_routes(main.app)
        failures = []
        checked = 0
        skip_used = set()
        for route in routes:
            path_template = route.path
            if "{brand_id}" not in path_template:
                continue
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue
                key = (path_template, method)
                if key in SKIP:
                    skip_used.add(key)
                    continue
                checked += 1
                passed = False
                attempts = []
                for filler in _FILLER_CANDIDATES:
                    path = path_template.replace("{brand_id}", self.brand_b)
                    path = _PATH_PARAM.sub(filler, path)
                    kwargs = {"headers": {"Authorization": f"Bearer {self.a_token}"}}
                    if method in ("POST", "PUT", "PATCH", "DELETE"):
                        kwargs["json"] = {}
                    response = self.client.request(method, path, **kwargs)
                    if response.status_code == 404:
                        passed = True
                        break
                    attempts.append((path, response.status_code, response.text[:120]))
                if not passed:
                    failures.append(f"{method} {path_template} -> {attempts}")
        self.assertGreater(
            checked, 100, "brand_id route sweep looks too small; registration broken?"
        )
        self.assertLessEqual(len(SKIP), 5, "太多 route 進了逃生門，回頭修 sweep 本身或補上租戶檢查")
        stale_skips = set(SKIP) - skip_used
        self.assertEqual(stale_skips, set(), f"逃生門清單裡這些已經用不到了，清掉：{stale_skips}")
        self.assertEqual(
            failures, [],
            f"以下 {len(failures)} 條 brand_id 路由沒有在跨組織時回 404（票 03-1 done-check 2）：\n"
            + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
