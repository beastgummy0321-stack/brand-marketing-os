"""app/tests/test_identity_tenant_routes.py — 票 03-1 done-check 2 / 03-1 r1 §5：跨租戶隔離的
「路由表證明」。逐一走過 `app.routes` 裡每一條帶任何 `{...}` 路徑參數的路由：

- 路徑含 `{brand_id}` 的，用組織 A 的有效 token 打組織 B 的真品牌 id，斷言一律 404
  （GET／POST 都帶最小 body）。
- 路徑不含 `{brand_id}` 但仍有其他 `{...}` 參數的（例如 `/api/interrupts/{interrupt_id}/resolve`
  這種租戶界線不是靠 brand_id 守的路由），填一個不存在的 id，一樣斷言 404——這條分支就是
  票 03-1 r1 defect 1（`POST /api/interrupts/{id}/resolve` 沒查 org_id）會被抓到的地方：
  原本的 sweep 只看 `{brand_id}`，這種路由完全沒被走到。

不是手寫路由清單，新增路由自動被本測試看到。

真的沒辦法用「填 id、其餘參數填 x、body 填 {}」這個泛用打法打通的路由，才准列進 `SKIP`
（逃生門，同 done-check 2 原文：上限 5 條，每條要寫理由）。
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

# 泛用填值試這三組（依序），只要有一組讓這條路由真的走到租戶／存在性檢查（不是被
# int／UUID 型別的路徑參數擋在半路 422），就算通過——避免逐一列舉型別例外。第三組是
# 合法格式的 UUID 字面值，服務 `{user_id}` 這種宣告成 `UUID` 型別的路徑參數（同
# test_identity_auth.py 的 sweep 作法）。
_FILLER_CANDIDATES = ("x", "1", "00000000-0000-0000-0000-000000000099")

# (path, method) -> 為什麼泛用打法打不通這一條。上限 5（done-check 2 原文，03-1 r1 §5 沿用
# 同一個逃生門、不另開新的 5 條額度）。
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

    def _try_fillers(self, path_template: str, method: str, *, brand_scoped: bool):
        """回傳 (passed, attempts)：passed=True 代表至少一組填值讓這條路由回 404。"""
        attempts = []
        for filler in _FILLER_CANDIDATES:
            path = path_template
            if brand_scoped:
                path = path.replace("{brand_id}", self.brand_b)
            path = _PATH_PARAM.sub(filler, path)
            kwargs = {"headers": {"Authorization": f"Bearer {self.a_token}"}}
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                kwargs["json"] = {}
            response = self.client.request(method, path, **kwargs)
            if response.status_code == 404:
                return True, attempts
            attempts.append((path, response.status_code, response.text[:120]))
        return False, attempts

    def test_every_path_param_route_404s_for_wrong_tenant_or_nonexistent_id(self):
        """票 03-1 done-check 2 ＋ 03-1 r1 §5：sweep 涵蓋範圍從「只看 `{brand_id}`」
        擴大到「任何 `{...}` 路徑參數」。"""
        routes = flatten_routes(main.app)
        failures = []
        checked = 0
        checked_non_brand = 0
        skip_used = set()
        for route in routes:
            path_template = route.path
            if not _PATH_PARAM.search(path_template):
                continue
            brand_scoped = "{brand_id}" in path_template
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue
                key = (path_template, method)
                if key in SKIP:
                    skip_used.add(key)
                    continue
                checked += 1
                if not brand_scoped:
                    checked_non_brand += 1
                passed, attempts = self._try_fillers(
                    path_template, method, brand_scoped=brand_scoped
                )
                if not passed:
                    failures.append(f"{method} {path_template} -> {attempts}")
        # 03-1 r1 §5：門檻原本 200（沿用既有 brand_id sweep 的規模）。外殼切片
        # （2026-08-28）刪掉 `app/ads/` 後帶路徑參數的路由從 250 降到 90，門檻下修到 80
        # （保留一成餘裕）——這個數字守的是「註冊迴圈壞掉」，不是「路由只能增加」。另外直接斷言
        # 「有 route 是走非 brand_id 分支」——這才是真的驗到擴大範圍生效，而不是單純
        # 依賴一個總數門檻（總數門檻對「擴大範圍那段程式碼被誤刪」不敏感，因為
        # brand_id 路由本身數量就遠超過舊門檻）。
        self.assertGreater(
            checked, 80, "path-param route sweep looks too small; registration broken?"
        )
        self.assertGreaterEqual(
            checked_non_brand, 1,
            "sweep 沒有掃到任何非 brand_id 的 {...} 路由——03-1 r1 §5 擴大範圍失效了",
        )
        self.assertLessEqual(len(SKIP), 5, "太多 route 進了逃生門，回頭修 sweep 本身或補上租戶檢查")
        stale_skips = set(SKIP) - skip_used
        self.assertEqual(stale_skips, set(), f"逃生門清單裡這些已經用不到了，清掉：{stale_skips}")
        self.assertEqual(
            failures, [],
            f"以下 {len(failures)} 條路由沒有在跨組織／不存在的 id 時回 404"
            f"（票 03-1 done-check 2、03-1 r1 §5）：\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
