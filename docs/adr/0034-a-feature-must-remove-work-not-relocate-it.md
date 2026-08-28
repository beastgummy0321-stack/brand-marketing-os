# A feature must remove work, not relocate it

Every feature answers one question before it is built: **which action does the user no longer
perform?** If the answer is "the same action, in a different place", the feature does not get
built. This outranks every other decision in this repo — it is the test a ticket passes before
its done-checks are even written.

The test is mechanical. Write two lists of actions, *before* and *after*. The *after* list must
be **shorter**. Not tidier, not better organised, not prettier — shorter.

Two failures named by the user, 2026-08-29, that this rule exists to prevent:

- **"I used to paste brand information into ChatGPT one piece at a time to plan a campaign. If
  this program just swaps GPT for code and I do the same amount of typing and judging, I may as
  well not use it."**
- **"I used to open the Meta dashboard, the Shopee dashboard and my own site's dashboard one by
  one and work out performance myself. If this program still makes me flip between dashboards
  and do the arithmetic, I may as well not use it."**

## Work removed is not always clicks removed

Manual publishing is the case that nearly failed this test and passes for a different reason
than expected. The shell produces a campaign tree; a media buyer types it into Ads Manager by
hand. The typing is identical to before, so on clicks alone it relocates work. It survives
because it removes two other things:

- **Missed non-default settings.** Where the plan departs from a platform default — "Facebook
  only, no Instagram" — the tree carries a marked, collapsed node. The buyer stops discovering
  those by accident.
- **Untrackable results.** Each node carries the exact name to type. After publishing, the
  shell pulls the account's campaigns and binds the one whose name matches, then keeps the
  platform id and never relies on the name again. Without this, a hand-published campaign is
  invisible to the system forever and the next cycle has no data to reason from.

So the *after* list is shorter by "check every toggle by hand" and "reconcile results by hand",
even though it is not shorter by keystrokes. Name that saving in the ticket, or the feature has
not passed.

## There are two publishing modes, not three

**Manual publish**: the shell produces the tree; the human builds it in the platform.
**Automatic publish**: the shell builds the whole structure through the API in `PAUSED` state
and the human confirms and starts it. Meta's Marketing API accepts only `ACTIVE` and `PAUSED`
at creation, and a paused campaign cascades to its ad sets and ads, so nothing spends before
the human acts.

"Build it paused and let the human press go" is **what automatic publish is**, not a third mode
between the two. A separate button for it would be two buttons doing one thing.

## Consequences

- **A reviewer may reject a ticket for relocating work.** This joins the existing reject
  grounds (a failed done-check, a red machine gate, a container-contract violation). It is the
  only reject ground that is about the feature rather than the code.
- **Every ticket states its saving in one line**, in the form "the user no longer does X". A
  ticket that cannot fill that line is not ready to dispatch.
- **This rule is why ADR 0036 exists.** Hardcoded domain knowledge does not remove work from
  the user; it removes freedom from the agent and adds maintenance for us.
