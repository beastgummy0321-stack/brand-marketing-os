"""Test-only source/provider/queue assembly for the isolated F13 runtime."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

FIXTURE = json.loads(Path(__file__).with_suffix(".json").read_text("utf-8"))


def read_json(path):
    return json.loads(Path(path).read_text("utf-8"))


def write_json(path, value):
    target = Path(path)
    temporary = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


class ReadOnlyReader:
    """Fixture source with two accounts, pages and a non-Meta native vocabulary."""

    def __init__(self, context, platform):
        self.context, self.platform = context, platform

    def state(self):
        return read_json(self.context["state_file"])

    def accounts(self, conn, org, brand):
        if org != self.context["org_id"] or brand not in self.context["brand_ids"]:
            return []
        return [
            {
                "account_id": a,
                "name": f"測試帳號 {i + 1}",
                "currency": "TWD",
                "timezone_name": "Asia/Taipei",
            }
            for i, a in enumerate(FIXTURE["accounts"])
        ]

    def node(self, account, native_id, kind, **fields):
        return {
            "platform": self.platform,
            "source_account": account["account_id"],
            "native_id": native_id,
            "native_kind": kind,
            "native_label": {
                "campaign": "活動",
                "adset": "廣告組",
                "ad": "廣告",
                "portfolio": "組合",
                "line": "項目",
                "unit": "內容",
            }[kind],
            "name": FIXTURE["campaign_name"]
            if kind in {"campaign", "portfolio"}
            else f"測試{kind}",
            "native_status": "PAUSED",
            **fields,
        }

    def kinds(self):
        return (
            ("campaign", "adset", "ad")
            if self.platform == "meta"
            else ("portfolio", "line", "unit")
        )

    def list_existing(self, conn, org, brand, account, *, cursor=None, **kwargs):
        from app.ads.adapters.external import SourcePage, SourceReadError

        state = self.state()
        if cursor and state.get("fail_next"):
            raise SourceReadError("測試來源分頁暫時不可用。", "temporary")
        native = "second" if cursor else "root"
        return SourcePage(
            [
                self.node(
                    account,
                    native,
                    self.kinds()[0],
                    budget_type="lifetime",
                    budget_amount=None,
                    budget_raw={"lifetime_budget": "500000"},
                    currency="TWD",
                )
            ],
            None if cursor else {"after": "page2"},
        )

    def read_structure(self, conn, org, brand, account, *, native_id, **kwargs):
        from app.ads.adapters.external import SourcePage

        root, middle, leaf = self.kinds()
        return SourcePage(
            [
                self.node(account, native_id, root),
                self.node(
                    account,
                    f"{native_id}-group",
                    middle,
                    parent_native_kind=root,
                    parent_native_id=native_id,
                ),
                self.node(
                    account,
                    f"{native_id}-ad",
                    leaf,
                    parent_native_kind=middle,
                    parent_native_id=f"{native_id}-group",
                ),
            ]
        )

    def creative(self):
        return {
            "kind": "image",
            "fields": {
                "id": f"creative-{self.state()['creative_revision']}",
                "title": "平台原始標題",
                "body": "平台原始文案",
                "image_hash": "meta-hash-is-not-sha256",
            },
            "video_original": None,
            "video_original_availability": "unavailable",
        }

    def read_creatives(self, conn, org, brand, account, *, native_id, **kwargs):
        from app.ads.adapters.external import SourcePage

        return SourcePage(
            [self.node(account, f"{native_id}-ad", self.kinds()[2], creative=self.creative())]
        )

    def read_observations(self, conn, org, brand, account, *, native_id, start, end, **kwargs):
        from app.ads.adapters.external import SourcePage

        return SourcePage(
            [
                {
                    "native_kind": self.kinds()[2],
                    "native_id": f"{native_id}-ad",
                    "day": str(end),
                    "metric_scope": self.kinds()[2],
                    "attribution_key": "fixture_7d_click",
                    "currency": "TWD",
                    "spend": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "purchases": None,
                    "revenue": None,
                    "source": "fixture",
                }
            ]
        )

    def binding_kinds(self):
        return (self.kinds()[2],)

    def verify_native(
        self, conn, org, brand, account, *, native_kind, native_id, root_kind, root_id, original
    ):
        root, middle, leaf = self.kinds()
        if (native_kind, native_id, root_kind) != (leaf, f"{root_id}-ad", root):
            raise ValueError("測試來源的指定廣告與父鏈不符。")
        return {
            "entity": self.node(
                account,
                native_id,
                leaf,
                parent_native_kind=middle,
                parent_native_id=f"{root_id}-group",
                creative=self.creative(),
            ),
            "parents": [
                self.node(
                    account,
                    f"{root_id}-group",
                    middle,
                    parent_native_kind=root,
                    parent_native_id=root_id,
                ),
                self.node(account, root_id, root),
            ],
            "timezone_name": "Asia/Taipei",
            "media_equivalence": None,
            "continuous_intervals": [],
        }


def install_assembly(context):
    import httpx
    import pytest  # noqa: F401 -- main skips root dotenv only in test processes

    from app import background
    from app.ads import asset_suggestions, channels, external_sync, user_assets
    from app.llm import providers

    state_lock = threading.Lock()
    stats = {"handlers": {}, "provider_calls": 0, "errors": [], "blocked_external": 0}
    original_send = httpx.Client.send
    original_async_send = httpx.AsyncClient.send

    def guard(request):
        if request.url.host not in {"localhost", "127.0.0.1", "::1"}:
            stats["blocked_external"] += 1
            raise RuntimeError("F13 blocks every non-local transport, including platform writes")

    def send(client, request, *args, **kwargs):
        guard(request)
        return original_send(client, request, *args, **kwargs)

    async def async_send(client, request, *args, **kwargs):
        guard(request)
        return await original_async_send(client, request, *args, **kwargs)

    httpx.Client.send = send
    httpx.AsyncClient.send = async_send
    readers = {name: ReadOnlyReader(context, name) for name in ("meta", "fixture_third")}
    channels.CHANNELS = [
        {"key": "meta", "label": "Meta（測試唯讀來源）"},
        {"key": "fixture_third", "label": "第三種原生結構（測試）"},
    ]
    channels.external_reader = lambda platform: readers.get(platform)

    class SuggestionProvider:
        name = "codex_cli"

        def complete(self, *, messages, **kwargs):
            stats["provider_calls"] += 1
            payload = json.loads(messages[0]["content"])
            reply = {
                "items": [
                    {
                        "id": p["id"],
                        "copy_fields": FIXTURE["neutral_additions"],
                        "purpose": "品牌介紹",
                    }
                    for p in payload["placements"]
                ]
            }
            return providers.ProviderResponse(
                output_text=json.dumps(reply, ensure_ascii=False),
                structured=None,
                usage=providers.Usage(input_tokens=0, output_tokens=0),
                stop_reason="end_turn",
            )

    def select(provider, task_type=None):
        if task_type == asset_suggestions.TASK_TYPE:
            return SuggestionProvider()
        if task_type == "ads_brief_parse":
            return providers.ScriptedProvider(providers.SCRIPTED_REPLIES[task_type])
        raise LookupError(f"F13 has no fake provider for {task_type}")

    providers.select_provider = select
    providers.resolve_model = lambda *args, **kwargs: "gpt-5.6-luna"
    handlers = {
        external_sync.TASK: external_sync.run_sync,
        user_assets.TASK: user_assets.process_preview,
        asset_suggestions.TASK: asset_suggestions.run,
    }
    jobs = queue.Queue()
    active = set()
    stopped = threading.Event()

    def enqueue(task_name, *, org_id, lock, **kwargs):
        if task_name not in handlers or org_id != context["org_id"]:
            raise RuntimeError("Unexpected background task or tenant in F13 assembly")
        with state_lock:
            if lock in active:
                return False
            active.add(lock)
            jobs.put((task_name, lock, {"org_id": org_id, **kwargs}))
        return True

    background.enqueue = enqueue
    background.is_active = lambda lock: lock in active

    def runner():
        last_dispatch = 0
        while not stopped.wait(0.05):
            if read_json(context["state_file"]).get("paused"):
                continue
            try:
                if time.monotonic() - last_dispatch > 0.5:
                    for dispatch in (
                        external_sync.dispatch_pending,
                        user_assets.dispatch_pending,
                        asset_suggestions.dispatch_pending,
                    ):
                        dispatch(datetime.now(UTC))
                    last_dispatch = time.monotonic()
                name, lock, values = jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception as exc:
                stats["errors"].append(type(exc).__name__)
                continue
            try:
                handlers[name](**values)
                stats["handlers"][name] = stats["handlers"].get(name, 0) + 1
            except Exception as exc:
                stats["errors"].append(f"{name}:{type(exc).__name__}")
            finally:
                with state_lock:
                    active.discard(lock)
                jobs.task_done()

    thread = threading.Thread(target=runner, daemon=True, name="f13-real-handlers")
    return thread, stopped, stats
