"""app/ads/campaign_stage.py — F30-I06 (Contract E): the one lifecycle stage of a campaign, the
workspace's stage rail (prototype v10 `stageOf()`). Pure: the caller reads the facts, this module
only decides -- never a second copy of the rule in a route or the frontend.

Rules, in order, over the campaign's `lifecycle.state` (F49 Contract L):
- closed -> `review`, done (every stage, `review` included).
- ended -> `review` when internal closeout is available, else `read` for an imported campaign.
- draft (not on any platform yet) -> `launch` once its launch is approved, `assets` once its cap
  resolves, else `plan`.
- live -> `read` while its `data_status` (triage `data.status`) is not `ready`, `decide` when it
  has open queue items, else `read`.

Unknown is never promoted: an unread data status counts as not ready, and an unread queue count as
no open item, so a failed read lands on `read` -- the stage that asks for nothing -- and never on
`decide`.
"""

STAGES = ("plan", "assets", "launch", "read", "decide", "review")


def stage(*, state: str, launch_approved: bool, cap_set: bool,
          data_ready: bool | None, open_items: int | None, can_close: bool = True) -> dict:
    """`{key, done}`: `done` is every stage before `key`, in rail order (all of them once
    closed)."""
    if state == "closed":
        return {"key": "review", "done": list(STAGES)}
    if state == "ended":
        key = "review" if can_close else "read"
    elif state == "draft":
        key = "launch" if launch_approved else "assets" if cap_set else "plan"
    elif data_ready is not True:
        key = "read"
    elif open_items:
        key = "decide"
    else:
        key = "read"
    return {"key": key, "done": list(STAGES[:STAGES.index(key)])}


def next_action(*, lifecycle: dict, capabilities: dict, running: dict,
                launch_approved: bool = False, stage_key: str | None = None) -> dict:
    """Served target descriptors consumed by the existing canonical adsRoutes builders.

    Navigation only; never activation, a second platform comparator or a router path.
    """
    allowed = capabilities["allowed"]
    state = lifecycle["state"]
    if state == "draft" and launch_approved and "publish" in allowed:
        return {"id": "review_checklist", "label": "查看已核准的平台交接清單",
                "target": {"kind": "flow", "parts": ["publish"]},
                "reason": "核准與內部確認不代表平台已上架或開始投放。"}
    if state == "draft":
        tab = ("strategy" if "strategy" in allowed and stage_key not in {"assets", "launch"}
               else "assets")
        return {"id": "prepare_campaign", "label": "查看策略" if tab == "strategy" else "安排素材",
                "target": {"kind": "campaign", "tab": tab},
                "reason": "尚未讀到平台活動；先完成可用的準備步驟。"}
    if state in {"ended", "closed"}:
        can_close = lifecycle["can_close"] and "close" in allowed
        return {"id": "review_period",
                "label": "查看本期結果與結案" if can_close else "查看本期成效",
                "target": {"kind": "campaign", "tab": "perf"},
                "reason": (capabilities["unavailable"].get("close")
                           or "週期狀態不代表平台廣告已關閉。")}
    if running["state"] == "off":
        return {"id": "view_delivery", "label": "查看未在投放的廣告",
                "target": {"kind": "campaign", "tab": "structure"}, "reason": running["reason"]}
    return {"id": "read_platform" if running["state"] == "unknown" else "view_performance",
            "label": "查看平台讀取狀態" if running["state"] == "unknown" else "查看本期成效",
            "target": {"kind": "campaign", "tab": "perf"}, "reason": running["reason"]}


def action_of(conn, org_id: str, brand_id: str, campaign: dict, lifecycle: dict,
              running: dict, *, stage_key: str | None = None) -> dict:
    """Read the existing approved launch owner for list/detail/home guidance."""
    from app.ads import change_control_launch, external_models, targets

    launch = (change_control_launch.launch_set(conn, org_id, brand_id, campaign["id"])
              if lifecycle["state"] == "draft" else None)
    if lifecycle["state"] == "draft" and stage_key is None:
        cap = targets.resolve(conn, org_id, brand_id, campaign)
        stage_key = "assets" if cap["value"] is not None else "plan"
    return next_action(lifecycle=lifecycle,
                       capabilities=external_models.capabilities(campaign["origin"]),
                       running=running, launch_approved=launch is not None, stage_key=stage_key)
