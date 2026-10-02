"""app/ads/learning_rank.py — F46 Contract B: the one ranking rule a closed campaign's ads are
judged by (drill-10 root cause 1: the 555 winner was tagged 太貴 beside 1,769, the 290 winner
never entered learning, and the next plan re-ran the themes it had just cut).

Pure: no SQL, no model call. Input = `period_grades.grade_period` rows of one campaign (spend,
results, currency, cap). The program decides 留下／換掉; the planners only read the result.

- Who enters: a row whose spend and results are both known in one currency. Sold (results >= 1)
  rows rank by cost per sale (spend ÷ results) ascending, then more sales first, then name;
  沒賣出 rows (known 0 results, spend > 0) follow, cheapest spend first. Anything else (unknown
  results or spend, mixed currency, nothing spent) is not ranked and writes nothing.
- Verdict: cap known and cost <= cap -> `keep` 「留下」. When no sold row is <= cap (or there is
  no cap): sold rows with cost <= best × 1.3 -> `keep_relative` 「留下」 flagged
  「相對最好，仍高於上限」 (no cap: 「相對最好」). Every other row, 沒賣出 included -> `replace`.
- 「樣本少」 = 1–4 sales (`SAMPLE_FEW`, the prototype's constant).

Also the stored scope string (`scope` / `parse_scope`) the closeout writes and every reader
parses: `coord；v=2；verdict=…；rank=…；of=…；sales=…；spend=…；cpr=…；cap=…；few=…；group=…；
audience=…；pain=…；angle=…；hook=…；proof=…；offer=…；format=…；cur=…`. Rows without `v=2`
(F39/F41 grade rows) parse as `None` and are read nowhere.
Private to app/ads.
"""

import math

SAMPLE_FEW = 5  # 1–4 sales -> 樣本少
NEAR_BEST = 1.3  # nothing under the cap -> keep the best and those within 30% of it

KEEP, KEEP_RELATIVE, REPLACE = "keep", "keep_relative", "replace"
VERDICTS = (KEEP, KEEP_RELATIVE, REPLACE)
VERDICT_LABELS = {KEEP: "留下", KEEP_RELATIVE: "留下", REPLACE: "換掉"}
FLAG_FEW = "樣本少"
FLAG_RELATIVE = "相對最好，仍高於上限"
FLAG_RELATIVE_NO_CAP = "相對最好"

# The seven learning coordinates, in the order every learning reader prints them.
DIMENSIONS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")
# The dimension names the owner reads (drill-8 #11: no English codes on screen or in stored text).
DIMENSION_LABELS = {
    "audience": "受眾", "pain": "痛點", "angle": "角度", "hook": "標題", "proof": "證據",
    "offer": "優惠", "format": "格式",
}
MISSING = "none"
SCOPE_PREFIX = "coord"
SCOPE_VERSION = "2"


def is_keep(verdict: str) -> bool:
    return verdict in (KEEP, KEEP_RELATIVE)


def _known(row: dict) -> bool:
    return (
        row.get("results") is not None and row.get("spend") is not None
        and row.get("currency") is not None
    )


def rank(rows: list[dict]) -> list[dict]:
    """Contract B over one campaign's `grade_period` rows. Each result row is the input row plus
    `sales`, `cost_per_sale` (None for 沒賣出), `verdict`, `verdict_label`, `flags`, `few`,
    `rank`, `of`. Unknown and no-spend rows are left out."""
    sold, unsold = [], []
    for row in rows:
        if not _known(row):
            continue
        sales = int(row["results"])
        spend = float(row["spend"])
        if sales >= 1:
            sold.append({**row, "sales": sales, "spend": spend, "cost_per_sale": spend / sales})
        elif spend > 0:
            unsold.append({**row, "sales": 0, "spend": spend, "cost_per_sale": None})
    sold.sort(key=lambda r: (r["cost_per_sale"], -r["sales"], r.get("name") or ""))
    unsold.sort(key=lambda r: (r["spend"], r.get("name") or ""))

    cap = _cap(rows)
    any_under = cap is not None and any(r["cost_per_sale"] <= cap for r in sold)
    near = sold[0]["cost_per_sale"] * NEAR_BEST if sold else None
    ranked = []
    for row in sold:
        flags = []
        if any_under:
            verdict = KEEP if row["cost_per_sale"] <= cap else REPLACE
        elif row["cost_per_sale"] <= near:
            verdict = KEEP_RELATIVE
            flags.append(FLAG_RELATIVE if cap is not None else FLAG_RELATIVE_NO_CAP)
        else:
            verdict = REPLACE
        if row["sales"] < SAMPLE_FEW:
            flags.insert(0, FLAG_FEW)
        ranked.append({**row, "verdict": verdict, "flags": flags})
    ranked.extend({**row, "verdict": REPLACE, "flags": []} for row in unsold)
    for n, row in enumerate(ranked, start=1):
        row.update({
            "rank": n, "of": len(ranked), "verdict_label": VERDICT_LABELS[row["verdict"]],
            "few": 1 <= row["sales"] < SAMPLE_FEW, "cap": cap,
        })
    return ranked


