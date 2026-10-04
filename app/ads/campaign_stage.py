"""app/ads/campaign_stage.py — F30-I06 (Contract E): the one lifecycle stage of a campaign, the
workspace's stage rail (prototype v10 `stageOf()`). Pure: the caller reads the facts, this module
only decides -- never a second copy of the rule in a route or the frontend.

Rules, in order, over the campaign's `lifecycle.state` (F49 Contract L):
- closed -> `review`, done (every stage, `review` included).
- ended -> `review`: the closeout is the step waiting.
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
          data_ready: bool | None, open_items: int | None) -> dict:
    """`{key, done}`: `done` is every stage before `key`, in rail order (all of them once
    closed)."""
    if state == "closed":
        return {"key": "review", "done": list(STAGES)}
    if state == "ended":
        key = "review"
    elif state == "draft":
        key = "launch" if launch_approved else "assets" if cap_set else "plan"
    elif data_ready is not True:
        key = "read"
    elif open_items:
        key = "decide"
    else:
        key = "read"
    return {"key": key, "done": list(STAGES[:STAGES.index(key)])}
