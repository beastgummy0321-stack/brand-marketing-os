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
  // F48-I10 money scan. Debt outside this issue's touch (reported to the feature lead): browser arithmetic over a
  // backend number, and comments that say a frontend function re-derives a backend rule.
  { file: "components/ads/patterns/PaceChart.tsx", text: "const pace = Math.round((budget * dayOfMonth) / daysInMonth);", why: "debt: today's pace on the home month chart is priced in the browser; home_overview's pace block should serve it" },
  { file: "components/ads/PerformanceTab.tsx", text: "跟 `app/ads/learning.py::_sentence` 同一套公式", why: "debt: the closeout learning sentence is rebuilt in the browser; the close response should serve it" },
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_spend` exactly", why: "debt: an ad's window spend is summed in the browser; the review read should serve it" },
  { file: "components/ads/review/reviewFlow.ts", text: "mirrors `app/ads/triage.py::_ad_window`", why: "debt: the ad's result view is picked in the browser by triage's rule; the review read should serve it" },
  // Read-shape notes: a type file saying which route serves its shape re-derives no rule (rewording them is a
  // one-word change in files outside this issue's touch).
  { file: "lib/adsConnectionsApi.ts", text: "Mirrors `app/ads/connections.py::get_connections` exactly", why: "a response type's shape, not a rule" },
  { file: "lib/adsTriageApi.ts", text: "decision queue, per-ad program triage, and campaign target sub-resource. Mirrors", why: "a response type's shape, not a rule" },
  { file: "lib/adsHomeApi.ts", text: "Mirrors `app/ads/home_overview.py` exactly", why: "a response type's shape, not a rule" },
  { file: "lib/adsMonthApi.ts", text: "Mirrors `app/ads/month_summary.py`", why: "a response type's shape, not a rule" },
  { file: "lib/adsSettleApi.ts", text: "Mirrors `app/ads/settle.py`", why: "a response type's shape, not a rule" },
  { file: "lib/adsStatusApi.ts", text: "Mirrors `app/ads/status_summary.py::get_status_summary`", why: "a response type's shape, not a rule" },
  { file: "lib/adsStatusApi.ts", text: "mirrors `app/ads/recovery.py::get_recovery`", why: "a response type's shape, not a rule" },
  { file: "lib/adsWizardApi.ts", text: "Mirrors `app/ads/wizard_options.py`", why: "a response type's shape, not a rule" },
  { file: "lib/adsWorkspaceApi.ts", text: "Mirrors `app/ads/workspace_reads.py` exactly", why: "a response type's shape, not a rule" },
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
