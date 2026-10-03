/** Static falsifiers for the ads ruler (ads.md §6.33 "One ruler", F48 Contract R-API, decision 11). Backend twin:
 * `app/tests/test_ads_one_ruler.py`. Each scan reads every non-test source under `components/ads` (and the
 * `lib/ads*` read modules) and names the file and line of each hit:
 *
 * 1. F29-I01: no screen decides with the trend `class` (`x.class === …`, `switch (x.class)`, `x["class"]`).
 * 2. F48-I08: no ruler number is written down on the frontend (`1.2`, `1.3`, `1.5`, `0.02`, `3 *`／`* 3`, `3 倍`,
 *    `2 成`, `3 成`, `7 天`, `10 筆`, `SAMPLE_FEW`) — thresholds, labels and sentences come from `useAdsRules()`.
 * 3. F48-I08: no branch on a label — no equality against a `*_label` field, and no `…label === "中文"` (the frontend's
 *    own `step.label` navigation is allowed). Branches use `grade`／`reason_code`／`verdict`／`offer_key`.
 *
 * Comments are not code: every scan reads the source with comments blanked out (line numbers kept); the numeric
 * literals are read in code only (a class name such as `gap-1.5` is a string). `ALLOWLIST` names the files a later
 * issue of feature F48 rewires; that issue removes its own entries. */
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

/** A branch on a label: `x.grade_label === …`, `… !== y.offer_label`, or `label === "中文"` on any identifier
 * ending in `label`. `step.label` and `action.label` (navigation words the frontend builds itself) are allowed. */
const LABEL_COMPARE = [
  /\b\w+_label\s*[!=]==?/,
  /[!=]==?\s*[\w$.?]*\w_label\b/,
  /(?<!(?:step|action)\.)\b\w*[lL]abel\s*[!=]==?\s*["'`][\u4e00-\u9fff]/,
  /["'`][\u4e00-\u9fff][^"'`]*["'`]\s*[!=]==?\s*(?!(?:step|action)\.)[\w$.?]*[lL]abel\b/,
];

/** Hits that are not the ruler, excused one line at a time (`text` must appear on the hit line), with the reason. */
const NOT_A_RULER: { file: string; text: string; why: string }[] = [
  { file: "components/ads/home/MonthMoney.tsx", text: "(cpp ?? 0) * 1.3", why: "axis headroom of the home money meter, not NEAR_BEST" },
  { file: "components/ads/ReviewPanel.tsx", text: "預設每 7 天自動檢查", why: "the review round's revisit cadence, not the grading window" },
];

/** Files a later F48 issue rewires (it removes its own entries; the last frontend issue leaves this empty). */
const ALLOWLIST: Record<string, string> = {
  "components/ads/flow/confirmParts.tsx": "F48-I11",
  "components/ads/flow/changeFlow.ts": "F48-I11",
};

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

const classComparisons = (text: string) => hits(text, CLASS_COMPARE);
const rulerLiterals = (text: string) =>
  [...new Set([...hits(text, RULER_NUMBERS, true), ...hits(text, RULER_WORDS)])].sort((a, b) => a - b);
const labelComparisons = (text: string) => hits(text, LABEL_COMPARE);

const FILES = () => [...sources(ADS_DIR, () => true), ...sources(LIB_DIR, (name) => name.startsWith("ads"))];
const rel = (full: string) => relative(SRC_DIR, full).split("\\").join("/");

function offenders(scan: (text: string) => number[], allow: boolean): string[] {
  const files = FILES();
  expect(files.length).toBeGreaterThan(20);
  return files
    .filter((full) => !(allow && rel(full) in ALLOWLIST))
    .flatMap((full) => {
      const text = readFileSync(full, "utf-8");
      const lines = text.split("\n");
      const excused = (line: number) => allow && NOT_A_RULER.some((x) => x.file === rel(full) && lines[line - 1].includes(x.text));
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
  it("no ads source writes a ruler number down (outside the allowlist)", () => {
    expect(offenders(rulerLiterals, true)).toEqual([]);
  });

  it("no ads source branches on a label (outside the allowlist)", () => {
    expect(offenders(labelComparisons, true)).toEqual([]);
  });

  it("every allowlisted file exists and every excused line is still there (stale entries go)", () => {
    const present = new Set(FILES().map(rel));
    expect(Object.keys(ALLOWLIST).filter((path) => !present.has(path))).toEqual([]);
    const stale = NOT_A_RULER.filter((x) => !present.has(x.file) || !readFileSync(join(SRC_DIR, x.file), "utf-8").includes(x.text));
    expect(stale).toEqual([]);
  });

  it("every allowlisted file still has a hit (a file that is clean leaves the allowlist and stays guarded)", () => {
    const clean = Object.keys(ALLOWLIST).filter((path) => {
      const text = readFileSync(join(SRC_DIR, path), "utf-8");
      return rulerLiterals(text).length === 0 && labelComparisons(text).length === 0;
    });
    expect(clean).toEqual([]);
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
