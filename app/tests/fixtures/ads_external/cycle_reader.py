"""Shared read-only A/B/C/D platform replacement; never writes platform data."""

import os
from datetime import date, timedelta

from app.tests.fixtures.ads_external import runtime as assembly

COPY_V2 = "先了解適合自己的補給方式，再選擇日常所需。"


class CycleReader(assembly.ReadOnlyReader):
    def cold_nodes(self, account):
        today = date.today()
        root = self.node(account, "cold-root", "campaign", objective="購買")
        root.update(
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=7)).isoformat(),
            budget_type="unknown",
            budget_amount=None,
        )
        nodes = [root]
        for role, amount in (("new", 50), ("retarget", 30), ("explore", 20)):
            group = self.node(
                account,
                f"cold-{role}-group",
                "adset",
                parent_native_kind="campaign",
                parent_native_id="cold-root",
            )
            group.update(
                start_date=root["start_date"],
                end_date=root["end_date"],
                budget_type="daily",
                budget_amount=amount,
            )
            ad = self.node(
                account,
                f"cold-{role}-ad",
                "ad",
                parent_native_kind="adset",
                parent_native_id=group["native_id"],
                creative={
                    "kind": "image",
                    "fields": {
                        "title": "探索品牌",
                        "body": "了解更多",
                        "description": "品牌介紹",
                        "image_hash": "fixture-cold-original",
                    },
                },
            )
            nodes.extend([group, ad])
        return nodes

    def read_structure(self, *args, **kwargs):
        if kwargs.get("native_id") == "cold-root":
            from app.ads.adapters.external import SourcePage

            return SourcePage(self.cold_nodes(args[3]))
        return super().read_structure(*args, **kwargs)

    def read_creatives(self, *args, **kwargs):
        if kwargs.get("native_id") == "cold-root":
            from app.ads.adapters.external import SourcePage

            return SourcePage([r for r in self.cold_nodes(args[3]) if r["native_kind"] == "ad"])
        return super().read_creatives(*args, **kwargs)

    def accounts(self, *args):
        rows = super().accounts(*args)
        if os.environ.get("F15_ACCEPTANCE_PHASE") in {"C", "D"}:
            return rows[:1] if self.platform == "meta" else []
        return rows

    def list_existing(self, *args, **kwargs):
        page = super().list_existing(*args, **kwargs)
        if os.environ.get("F15_ACCEPTANCE_PHASE") in {"C", "D"}:
            page.cursor = None
        return page

    def node(self, account, native_id, kind, **fields):
        if os.environ.get("F15_ACCEPTANCE_PHASE") in {"C", "D"}:
            today = date.today()
            fields.update(
                currency="TWD",
                start_date=today.replace(day=1).isoformat(),
                end_date=(today + timedelta(days=10)).isoformat(),
            )
            fields.update(
                budget_type="daily" if kind == "campaign" else "unknown",
                budget_amount=100 if kind == "campaign" else None,
            )
        return super().node(account, native_id, kind, **{"native_status": "ACTIVE", **fields})

    def creative(self):
        value = super().creative()
        revision = self.state()["creative_revision"]
        value["fields"]["body"] = (
            "平台原始文案" if revision == 1 else COPY_V2 if revision == 2 else "平台外部另改的文案"
        )
        if revision == 4:
            value["fields"].update(title="探索品牌", body="了解更多")
        return value

    def read_observations(self, conn, org, brand, account, *, native_id, start, end, **kwargs):
        if native_id == "cold-root":
            from app.ads.adapters.external import SourcePage

            return SourcePage([])
        if os.environ.get("F15_ACCEPTANCE_PHASE") not in {"B", "C", "D"}:
            return super().read_observations(
                conn, org, brand, account, native_id=native_id, start=start, end=end, **kwargs
            )
        from app.ads.adapters.external import SourcePage

        first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        rows = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            later = day >= date.today() - timedelta(days=7)
            rows.append(
                {
                    "native_kind": self.kinds()[2],
                    "native_id": f"{native_id}-ad",
                    "day": day.isoformat(),
                    "metric_scope": self.kinds()[2],
                    "attribution_key": "fixture_7d_click",
                    "currency": "TWD",
                    "spend": 100,
                    "impressions": 2000 if later else 1000,
                    "clicks": 80 if later else 30,
                    "purchases": 6 if later else 3,
                    "revenue": 600 if later else 300,
                    "source": "fixture",
                }
            )
        return SourcePage(rows)

    def read_monthly(self, conn, org, brand, account, *, start, end, **kwargs):
        page = super().read_monthly(conn, org, brand, account, start=start, end=end, **kwargs)
        if os.environ.get("F15_ACCEPTANCE_PHASE") not in {"B", "C", "D"}:
            return page
        first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        page.items = [
            {
                "native_kind": self.kinds()[0],
                "native_id": "root",
                "day": (first + timedelta(days=i)).isoformat(),
                "metric_scope": self.kinds()[0],
                "attribution_key": "account_monthly_spend",
                "currency": "TWD",
                "spend": 100,
                "source": "fixture",
            }
            for i in range((last - first).days + 1)
        ]
        return page

    def verify_native(self, *args, **kwargs):
        if self.state().get("fail_next"):
            raise ValueError("隔離替身暫時無法讀回。")
        if kwargs.get("native_id", "").startswith("cold-"):
            nodes = self.cold_nodes(args[3])
            node = next(r for r in nodes if r["native_id"] == kwargs["native_id"])
            parents = []
            current = node
            while current.get("parent_native_id"):
                current = next(r for r in nodes if r["native_id"] == current["parent_native_id"])
                parents.append(current)
            return {
                "entity": node,
                "parents": parents,
                "timezone_name": "Asia/Taipei",
                "media_equivalence": None,
                "continuous_intervals": [],
            }
        if os.environ.get("F15_ACCEPTANCE_PHASE") in {"C", "D"} and kwargs.get("native_id") == "B2":
            account = args[3]
            return {
                "entity": self.node(
                    account,
                    "B2",
                    "ad",
                    parent_native_kind="adset",
                    parent_native_id="root-group",
                    creative={
                        "kind": "image",
                        "fields": {
                            "title": "探索品牌",
                            "body": "了解更多",
                            "description": "品牌介紹",
                            "image_hash": "fixture-new-picture",
                        },
                    },
                ),
                "parents": [
                    self.node(
                        account,
                        "root-group",
                        "adset",
                        parent_native_kind="campaign",
                        parent_native_id="root",
                    ),
                    self.node(account, "root", "campaign"),
                ],
                "timezone_name": "Asia/Taipei",
                "media_equivalence": None,
                "continuous_intervals": [],
            }
        return super().verify_native(*args, **kwargs)