def _cap(rows: list[dict]):
    """The campaign's one cap (every row of a campaign carries the same resolved value)."""
    for row in rows:
        if row.get("cap") is not None:
            return float(row["cap"])
    return None


def whole(value) -> str:
    """Money as the owner reads it: a whole number, half up, with thousands separators."""
    return f"{math.floor(float(value) + 0.5):,}"


def rule_text(ranked: list[dict], cap) -> str | None:
    """How this campaign was judged, in one line (Contract L); `None` with no ranked row."""
    if not ranked:
        return None
    costs = [row["cost_per_sale"] for row in ranked if row["cost_per_sale"] is not None]
    if not costs:
        return "沒有一則賣出 → 全部換掉"
    kept = [row for row in ranked if row["verdict"] == KEEP]
    if kept:
        return f"{len(kept)} 則每筆低於上限 {whole(cap)} → 留下；其餘換掉"
    best = min(costs)
    head = "沒有上限" if cap is None else f"沒有一則低於上限 {whole(cap)}"
    return f"{head} → 留下最好的 {whole(best)} 和 {whole(best * NEAR_BEST)} 以內的；其餘換掉"


# -- stored scope ------------------------------------------------------------------------------

def _num(value) -> str:
    if value is None:
        return MISSING
    rounded = round(float(value), 2)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


def scope(row: dict, keys: dict, group_id: str | None) -> str:
    """The stored `applicability_scope` of one ranked row (Contract B, plus `cur`: the ad's one
    currency, so the view's campaign currency also comes from the stored row)."""
    fields = [
        SCOPE_PREFIX, f"v={SCOPE_VERSION}", f"verdict={row['verdict']}", f"rank={row['rank']}",
        f"of={row['of']}", f"sales={row['sales']}", f"spend={_num(row['spend'])}",
        f"cpr={_num(row['cost_per_sale'])}", f"cap={_num(row['cap'])}",
        f"few={1 if row['few'] else 0}", f"group={group_id or MISSING}",
        *(f"{d}={keys.get(d) or MISSING}" for d in DIMENSIONS),
        f"cur={row.get('currency') or MISSING}",
    ]
    return "；".join(fields)


def _parse_num(value: str | None):
    if value is None or value == MISSING:
        return None
    try:
        number = round(float(value), 2)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def parse_scope(text: str | None) -> dict | None:
    """Inverse of `scope`; `None` for anything that is not a `v=2` row (old grade rows included)."""
    parts = (text or "").split("；")
    if not parts or parts[0] != SCOPE_PREFIX:
        return None
    fields = {}
    for part in parts[1:]:
        name, sep, value = part.partition("=")
        if sep:
            fields[name] = value
    if fields.get("v") != SCOPE_VERSION or fields.get("verdict") not in VERDICTS:
        return None
    try:
        rank_no, of, sales = int(fields["rank"]), int(fields["of"]), int(fields["sales"])
    except (KeyError, ValueError):
        return None
    cap = _parse_num(fields.get("cap"))
    verdict = fields["verdict"]
    few = fields.get("few") == "1"
    flags = [FLAG_FEW] if few else []
    if verdict == KEEP_RELATIVE:
        flags.append(FLAG_RELATIVE if cap is not None else FLAG_RELATIVE_NO_CAP)
    group = fields.get("group")
    currency = fields.get("cur")
    return {
        "verdict": verdict, "verdict_label": VERDICT_LABELS[verdict], "flags": flags,
        "few": few, "rank": rank_no, "of": of, "sales": sales,
        "spend": _parse_num(fields.get("spend")),
        "cost_per_sale": _parse_num(fields.get("cpr")), "cap": cap,
        "customer_group_id": None if group in (None, "", MISSING) else group,
        "keys": {d: fields.get(d) or MISSING for d in DIMENSIONS},
        "currency": None if currency in (None, "", MISSING) else currency,
    }
