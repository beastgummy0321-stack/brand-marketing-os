"""app/ads/queue_done.py -- F47 Contract D, F49 Contract Q: which queue rows are decisions, and when
a row is done, have one owner.

Pure functions over one row of `triage.get_queue()` (`kind_key` + `proposal`, nothing else).

`DECISION_KINDS` is the one list of decision kinds, in board order -- the home 「需要你決定」
board, 「第 N 件／共 M 件」, 「下一件」, the top bar's `open_items` and the inbox's ads-queue
rows all count these rows and only these. `NOTICE_KINDS` are served in the queue read with
`decision: false` (`scale_budget` on the money card, `insufficient_data` on the campaign row and
`/wait`) and are never an inbox interrupt.

Done rules (`DONE_RULES`, one per kind the queue serves):
- a change-set proposal (`cleanup`, `scale_budget`, the retired `stop_loss`) is done once it is
  rejected or deferred, or approved and its readback `confirmed`;
- a `worse` row's review round is done once deferred or unjudgeable, or completed with a copy change
  set that is itself done by the rule above;
- no proposal yet is never done; `closeout` (it leaves when the campaign closes), `settle`,
  `refresh_creative` and `insufficient_data` rows have no proposal flow and are never done.

`triage.get_queue` stamps `decision`, `done` and `position` on every row; `status_summary`,
`workspace_reads`, `digest` and the frontend read those fields -- no second copy of the rule.
"""

DECISION_KINDS = ("cleanup", "worse", "closeout", "settle", "refresh_creative")
NOTICE_KINDS = ("scale_budget", "insufficient_data")


def _set_done(status, verification_state) -> bool:
    if status in {"rejected", "deferred"}:
        return True
    return status == "approved" and verification_state == "confirmed"


def _review_done(proposal) -> bool:
    status = proposal.get("status")
    if status in {"deferred", "unjudgeable"}:
        return True
    if status == "completed" and proposal.get("change_set_id") is not None:
        return _set_done(
            proposal.get("change_set_status") or "draft",
            proposal.get("verification_state") or "pending",
        )
    return False


def _change_set_done(proposal) -> bool:
    return _set_done(proposal.get("status"), proposal.get("verification_state"))


def _never(_proposal) -> bool:
    return False


DONE_RULES = {
    "cleanup": _change_set_done,
    "worse": _review_done,
    "closeout": _never,
    "settle": _never,
    "refresh_creative": _never,
    "scale_budget": _change_set_done,
    "insufficient_data": _never,
    "stop_loss": _change_set_done,
}


def is_decision(row) -> bool:
    """Whether this queue row is a decision the user is asked to make (a counted row)."""
    return row.get("kind_key") in DECISION_KINDS


def done(row) -> bool:
    """Whether this queue row no longer waits on the user."""
    proposal = row.get("proposal")
    if proposal is None:
        return False
    rule = DONE_RULES.get(row.get("kind_key"), _never)
    return rule(proposal)


def open_count(rows) -> int:
    """How many decision rows still wait -- the top bar's `open_items`, the home board's total and
    a campaign workspace's `pending_count` (over that campaign's rows)."""
    return sum(1 for row in rows if is_decision(row) and not row["done"])


def stamp(rows) -> dict:
    """Stamp `decision`, `done` and `position` on every row (in place) and return the payload's
    `decisions {kinds, open}`. `position` is 1-based over the open decision rows in board order
    (`DECISION_KINDS`; rows of one kind keep their given order), null on every other row."""
    for row in rows:
        row["decision"] = is_decision(row)
        row["done"] = done(row)
        row["position"] = None
    waiting = [row for row in rows if row["decision"] and not row["done"]]
    waiting.sort(key=lambda row: DECISION_KINDS.index(row["kind_key"]))
    for index, row in enumerate(waiting, start=1):
        row["position"] = index
    return {"kinds": list(DECISION_KINDS), "open": len(waiting)}
