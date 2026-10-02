"""app/ads/queue_done.py -- F47 Contract D: a brand queue row's done-ness has one owner.

Pure functions over one row of `triage.get_queue()` (`kind_key` + `proposal`, nothing else). The
rule is the one the home list always rendered (`home/status.ts::isQueueItemDone` before F47-I07):

- a change-set proposal (`cleanup`, `scale_budget`, the retired `stop_loss`) is done once it is
  rejected or deferred, or approved and its readback `confirmed`;
- a `worse` row's review round is done once deferred or unjudgeable, or completed with a copy change
  set that is itself done by the rule above;
- no proposal yet is never done; `refresh_creative`, `insufficient_data` and `settle` rows have
  no proposal flow and are never done.

`triage.get_queue` stamps `done` on every row; `status_summary.open_items` and the frontend read
that field -- no second copy of the rule anywhere.
"""

_SET_KINDS = frozenset({"cleanup", "scale_budget", "stop_loss"})

# The rows the home 「需要你決定」 board counts (`home/TodayDecisions.tsx::homeBoard`): the top
# bar's `open_items` counts the same rows, so the two numbers can never disagree (drill-10 Q2).
DECISION_KINDS = frozenset({"cleanup", "worse", "refresh_creative", "settle"})


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


def done(row) -> bool:
    """Whether this queue row no longer waits on the user."""
    proposal = row.get("proposal")
    if proposal is None:
        return False
    kind = row.get("kind_key")
    if kind == "worse":
        return _review_done(proposal)
    if kind in _SET_KINDS:
        return _set_done(proposal.get("status"), proposal.get("verification_state"))
    return False


def open_count(rows) -> int:
    """How many rows the home board shows as still waiting -- the top bar's `open_items`."""
    return sum(1 for row in rows if row.get("kind_key") in DECISION_KINDS and not row["done"])
