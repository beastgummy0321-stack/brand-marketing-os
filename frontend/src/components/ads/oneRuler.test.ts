/** Static falsifiers for the ads ruler (ads.md §6.33 "One ruler", F48 Contract R-API, decision 11). Backend twin:
 * `app/tests/test_ads_one_ruler.py`. Each scan reads every non-test source under `components/ads` (and the
 * `lib/ads*` read modules) and names the file and line of each hit:
 *
 * 1. F29-I01: no screen decides with the trend `class` (`x.class === …`, `switch (x.class)`, `x["class"]`).
 * 2. F48-I08: no ruler number is written down on the frontend (`1.2`, `1.3`, `1.5`, `0.02`, `3 *`／`* 3`, `3 倍`,
 *    `2 成`, `3 成`, `7 天`, `10 筆`, `SAMPLE_FEW`) — thresholds, labels and sentences come from `useAdsRules()`.
 * 3. F48-I08: no branch on a label — no equality against a `*_label` field, and no `…label === "中文"` (the frontend's
 *    own `step.label` navigation is allowed). Branches use `grade`／`reason_code`／`verdict`／`offer_key`.
 * 4. F48-I11: no fact written into words — a number with a unit (`N 天`, `N–M 天`, `N%`, `N 期`, `N 則`, `N 倍`,
 *    `N 成`, `N 筆`) in a string or JSX text. A fact a screen prints comes from a served field through `${…}`／`{…}`;
 *    the revisit quick picks 「N 天後」 are the frontend's own choices, and a zero (「0 筆」) is a grade's definition, not
 *    a figure. A `%` counts only after a space or a CJK character (`w-[30%]`, `width="100%"` are layout).
 * 5. F48-I10 (Contract M, one money calculator): no browser money arithmetic — no `Math.round(` whose argument names
 *    `total`, `budget`, `amount` or `pct` (a whole identifier, `x.total` included), and no comment that declares a
 *    copy of a backend rule (`mirrors`, `same formula as`, `same rule as`, 「同一套」) while naming `app/`. Amounts,
 *    totals and splits are the API's (`budget_total`, `budget_preview`, `allocation[].amount`).
 * 6. F49-I01 (Contract L, one lifecycle): no platform status word (`ACTIVE`, `PAUSED`, …) and no `.native_status`
 *    read — screens print the served `delivery_label`; no `.status ===` against `live|ended|closed` and no local list
 *    or map of two or more of those codes — screens read the served `lifecycle {state, label, can_close}`. Today's
 *    hits are listed in `LIFECYCLE_PENDING`, each naming the issue that removes it.
 * 7. F49-I02 (Contract O, one sync outcome): no `.job.status`／`.job.error` read and no `syncJob(` call outside
 *    `lib/useSyncOutcome.ts` — screens print the served `outcome`. Today's hits are listed in `SYNC_PENDING`.
 * 8. F49-I06 (Contract B): no local word table for verification or launch-item states — screens print the served
 *    `verification_label`／`status_label`／`state_label`. Today's hits are listed in `STATE_WORDS_PENDING`.
 * 9. F49-I05 (Contract Q): no local list of queue kinds (an array, `Set` or object keyed by two or more) and no table
 *    keyed by two or more wait reason codes — the queue serves `decision`／`position`／`decisions {kinds, open}` and
 *    `GET …/rules` serves `reasons`. Type unions are not literals. Today's hits are listed in `QUEUE_PENDING`.
 * 10. F49-I07 (Contract T): in the slot pieces no chip word (處理中／等你／卡住／失敗) in a string or JSX text, no word
 *    table keyed by two or more slot states and no `missing_material` read — slots serve `state_label`／`state_text`,
 *    the structure `slot_state`／`slot_label`. Today's hits are listed in `SLOT_PENDING`.
 *
 * Comments are not code: every scan reads the source with comments blanked out (line numbers kept); the numeric
 * literals are read in code only (a class name such as `gap-1.5` is a string). A hit that is not a served fact is
 * excused one line at a time in `NOT_A_RULER`, with the reason. F48-I11 emptied the per-file allowlist (the last
 * frontend issue of feature F48): every ads source is scanned. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ADS_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(ADS_DIR, "..", "..");
const LIB_DIR = join(SRC_DIR, "lib");

const CLASS_COMPARE = [
  /\.class\s*[!=]==?/, // x.class === "worse"
  /[!=]==?\s*[\w$.?]+\.class\b/, // "worse" === x.class
  /switch\s*\(\s*[\w$.?]+\.class\s*\)/, // switch (x.class)
  /\[\s*["']class["']\s*\]/, // x["class"]
];

/** The ruler's numbers (`app/ads/triage.py`／`learning_rank.py` own them; `GET …/rules` serves them), read in code. */
const RULER_NUMBERS = [
  /(?<![\w.])1\.2(?![\w.])/, // WATCH_BAND
  /(?<![\w.])1\.3(?![\w.])/, // NEAR_BEST
  /(?<![\w.])1\.5(?![\w.])/,
  /(?<![\w.])0\.02(?![\w.])/, // BREAK_EVEN_BAND
  /(?<![\w.])3 ?\*|\* ?3(?![\w.])/, // the 沒賣出 spend multiple
  /\bSAMPLE_FEW\b/,
];
/** The same rules as words, read in strings and JSX text too. 「N 天後」 (a revisit quick pick) is allowed. */
const RULER_WORDS = [
  /(?<![\d.])3 ?倍/, /(?<![\d.])2 ?成/, /(?<![\d.])3 ?成/, /(?<![\d.])7 ?天(?!後)/, /(?<![\d.])10 ?筆/,
];

/** A fact in words (F48-I11): a non-zero number with a unit, read in strings and JSX text (comments blanked). The
 * number must not continue a word, a class name or a bigger number; 「N 天後」 is allowed. */
const FACT_LITERALS = [
  /(?<![\w.\-[(,/–~])[1-9]\d*(?:[–~]\d+)? ?(?:天(?!後)|期|則|倍|成|筆)/,
  /(?<=[\s　-〿㐀-鿿＀-￯])[1-9]\d*(?:[–~]\d+)? ?%/,
];

/** A branch on a label: `x.grade_label === …`, `… !== y.offer_label`, or `label === "中文"` on any identifier
 * ending in `label`. `step.label` and `action.label` (navigation words the frontend builds itself) are allowed. */
const LABEL_COMPARE = [
  /\b\w+_label\s*[!=]==?/,
  /[!=]==?\s*[\w$.?]*\w_label\b/,
  /(?<!(?:step|action)\.)\b\w*[lL]abel\s*[!=]==?\s*["'`][\u4e00-\u9fff]/,
  /["'`][\u4e00-\u9fff][^"'`]*["'`]\s*[!=]==?\s*(?!(?:step|action)\.)[\w$.?]*[lL]abel\b/,
];

/** Money arithmetic (F48-I10): `Math.round(` over an expression naming a total／budget／amount／pct, read in code. */
const MONEY_WORD = /^(?:total|budget|amount|pct)$/i;
/** A comment declaring a copy of a backend rule; it is a hit only when the same comment names `app/`. */
const MIRROR_WORDS = /\bmirrors?\b|same (?:formula|rule) as|同一套/i;
const NAMES_APP = /(?<![\w/])app\//;

/** Hits that are not the ruler, excused one line at a time (`text` must appear on the hit line), with the reason. An
 * entry whose line is gone fails the stale-entry test. Entries marked "debt" are numbers the backend owns that a later
 * feature serves (F48 Decisions: time／input rules are W11–W14, feature C); they are excused here, not fixed. */
const NOT_A_RULER: { file: string; text: string; why: string }[] = [
  { file: "components/ads/home/MonthMoney.tsx", text: "(cpp ?? 0) * 1.3", why: "axis headroom of the home money meter, not NEAR_BEST" },
  { file: "components/ads/ReviewPanel.tsx", text: "預設每 7 天自動檢查", why: "the review round's revisit cadence (a default the user edits in 追蹤設定), not the grading window; debt: W13 serves the cadence" },
  { file: "components/ads/ReviewPanel.tsx", text: "一次最多 31 天", why: "debt (W13 input rules): the observation-range limit `app/ads/review_monitor.py` checks" },
  { file: "components/ads/ReviewTracking.tsx", text: "請填 1 至 31 天", why: "debt (W13 input rules): the same limit, validated before the request" },
  { file: "components/ads/NewCampaignPage.tsx", text: "從今天起算 30 天", why: "debt (W11 time rules): the brief's default period (`app/ads/brief.py`)" },
  { file: "components/ads/review/CopyPage.tsx", text: "（最多 5 則）", why: "debt (W13 input rules): the copy editor's per-list cap, enforced beside it" },
  { file: "components/ads/workspace/OverviewBody.tsx", text: "\"近 14 天數字\"", why: "debt (W11 time rules): the overview window's name; its dates print from `t.start`／`t.end`" },
  { file: "components/ads/workspace/OverviewBody.tsx", text: ">近 14 天花費<", why: "debt (W11 time rules): the same window's name" },
  { file: "components/ads/patterns/SlotGrid.tsx", text: "\"缺 1 則\"", why: "a slot placeholder is one missing ad by construction, not a figure" },
  { file: "components/ads/ExperimentPlan.tsx", text: "0.1 代表 10%", why: "explains the input's number format (a fraction), not a fact" },
  { file: "components/ads/StrategyTab.tsx", text: "剛好 100%", why: "percent shares sum to 100 by definition, not a fact" },
  // F48-I10 money scan: browser arithmetic over a backend number, and frontend functions that re-derive a backend
  // rule. Each is served by the backend in a later feature; the excuse goes when it is.
  { file: "components/ads/patterns/PaceChart.tsx", text: "const pace = Math.round((budget * dayOfMonth) / daysInMonth);", why: "debt: feature C/D (W11/W16) — today's pace on the home month chart is priced in the browser" },
  { file: "components/ads/PerformanceTab.tsx", text: "跟 `app/ads/learning.py::_sentence` 同一套公式", why: "debt: feature C/D (W11/W16) — the closeout learning sentence is rebuilt in the browser" },
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_spend` exactly", why: "debt: feature C/D (W11/W16) — an ad's window spend is summed in the browser" },
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_window`", why: "debt: feature C/D (W11/W16) — the ad's result view is picked in the browser by triage's rule" },
];

/** Test data that lives beside the sources: the served rules as a test fixture (the app never imports it). */
const TEST_DATA = new Set(["rulesFixture.ts"]);

function sources(dir: string, keep: (name: string) => boolean): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...sources(full, keep));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.(test|stories)\.tsx?$/.test(name) || TEST_DATA.has(name) || !keep(name)) continue;
    out.push(full);
  }
  return out;
}

/** The source with every comment replaced by spaces — and, with `blankStrings`, every string and template-literal
 * text too (a template's `${…}` code is kept). Newlines are kept, so line numbers hold; a `//` inside a string is not
 * a comment. */
function strip(text: string, blankStrings: boolean): string {
  let out = "";
  let i = 0;
  const keep = (s: string) => { out += s; };
  const blank = (s: string) => { out += s.replace(/[^\n]/g, " "); };
  const literal = (s: string) => (blankStrings ? blank(s) : keep(s));
  function code(inTemplate: boolean) {
    let depth = 0;
    while (i < text.length) {
      const c = text[i], n = text[i + 1];
      if (inTemplate && c === "{") depth++;
      if (inTemplate && c === "}" && depth-- === 0) return;
      if (c === "/" && n === "/") {
        const e = text.indexOf("\n", i);
        const stop = e === -1 ? text.length : e;
        blank(text.slice(i, stop));
        i = stop;
      } else if (c === "/" && n === "*") {
        const e = text.indexOf("*/", i + 2);
        const stop = e === -1 ? text.length : e + 2;
        blank(text.slice(i, stop));
        i = stop;
      } else if (c === '"' || c === "'") {
        let j = i + 1;
        while (j < text.length && text[j] !== c && text[j] !== "\n") j += text[j] === "\\" ? 2 : 1;
        keep(c);
        literal(text.slice(i + 1, j));
        if (text[j] === c) { keep(c); j++; }
        i = j;
      } else if (c === "`") {
        keep(c);
        i++;
        template();
      } else {
        keep(c);
        i++;
      }
    }
  }
  function template() {
    while (i < text.length) {
      const c = text[i];
      if (c === "\\") {
        literal(text.slice(i, i + 2));
        i += 2;
      } else if (c === "`") {
        keep(c);
        i++;
        return;
      } else if (c === "$" && text[i + 1] === "{") {
        keep("${");
        i += 2;
        code(true);
        if (i < text.length) { keep("}"); i++; }
      } else {
        literal(c);
        i++;
      }
    }
  }
  code(false);
  return out;
}

function hits(text: string, patterns: RegExp[], blankStrings = false): number[] {
  const lines: number[] = [];
  strip(text, blankStrings).split("\n").forEach((line, index) => {
    if (patterns.some((pattern) => pattern.test(line))) lines.push(index + 1);
  });
  return lines;
}

/** Each `Math.round(` whose argument (balanced parentheses, strings blanked) names a money word, by line. */
function moneyRounding(text: string): number[] {
  const code = strip(text, true);
  const lines: number[] = [];
  for (const m of code.matchAll(/Math\.round\(/g)) {
    let depth = 1;
    let j = (m.index ?? 0) + m[0].length;
    const from = j;
    while (j < code.length && depth > 0) {
      if (code[j] === "(") depth++;
      else if (code[j] === ")") depth--;
      j++;
    }
    const names = code.slice(from, j - 1).match(/[A-Za-z_$][\w$]*/g) ?? [];
    if (names.some((name) => MONEY_WORD.test(name))) lines.push(code.slice(0, m.index).split("\n").length);
  }
  return [...new Set(lines)];
}

/** Comment text only (code blanked, line numbers kept). A run of lines that carry comment text is one comment; a
 * clause of it (up to `.`／`;`／。／；) with a mirror word that also names `app/` is a hit, reported at the mirror
 * word's line. 「this builder mirrors the same shape」 in a comment that names `app/` elsewhere is not. */
function mirrorComments(text: string): number[] {
  const code = strip(text, false);
  let comments = "";
  for (let i = 0; i < text.length; i++) comments += text[i] === "\n" ? "\n" : code[i] === text[i] ? " " : text[i];
  const rows = comments.split("\n");
  const lines: number[] = [];
  let block: number[] = [];
  const flush = () => {
    const joined = block.map((n) => rows[n]).join("\n");
    let start = 0;
    for (const clause of joined.split(/[.;](?=\s|$)|[。；]/)) {
      const at = joined.indexOf(clause, start);
      start = at + clause.length;
      const word = MIRROR_WORDS.exec(clause);
      if (word && NAMES_APP.test(clause)) lines.push(block[joined.slice(0, at + word.index).split("\n").length - 1] + 1);
    }
    block = [];
  };
  rows.forEach((row, n) => { if (row.trim()) block.push(n); else if (block.length) flush(); });
  if (block.length) flush();
  return [...new Set(lines)];
}

/** F49 Contract L (decision 11): a platform's own status vocabulary and the `native_status` field are the backend
 * adapter's (`app/ads/adapters/meta_read.py` `STATUS_TABLE`); a screen prints the served `delivery_label`／`delivery`. */
const NATIVE_STATUS = [
  /(?<![\w$])(?:ACTIVE|PAUSED|ARCHIVED|DELETED|ADSET_PAUSED|CAMPAIGN_PAUSED|DISAPPROVED|WITH_ISSUES|IN_PROCESS|PENDING_REVIEW|PREAPPROVED|PENDING_BILLING_INFO)(?![\w$])/,
  /\.native_status\b/,
];
/** F49 Contract L: the campaign lifecycle (`live|ended|closed`) is served as `lifecycle {state, label, can_close}`; a
 * screen never compares `.status` to those codes nor keeps its own list or map of two or more of them. */
const LIFECYCLE_CODE = `(?:live|ended|closed)`;
const LIFECYCLE_COMPARE = [
  new RegExp(String.raw`\.status\s*[!=]==?\s*["'\x60]${LIFECYCLE_CODE}["'\x60]`),
  new RegExp(String.raw`["'\x60]${LIFECYCLE_CODE}["'\x60]\s*[!=]==?\s*[\w$.?]*\.status\b`),
  new RegExp(String.raw`\[[^\[\]\n]*["']${LIFECYCLE_CODE}["'][^\[\]\n]*["']${LIFECYCLE_CODE}["'][^\[\]\n]*\]`),
];
const LIFECYCLE_KEY = new RegExp(String.raw`(?:^|[\s{,;])["']?(live|ended|closed)["']?\s*:`, "g");

/** Each `{…}` block (no nested braces, comments blanked) keyed by two or more lifecycle codes, at its `{` line. */
function lifecycleMaps(text: string): number[] {
  const code = strip(text, false);
  const lines: number[] = [];
  for (const m of code.matchAll(/\{[^{}]*\}/g)) {
    const keys = new Set([...m[0].matchAll(LIFECYCLE_KEY)].map((k) => k[1]));
    if (keys.size >= 2) lines.push(code.slice(0, m.index).split("\n").length);
  }
  return lines;
}

const nativeStatus = (text: string) => hits(text, NATIVE_STATUS);
const lifecycleCodes = (text: string) =>
  [...new Set([...hits(text, LIFECYCLE_COMPARE), ...lifecycleMaps(text)])].sort((a, b) => a - b);

/** Today's hits of the two F49 lifecycle rules, each naming the issue that moves the file onto the served fields and
 * deletes the entry (an entry with `text` excuses only its lines). An entry whose file no longer hits fails the
 * stale-entry test, so every screen issue deletes its own entries. The W19 entries (the change-set pause payload is
 * the platform's own word, feature D) stay. */
type LifecycleRule = "native" | "lifecycle";
const LIFECYCLE_PENDING: { rule: LifecycleRule; file: string; issue: string; text?: string }[] = [
  { rule: "native", file: "components/ads/detail/GradeGroups.tsx", issue: "F49-I09" },
  { rule: "native", file: "components/ads/OverviewTab.tsx", issue: "F49-I09" },
  { rule: "native", file: "components/ads/flow/VerifyPage.tsx", issue: "F49-I11" },
  { rule: "native", file: "components/ads/AssetsTab.tsx", issue: "F49-I13" },
  { rule: "native", file: "components/ads/DeliveryTab.tsx", issue: "F49-I13" },
  { rule: "native", file: "components/ads/ExistingCampaignDialog.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/ExternalCampaignPanel.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/ChangeSetView.tsx", issue: "F49-I14" },
  { rule: "native", file: "components/ads/patterns/campaignWords.ts", issue: "F49-I14" },
  { rule: "native", file: "components/ads/flow/changeFlow.ts", issue: "W19", text: 'after: { status: "PAUSED" }' },
  { rule: "native", file: "components/ads/ChangeComposer.tsx", issue: "W19", text: '{ status: "PAUSED" }' },
  { rule: "lifecycle", file: "components/ads/AllCampaignsPage.tsx", issue: "F49-I08" },
  { rule: "lifecycle", file: "components/ads/patterns/campaignWords.ts", issue: "F49-I08" },
  { rule: "lifecycle", file: "components/ads/home/status.ts", issue: "F49-I08" },
  { rule: "lifecycle", file: "components/ads/nextStep.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/PerformanceTab.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/detail/CampaignDetailPage.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/detail/PeriodStatusRow.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/workspace/OverviewBody.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/workspace/WorkspaceHead.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/DeliveryTab.tsx", issue: "F49-I13" },
  { rule: "lifecycle", file: "components/ads/UserAssetPlacements.tsx", issue: "F49-I14" },
  { rule: "lifecycle", file: "components/ads/CloseCampaignDialog.tsx", issue: "F49-I09" },
  { rule: "lifecycle", file: "components/ads/ManualSettings.tsx", issue: "F49-I12" },
];
const LIFECYCLE_SCANS: Record<LifecycleRule, (text: string) => number[]> = { native: nativeStatus, lifecycle: lifecycleCodes };

/** Every hit of `rule` as `file:line`, the `LIFECYCLE_PENDING` ones left out. */
function lifecycleOffenders(rule: LifecycleRule): string[] {
  const files = FILES();
  expect(files.length).toBeGreaterThan(20);
  return files.flatMap((full) => {
    const text = readFileSync(full, "utf-8");
    const lines = text.split("\n");
    const entries = LIFECYCLE_PENDING.filter((x) => x.rule === rule && x.file === rel(full));
    const excused = (line: number) => entries.some((x) => x.text === undefined || lines[line - 1].includes(x.text));
    return LIFECYCLE_SCANS[rule](text).filter((line) => !excused(line)).map((line) => `${rel(full)}:${line}`);
  });
}

const classComparisons = (text: string) => hits(text, CLASS_COMPARE);
const rulerLiterals = (text: string) =>
  [...new Set([...hits(text, RULER_NUMBERS, true), ...hits(text, RULER_WORDS)])].sort((a, b) => a - b);
const labelComparisons = (text: string) => hits(text, LABEL_COMPARE);
const factLiterals = (text: string) => hits(text, FACT_LITERALS);

const FILES = () => [...sources(ADS_DIR, () => true), ...sources(LIB_DIR, (name) => name.startsWith("ads"))];
const rel = (full: string) => relative(SRC_DIR, full).split("\\").join("/");

/** Every hit of `scan` across the ads sources as `file:line`; with `excuse`, the `NOT_A_RULER` lines are left out. */
function offenders(scan: (text: string) => number[], excuse: boolean): string[] {
  const files = FILES();
  expect(files.length).toBeGreaterThan(20);
  return files.flatMap((full) => {
    const text = readFileSync(full, "utf-8");
    const lines = text.split("\n");
    const excused = (line: number) => excuse && NOT_A_RULER.some((x) => x.file === rel(full) && lines[line - 1].includes(x.text));
    return scan(text).filter((line) => !excused(line)).map((line) => `${rel(full)}:${line}`);
  });
}

describe("one ruler (ads.md §6.33)", () => {
  it("no ads screen decides with the trend `class`", () => {
    expect(offenders(classComparisons, false)).toEqual([]);
  });

  it("the class scan sees every comparison shape and ignores other uses of the word", () => {
    expect(classComparisons('if (item.class === "worse") x();')).toEqual([1]);
    expect(classComparisons('const a = "flat" !== item.triage.class;')).toEqual([1]);
    expect(classComparisons("switch (row.triage.class) {}")).toEqual([1]);
    expect(classComparisons('const c = item["class"];')).toEqual([1]);
    expect(classComparisons('<div className="p-2" />')).toEqual([]);
    expect(classComparisons('const t = { class: "flat" };')).toEqual([]);
    expect(classComparisons('// was: item.class === "worse"')).toEqual([]);
  });
});

describe("rules come from the API (F48 Contract R-API, decision 11)", () => {
  it("no ads source writes a ruler number down", () => {
    expect(offenders(rulerLiterals, true)).toEqual([]);
  });

  it("no ads source branches on a label", () => {
    expect(offenders(labelComparisons, true)).toEqual([]);
  });

  it("no ads source writes a fact into its words (F48-I11)", () => {
    expect(offenders(factLiterals, true)).toEqual([]);
  });

  it("every excused line is still there and still a hit (stale entries go)", () => {
    const present = new Set(FILES().map(rel));
    const stale = NOT_A_RULER.filter((x) => {
      if (!present.has(x.file)) return true;
      const text = readFileSync(join(SRC_DIR, x.file), "utf-8");
      const lines = text.split("\n");
      const hit = [...rulerLiterals(text), ...labelComparisons(text), ...factLiterals(text), ...moneyRounding(text), ...mirrorComments(text)];
      return !hit.some((line) => lines[line - 1].includes(x.text));
    });
    expect(stale).toEqual([]);
  });

  it("no ads source does money arithmetic or re-derives a backend rule (F48-I10, Contract M)", () => {
    expect(offenders(moneyRounding, true)).toEqual([]);
    expect(offenders(mirrorComments, true)).toEqual([]);
  });

  it("the money scan sees each planted rounding and leaves other rounding alone", () => {
    expect(moneyRounding("const a = Math.round((pickedRow.total * pct) / 100);")).toEqual([1]);
    expect(moneyRounding("const t = Math.round(dailySum * days) + Math.round(c.budget);")).toEqual([1]);
    expect(moneyRounding("const x = formatAmount(Math.round((total * p.pct) / 100));")).toEqual([1]);
    expect(moneyRounding("const a = 1;\nconst y = Math.round(\n  item?.amount ?? 0,\n);")).toEqual([2]);
    expect(moneyRounding("const p = Math.round((spent / t.TOTAL) * 100);")).toEqual([1]);
    expect(moneyRounding("const d = Math.round((end - start) / 86_400_000);")).toEqual([]);
    expect(moneyRounding("const p = Math.round(item.change_pct * 100); const q = Math.round(okAmount / spent);")).toEqual([]);
    expect(moneyRounding('const s = Math.round(x) + " total budget";')).toEqual([]);
    expect(moneyRounding("// Math.round(total * pct)")).toEqual([]);
    expect(moneyRounding("const n = Math.floor(total);")).toEqual([]);
  });

  it("the mirror scan sees a comment that copies a backend rule and leaves other comments alone", () => {
    expect(mirrorComments("/** F03-I23: mirrors `app/ads/repository.py::_budget_total` exactly. */\nexport const a = 1;")).toEqual([1]);
    expect(mirrorComments("// Same formula as the backend:\n// `app/ads/budget.py::split`\nconst a = 1;")).toEqual([1]);
    expect(mirrorComments("/** 跟 `app/ads/learning.py::_sentence` 同一套公式 */")).toEqual([1]);
    expect(mirrorComments("/** Same rule as `app/ads/triage.py` */ const a = 1;")).toEqual([1]);
    expect(mirrorComments("/** mirrors the prototype's layout */\nconst a = 1;")).toEqual([]);
    expect(mirrorComments("/** Served by `app/ads/budget.py`. */")).toEqual([]);
    expect(mirrorComments('const s = "mirrors app/ads";')).toEqual([]);
    expect(mirrorComments("// mirrors the old screen\n\n// `app/ads/x.py` serves this")).toEqual([]);
    expect(mirrorComments("/** The backend sends it twice (`app/ads/triage.py`); this builder mirrors that shape. */")).toEqual([]);
    expect(mirrorComments("/** Shape read from `app/ads/x.py`.\n * The union just mirrors the contract's own type. */")).toEqual([]);
  });

  it("the fact scan sees each planted literal", () => {
    expect(factLiterals('{ title: "學習期", note: "3–5 天" }')).toEqual([1]);
    expect(factLiterals("<div>加碼後等 3–5 天再看</div>")).toEqual([1]);
    expect(factLiterals('const r = "近兩期每筆都沒超過上限，加碼 20% 擴量";')).toEqual([1]);
    expect(factLiterals('const s = "已結案 2 期";')).toEqual([1]);
    expect(factLiterals("<p>這期 12 則廣告</p>")).toEqual([1]);
    expect(factLiterals('const s = "花到上限 3 倍";')).toEqual([1]);
    expect(factLiterals('const s = "加 2成";')).toEqual([1]);
    expect(factLiterals("const s = `賣出 ${n} 筆，另有 5 筆退款`;")).toEqual([1]);
    expect(factLiterals('const s = "等 1~2 天";')).toEqual([1]);
    expect(factLiterals('const s = cond ? "最多 31 天" : "";')).toEqual([1]);
  });

  it("the fact scan leaves served numbers, quick picks, zeros, layout and comments alone", () => {
    expect(factLiterals("const s = `${days} 天・${count} 則`;")).toEqual([]);
    expect(factLiterals("<span>{n} 筆</span>")).toEqual([]);
    expect(factLiterals('const picks = [{ label: "3 天後" }, { label: "7 天後" }];')).toEqual([]);
    expect(factLiterals('const s = "0 筆"; const t = "確認上架清單（0 則）";')).toEqual([]);
    expect(factLiterals('<i className="w-[30%] mt-1.5 top-[calc(100%+6px)]" />')).toEqual([]);
    expect(factLiterals('<svg width="100%" />')).toEqual([]);
    expect(factLiterals("const w = `${pct}%`;")).toEqual([]);
    expect(factLiterals('const k = "F48-I11 2026-10-04";')).toEqual([]);
    expect(factLiterals("// 學習期 3–5 天")).toEqual([]);
    expect(factLiterals("/* 加碼 20% */ const a = 1;")).toEqual([]);
  });

  it("the ruler scan sees each planted literal", () => {
    expect(rulerLiterals("const over = cost > cap * 1.2;")).toEqual([1]);
    expect(rulerLiterals("const keep = best * 1.3;")).toEqual([1]);
    expect(rulerLiterals("const x = cap * 1.5;")).toEqual([1]);
    expect(rulerLiterals("if (Math.abs(d) <= be * 0.02) even();")).toEqual([1]);
    expect(rulerLiterals("const gate = 3 * cap;")).toEqual([1]);
    expect(rulerLiterals("const gate = cap * 3;")).toEqual([1]);
    expect(rulerLiterals("const s = `到 ${formatAmount(T * 1.2)} 元`;")).toEqual([1]);
    expect(rulerLiterals('const s = "花到上限 3 倍";')).toEqual([1]);
    expect(rulerLiterals('const s = "超過不到 2 成";')).toEqual([1]);
    expect(rulerLiterals('const s = "差 3 成";')).toEqual([1]);
    expect(rulerLiterals('const s = "跑滿 7 天";')).toEqual([1]);
    expect(rulerLiterals("<span>賣出 10 筆</span>")).toEqual([1]);
    expect(rulerLiterals("const SAMPLE_FEW = 5;")).toEqual([1]);
  });

  it("the ruler scan leaves other numbers, class names and comments alone", () => {
    expect(rulerLiterals("const axis = cap * 1.6;")).toEqual([]);
    expect(rulerLiterals("const w = 31.2; const v = 1.25;")).toEqual([]);
    expect(rulerLiterals("const n = 13 * cap; const m = x * 30;")).toEqual([]);
    expect(rulerLiterals('<i className="mt-1.5 gap-1.2 px-3" />')).toEqual([]);
    expect(rulerLiterals("const c = `size-1.5 ${open ? \"gap-1.2\" : \"\"}`;")).toEqual([]);
    expect(rulerLiterals('const s = "近 14 天";')).toEqual([]);
    expect(rulerLiterals('const picks = ["3 天後", "7 天後"];')).toEqual([]);
    expect(rulerLiterals('const s = "近 17 天・12 成・110 筆";')).toEqual([]);
    expect(rulerLiterals("// 偏貴 <= 1.2T, 沒賣出 >= 3 × T, 7 天")).toEqual([]);
    expect(rulerLiterals("/* 7 天 */ const a = 1;")).toEqual([]);
    expect(rulerLiterals('const url = "http://x/"; // 7 天')).toEqual([]);
  });

  it("the label scan sees each planted branch and allows step.label", () => {
    expect(labelComparisons("if (item.grade_label === GRADE_LABEL.insufficient) x();")).toEqual([1]);
    expect(labelComparisons('const t = slot.offer_label === NO_OFFER ? "a" : "b";')).toEqual([1]);
    expect(labelComparisons("if (word !== row.verdict_label) x();")).toEqual([1]);
    expect(labelComparisons('return label === "剛開始、數字還不夠" ? a : b;')).toEqual([1]);
    expect(labelComparisons('if ("無優惠" === slot.offerLabel) x();')).toEqual([1]);
    expect(labelComparisons('if (step.label === "上限") x();')).toEqual([]);
    expect(labelComparisons('if (action.label === "看紀錄") return null;')).toEqual([]);
    expect(labelComparisons('if (item.reason_code === "too_new") x();')).toEqual([]);
    expect(labelComparisons("const word = item.grade_label || rules.labels.grade.too_new;")).toEqual([]);
    expect(labelComparisons('// was: item.grade_label === "資料不足"')).toEqual([]);
  });
});

describe("one lifecycle (F49 Contract L, decision 11)", () => {
  it("no ads source writes a platform status word or reads `.native_status`", () => {
    expect(lifecycleOffenders("native")).toEqual([]);
  });

  it("no ads source compares `.status` to a lifecycle code or keeps its own list or map of them", () => {
    expect(lifecycleOffenders("lifecycle")).toEqual([]);
  });

  it("every pending entry still hits (an issue that moved its file deletes its entry)", () => {
    const present = new Set(FILES().map(rel));
    const stale = LIFECYCLE_PENDING.filter((x) => {
      if (!present.has(x.file)) return true;
      const text = readFileSync(join(SRC_DIR, x.file), "utf-8");
      const lines = text.split("\n");
      return !LIFECYCLE_SCANS[x.rule](text).some((line) => x.text === undefined || lines[line - 1].includes(x.text));
    });
    expect(stale).toEqual([]);
  });

  it("the native scan sees status words and `.native_status` and leaves comments and served labels alone", () => {
    expect(nativeStatus('if (ad.native_status === "ACTIVE") x();')).toEqual([1]);
    expect(nativeStatus("const W = { PAUSED: '已暫停', ARCHIVED: '已封存' };")).toEqual([1]);
    expect(nativeStatus("const s = row?.native_status ?? null;")).toEqual([1]);
    expect(nativeStatus('const k = "DISAPPROVED";')).toEqual([1]);
    expect(nativeStatus("<Chip>{item.delivery_label}</Chip>")).toEqual([]);
    expect(nativeStatus("// was: native_status === 'ACTIVE'")).toEqual([]);
    expect(nativeStatus('const s = "ACTIVE_FILTER" + IS_ACTIVE;')).toEqual([]);
  });

  it("the lifecycle scan sees comparisons, lists and maps of the codes", () => {
    expect(lifecycleCodes('if (c.status === "closed") x();')).toEqual([1]);
    expect(lifecycleCodes("const a = 'ended' !== campaign.status;")).toEqual([1]);
    expect(lifecycleCodes('const ENDED = ["ended", "closed"];')).toEqual([1]);
    expect(lifecycleCodes('const s = new Set(["live", "ended"]);')).toEqual([1]);
    expect(lifecycleCodes('const W = {\n  draft: "草稿",\n  live: "投放中",\n  ended: "已結束",\n};')).toEqual([1]);
    expect(lifecycleCodes('if (c.lifecycle.state === "ended") x();')).toEqual([]);
    expect(lifecycleCodes('const one = ["live"]; const k = { live: 1 };')).toEqual([]);
    expect(lifecycleCodes('// c.status === "live"')).toEqual([]);
    expect(lifecycleCodes('if (job.status === "running") x();')).toEqual([]);
  });
});

/** F49-I02 (Contract O, one sync outcome): a platform read's outcome is served (`outcome {state, code, text}`) and read
 * through `lib/useSyncOutcome.ts` only — no screen reads a sync job's `.job.status`／`.job.error` or polls `syncJob(`
 * itself (the function's own declaration in `lib/adsExternalApi.ts` is not a call). Today's callers are listed in
 * `SYNC_PENDING`, each naming the issue that moves the screen onto the hook and deletes the entry; an entry whose file no
 * longer hits fails the stale-entry test. */
const SYNC_JOB_READ = [
  /\.job\??\.(?:status|error)\b/,
  /(?<!function\s+)\bsyncJob\(/,
];
const syncJobReads = (text: string) => hits(text, SYNC_JOB_READ);
const SYNC_PENDING: { file: string; issue: string; text?: string; why?: string }[] = [
  { file: "components/ads/wait/WaitPage.tsx", issue: "F49-I10" },
  { file: "components/ads/CampaignWorkspace.tsx", issue: "F49-I09" },
  { file: "components/ads/connections/DataConnectionsPage.tsx", issue: "F49-I14" },
  { file: "components/ads/ExistingCampaignDialog.tsx", issue: "F49-I14" },
  { file: "components/ads/ExternalCampaignPanel.tsx", issue: "F49-I14" },
  { file: "components/ads/settle/SettleAngles.tsx", issue: "W14", text: "found?.job.status",
    why: "an AI (LLM) job's queue status, not a platform read; background job outcomes are W14 (feature C)" },
];

describe("one sync outcome (F49 Contract O)", () => {
  it("no ads source reads a sync job's status／error or polls syncJob( outside useSyncOutcome", () => {
    const files = FILES();
    expect(files.length).toBeGreaterThan(20);
    const offenders = files.flatMap((full) => {
      const text = readFileSync(full, "utf-8");
      const lines = text.split("\n");
      const entries = SYNC_PENDING.filter((x) => x.file === rel(full));
      const excused = (line: number) => entries.some((x) => x.text === undefined || lines[line - 1].includes(x.text));
      return syncJobReads(text).filter((line) => !excused(line)).map((line) => `${rel(full)}:${line}`);
    });
    expect(offenders).toEqual([]);
  });

  it("every pending entry still hits (an issue that moved its screen onto the hook deletes its entry)", () => {
    const present = new Set(FILES().map(rel));
    const stale = SYNC_PENDING.filter((x) => {
      if (!present.has(x.file)) return true;
      const text = readFileSync(join(SRC_DIR, x.file), "utf-8");
      const lines = text.split("\n");
      return !syncJobReads(text).some((line) => x.text === undefined || lines[line - 1].includes(x.text));
    });
    expect(stale).toEqual([]);
  });

  it("the hook itself is the reader and is not scanned as a screen", () => {
    expect(FILES().map(rel)).not.toContain("lib/useSyncOutcome.ts");
    expect(syncJobReads(readFileSync(join(LIB_DIR, "useSyncOutcome.ts"), "utf-8")).length).toBeGreaterThan(0);
  });

  it("the sync scan sees each read shape and leaves the declaration, outcomes and comments alone", () => {
    expect(syncJobReads('if (["pending", "running"].includes(result.job.status)) x();')).toEqual([1]);
    expect(syncJobReads("if (result.job.error) setError(result.job.error);")).toEqual([1]);
    expect(syncJobReads("const s = page?.job?.status;")).toEqual([1]);
    expect(syncJobReads("const r = await syncJob(brandId, id, signal);")).toEqual([1]);
    expect(syncJobReads("export async function syncJob(brand: string, id: string) {}")).toEqual([]);
    expect(syncJobReads("<p>{outcome.text}</p>")).toEqual([]);
    expect(syncJobReads('if (read.state === "running") x();')).toEqual([]);
    expect(syncJobReads("// was: result.job.error")).toEqual([]);
  });
});

/** F49-I06 (Contract B, decision 11): a verification state's word is served (`verification_label`, `status_label`,
 * `state_label`) — no ads source keeps its own word table for the verification states
 * (`pending|reported|unknown|confirmed|deviated|stale`) or the launch-item states (`todo|built|verified|mismatch|changed`):
 * no object literal keyed by two or more codes of one of those vocabularies, and no `switch` with two or more such
 * `case`s, that holds a Chinese literal (a map onto colours or segment kinds is not a word table). Today's hits are
 * listed in `STATE_WORDS_PENDING`, each naming the issue that
 * moves the screen onto the served label and deletes the entry; a line that is not a word table is excused in
 * `STATE_WORDS_NOT_A_TABLE` with the reason. An entry whose file no longer hits fails the stale-entry test. */
const STATE_VOCABULARIES = [
  ["pending", "reported", "unknown", "confirmed", "deviated", "stale"],
  ["todo", "built", "verified", "mismatch", "changed"],
];
const STATE_KEY = /(?:^|[\s{,;])(?<!\bcase\s+)["']?([a-z_]+)["']?\s*:/g;
const STATE_CASE = /\bcase\s+["'`]([a-z_]+)["'`]\s*:/g;
const CJK = /[一-鿿]/;
const twoOfOneVocabulary = (codes: string[]) =>
  STATE_VOCABULARIES.some((vocabulary) => new Set(codes.filter((c) => vocabulary.includes(c))).size >= 2);

/** Each `{…}` block (no nested braces, comments blanked) keyed by two or more codes of one state vocabulary, and each
 * `switch` whose body has two or more `case`s of one vocabulary and a Chinese literal, at its first line. */
function stateWordTables(text: string): number[] {
  return wordTables(text, twoOfOneVocabulary);
}

/** `stateWordTables` over any vocabulary test (`twoOf` says whether the codes found hold two or more of one). */
function wordTables(text: string, twoOf: (codes: string[]) => boolean): number[] {
  const code = strip(text, false);
  const lineOf = (index: number) => code.slice(0, index).split("\n").length;
  const lines: number[] = [];
  for (const m of code.matchAll(/\{[^{}]*\}/g)) {
    if (CJK.test(m[0]) && twoOf([...m[0].matchAll(STATE_KEY)].map((k) => k[1]))) {
      lines.push(lineOf(m.index ?? 0));
    }
  }
  for (const m of code.matchAll(/\bswitch\s*\(/g)) {
    const open = code.indexOf("{", m.index ?? 0);
    if (open === -1) continue;
    let depth = 0;
    let end = open;
    for (; end < code.length; end++) {
      if (code[end] === "{") depth++;
      else if (code[end] === "}" && --depth === 0) break;
    }
    const body = code.slice(open, end + 1);
    if (CJK.test(body) && twoOf([...body.matchAll(STATE_CASE)].map((k) => k[1]))) {
      lines.push(lineOf(m.index ?? 0));
    }
  }
  return [...new Set(lines)].sort((a, b) => a - b);
}

const STATE_WORDS_PENDING: { file: string; issue: string }[] = [
  { file: "components/ads/flow/CleanupVerifyRows.tsx", issue: "F49-I11" },
  { file: "components/ads/home/status.ts", issue: "F49-I08" },
  { file: "components/ads/publish/PublishVerify.tsx", issue: "F49-I12" },
  { file: "components/ads/ChangeSetView.tsx", issue: "F49-I14" },
  { file: "components/ads/ManualHandoffPanel.tsx", issue: "F49-I14" },
];
const STATE_WORDS_NOT_A_TABLE: { file: string; text: string; why: string }[] = [
  { file: "components/ads/PlannedMaterialAssignments.tsx", text: "const statusLabel = { unassigned:",
    why: "a placement's `assignment_status` (unassigned|confirmed|stale), another vocabulary that shares two words" },
];

describe("one verification vocabulary (F49 Contract B)", () => {
  it("no ads source keeps its own word table for verification or launch-item states", () => {
    const files = FILES();
    expect(files.length).toBeGreaterThan(20);
    const offenders = files.flatMap((full) => {
      const text = readFileSync(full, "utf-8");
      const lines = text.split("\n");
      if (STATE_WORDS_PENDING.some((x) => x.file === rel(full))) return [];
      const excused = (line: number) =>
        STATE_WORDS_NOT_A_TABLE.some((x) => x.file === rel(full) && lines[line - 1].includes(x.text));
      return stateWordTables(text).filter((line) => !excused(line)).map((line) => `${rel(full)}:${line}`);
    });
    expect(offenders).toEqual([]);
  });

  it("every pending or excused entry still hits (an issue that moved its screen deletes its entry)", () => {
    const present = new Set(FILES().map(rel));
    const read = (file: string) => readFileSync(join(SRC_DIR, file), "utf-8");
    const stalePending = STATE_WORDS_PENDING.filter((x) => !present.has(x.file) || stateWordTables(read(x.file)).length === 0);
    const staleExcuses = STATE_WORDS_NOT_A_TABLE.filter((x) => {
      if (!present.has(x.file)) return true;
      const lines = read(x.file).split("\n");
      return !stateWordTables(read(x.file)).some((line) => lines[line - 1].includes(x.text));
    });
    expect([...stalePending, ...staleExcuses]).toEqual([]);
  });

  it("the state-word scan sees maps and switches of one vocabulary and leaves the rest alone", () => {
    expect(stateWordTables('const W = { pending: "尚未回報", confirmed: "已核對" };')).toEqual([1]);
    expect(stateWordTables('const W: Record<string, string> = {\n  "reported": "已回報",\n  unknown: "待確認",\n};')).toEqual([1]);
    expect(stateWordTables('const T = { verified: ["ok", "相符"], mismatch: ["warn", "不符"] };')).toEqual([1]);
    expect(stateWordTables('function w(s: string) {\n  switch (s) {\n    case "built": return "待讀回";\n    case "todo": return "還沒建";\n    default: return "";\n  }\n}')).toEqual([2]);
    expect(stateWordTables('switch (s) { case "built": return 1; case "todo": return 2; }')).toEqual([]);
    expect(stateWordTables('const one = { pending: "尚未回報" }; const mixed = { stale: 1, verified: 2 };')).toEqual([]);
    expect(stateWordTables('const SEGMENT = { verified: "ok", built: "built", mismatch: "mismatch" };')).toEqual([]);
    expect(stateWordTables("interface R { count: number; unknown: number; stale: boolean }")).toEqual([]);
    expect(stateWordTables("<Chip>{item.verification_label}</Chip>")).toEqual([]);
    expect(stateWordTables('// const W = { pending: "a", confirmed: "b" };')).toEqual([]);
  });
});

/** F49-I05 (Contract Q, decision 11): which rows are decisions, their board order and the wait reasons' words are served
 * (`app/ads/queue_done.py` `DECISION_KINDS`, each row's `decision`／`position`, `decisions {kinds, open}`; `GET …/rules`
 * `reasons`). No ads source keeps an array, `Set` or object keyed by two or more queue kinds, nor one of two or more wait
 * reason codes (type unions are not literals). Today's hits are listed in `QUEUE_PENDING`, each naming the issue that
 * moves the screen onto the served fields and deletes the entry; an entry whose file no longer hits fails the stale-entry
 * test. */
const QUEUE_KINDS = ["cleanup", "worse", "closeout", "settle", "refresh_creative", "scale_budget", "insufficient_data", "stop_loss"];
const WAIT_REASONS = [
  "too_new", "result_unknown_days", "needs_resync", "mixed_currency", "mixed_result_definition", "no_previous_window",
  "result_kind_unknown", "target_unresolved",
];

/** Each array literal (no nested brackets) quoting two or more of `codes`, and each object literal keyed by two or more
 * of them at its own level (comments blanked; a `case "x":` and a ternary's `? "x" :` are not keys), at its first line. */
function codeTables(text: string, codes: string[]): number[] {
  const code = strip(text, false);
  const lineOf = (index: number) => code.slice(0, index).split("\n").length;
  const alternatives = codes.join("|");
  const quoted = new RegExp(String.raw`["'\x60](${alternatives})["'\x60]`, "g");
  const lines: number[] = [];
  for (const m of code.matchAll(/\[[^[\]]*\]/g)) {
    if (new Set([...m[0].matchAll(quoted)].map((k) => k[1])).size >= 2) lines.push(lineOf(m.index ?? 0));
  }
  // The innermost `{` that holds each position, in one pass.
  const owner: number[] = new Array(code.length).fill(-1);
  const open: number[] = [];
  for (let i = 0; i < code.length; i++) {
    if (code[i] === "{") open.push(i);
    owner[i] = open.length ? open[open.length - 1] : -1;
    if (code[i] === "}") open.pop();
  }
  const key = new RegExp(String.raw`(?:^|[\s{,;])(?<!\bcase\s+)(?<!\?\s*)["']?(${alternatives})["']?\s*:`, "gm");
  const keysByBlock = new Map<number, Set<string>>();
  for (const m of code.matchAll(key)) {
    const at = (m.index ?? 0) + m[0].indexOf(m[1]);
    const block = owner[at];
    if (block < 0) continue;
    if (!keysByBlock.has(block)) keysByBlock.set(block, new Set());
    keysByBlock.get(block)?.add(m[1]);
  }
  for (const [block, keys] of keysByBlock) if (keys.size >= 2) lines.push(lineOf(block));
  return [...new Set(lines)].sort((a, b) => a - b);
}

type QueueRule = "kinds" | "reasons";
const QUEUE_SCANS: Record<QueueRule, (text: string) => number[]> = {
  kinds: (text) => codeTables(text, QUEUE_KINDS),
  reasons: (text) => codeTables(text, WAIT_REASONS),
};
const QUEUE_PENDING: { rule: QueueRule; file: string; issue: string }[] = [
  { rule: "kinds", file: "components/ads/home/status.ts", issue: "F49-I08" },
  { rule: "kinds", file: "components/ads/home/QueueRow.tsx", issue: "F49-I08" },
  { rule: "kinds", file: "components/ads/settle/SettlePage.tsx", issue: "F49-I08" },
  { rule: "kinds", file: "components/ads/workspace/OverviewBody.tsx", issue: "F49-I09" },
  { rule: "kinds", file: "components/ads/review/ReviewEvidencePage.tsx", issue: "F49-I11" },
  { rule: "reasons", file: "components/ads/wait/WaitPage.tsx", issue: "F49-I10" },
];

describe("one decision queue (F49 Contract Q)", () => {
  for (const rule of ["kinds", "reasons"] as const) {
    it(`no ads source keeps its own table of ${rule === "kinds" ? "queue kinds" : "wait reason codes"}`, () => {
      const files = FILES();
      expect(files.length).toBeGreaterThan(20);
      const offenders = files.flatMap((full) => {
        if (QUEUE_PENDING.some((x) => x.rule === rule && x.file === rel(full))) return [];
        return QUEUE_SCANS[rule](readFileSync(full, "utf-8")).map((line) => `${rel(full)}:${line}`);
      });
      expect(offenders).toEqual([]);
    });
  }

  it("every pending entry still hits (an issue that moved its screen onto the served fields deletes its entry)", () => {
    const present = new Set(FILES().map(rel));
    const stale = QUEUE_PENDING.filter(
      (x) => !present.has(x.file) || QUEUE_SCANS[x.rule](readFileSync(join(SRC_DIR, x.file), "utf-8")).length === 0,
    );
    expect(stale).toEqual([]);
  });

  it("the queue scans see arrays, sets and object keys and leave unions, branches and comments alone", () => {
    const kinds = QUEUE_SCANS.kinds;
    expect(kinds('const ORDER: QueueKind[] = ["cleanup", "worse", "refresh_creative"];')).toEqual([1]);
    expect(kinds('const BEFORE = new Set(["cleanup", "worse"]);')).toEqual([1]);
    expect(kinds('const MARK = {\n  cleanup: { kind: "cut", label: "清理" },\n  worse: { kind: "worse", label: "變貴" },\n};')).toEqual([1]);
    expect(kinds('const W = { "settle": 1, "closeout": 2 };')).toEqual([1]);
    expect(kinds('export type QueueKind = "cleanup" | "worse" | "closeout";')).toEqual([]);
    expect(kinds('if (item.kind_key === "cleanup" || item.kind_key === "worse") x();')).toEqual([]);
    expect(kinds('const k = a ? "cleanup" : b ? "worse" : "pause";')).toEqual([]);
    expect(kinds('switch (k) { case "cleanup": return 1; case "worse": return 2; }')).toEqual([]);
    expect(kinds('const one = ["cleanup"]; const two = { cleanup: { worse: 1 } };')).toEqual([]);
    expect(kinds('// const ORDER = ["cleanup", "worse"];')).toEqual([]);
    expect(kinds('interface P { cleanup?: X; settle?: Y }')).toEqual([]);
    const reasons = QUEUE_SCANS.reasons;
    expect(reasons('const REASON_ORDER = ["too_new", "result_unknown_days"] as const;')).toEqual([1]);
    expect(reasons('const T = { too_new: "剛開始", needs_resync: "重讀" };')).toEqual([1]);
    expect(reasons('if (code === "too_new") x();')).toEqual([]);
    expect(reasons("const r = rules.reasons[item.reason_code];")).toEqual([]);
  });
});

/** F49-I07 (Contract T, decision 11): a slot's chip word and sentence are served (`state_label`／`state_text`, one table
 * in `app/ads/slots.py` `STATE_TEXT`) and the structure read serves `slot_state`／`slot_label`. In the slot pieces no chip
 * word (處理中, 等你, 卡住, 失敗) is written as a string or JSX text, no word table is keyed by two or more slot states,
 * and no screen reads `missing_material` (one 缺素材 for six states). Today's hits are listed in `SLOT_PENDING`, each
 * naming the issue that moves the piece onto the served fields and deletes the entry; an entry whose file no longer
 * hits fails the stale-entry test. */
const SLOT_PIECES = [
  "components/ads/workspace/SlotTiles.tsx",
  "components/ads/workspace/AssetsBody.tsx",
  "components/ads/workspace/StructureTab.tsx",
  "components/ads/patterns/SlotGrid.tsx",
];
const SLOT_STATES = ["ready", "missing", "in_progress", "retrying", "failed", "waiting", "copy_only", "image_only", "blocked"];
type SlotRule = "chip" | "table" | "missing";
const SLOT_SCANS: Record<SlotRule, (text: string) => number[]> = {
  chip: (text) => hits(text, [/處理中|等你|卡住|失敗/]),
  table: (text) => wordTables(text, (codes) => new Set(codes.filter((c) => SLOT_STATES.includes(c))).size >= 2),
  missing: (text) => hits(text, [/\bmissing_material\b/]),
};
const SLOT_PENDING: { rule: SlotRule; file: string; issue: string }[] = [
  { rule: "chip", file: "components/ads/workspace/SlotTiles.tsx", issue: "F49-I13" },
  { rule: "chip", file: "components/ads/workspace/AssetsBody.tsx", issue: "F49-I13" },
  { rule: "missing", file: "components/ads/workspace/StructureTab.tsx", issue: "F49-I13" },
];

describe("slot states told as served (F49 Contract T)", () => {
  for (const rule of ["chip", "table", "missing"] as const) {
    it(`no slot piece keeps its own ${rule === "chip" ? "chip words" : rule === "table" ? "slot-state word table" : "missing_material read"}`, () => {
      const offenders = SLOT_PIECES.flatMap((file) => {
        if (SLOT_PENDING.some((x) => x.rule === rule && x.file === file)) return [];
        return SLOT_SCANS[rule](readFileSync(join(SRC_DIR, file), "utf-8")).map((line) => `${file}:${line}`);
      });
      expect(offenders).toEqual([]);
    });
  }

  it("every slot piece exists and every pending entry still hits (the issue that moved it deletes its entry)", () => {
    const present = new Set(FILES().map(rel));
    expect(SLOT_PIECES.filter((file) => !present.has(file))).toEqual([]);
    const stale = SLOT_PENDING.filter(
      (x) => !present.has(x.file) || SLOT_SCANS[x.rule](readFileSync(join(SRC_DIR, x.file), "utf-8")).length === 0,
    );
    expect(stale).toEqual([]);
  });

  it("the slot scans see chip words, state word tables and missing_material and leave the rest alone", () => {
    expect(SLOT_SCANS.chip('<Chip tone="warn">等你</Chip>')).toEqual([1]);
    expect(SLOT_SCANS.chip('const w = { n: 1, word: "卡住" };')).toEqual([1]);
    expect(SLOT_SCANS.chip("<Chip>{slot.state_label}</Chip>")).toEqual([]);
    expect(SLOT_SCANS.chip("// 處理中 slots poll every 3 s")).toEqual([]);
    expect(SLOT_SCANS.table('const W = { ready: "已確認", blocked: "卡住" };')).toEqual([1]);
    expect(SLOT_SCANS.table('const SEGMENT = { ready: "ok", in_progress: "running", blocked: "blocked" };')).toEqual([]);
    expect(SLOT_SCANS.table('const one = { ready: "已確認" };')).toEqual([]);
    expect(SLOT_SCANS.missing("if (a.missing_material) return null;")).toEqual([1]);
    expect(SLOT_SCANS.missing('if (a.slot_state !== "ready") x();')).toEqual([]);
  });
});
