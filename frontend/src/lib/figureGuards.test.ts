/** F51 Contract F (W16) — numbers carry their basis: repo-wide ratchets installed by F51-I04.
 *
 * 1. `zero`: `?? 0` and `|| 0` — an unknown number printed (or summed) as 0. Unknown is `null` and prints 不明 or
 *    the payload's reason (`layout/Figure`); a counted zero is served as 0.
 * 2. `currency`: an interpolated `NT$`／`US$` prefix (`NT$${x}`, `NT$ ${x}`, `US$${x}`, JSX `NT${x}`, `"NT$" + x`)
 *    outside `lib/format.ts` — money prints through `formatMoney(value, currency)` with its own currency, never a
 *    prefix the screen assumes.
 * 3. `money-ratio` (`components/ads/**`): dividing by a spend／cap or multiplying a price by results — the browser
 *    rebuilding a ROAS or a money figure the backend serves. The one browser ratio is `lib/figures.ts::roasAtCap`
 *    (a cap being typed) and `roasOf` (imported rows).
 * 4. `roas-format` (`components/ads/**`): `formatMetaRoas(`, `.toFixed(` on a ROAS value, reading `.roas`／
 *    `.roas_conservative` — a ROAS prints through `layout/Figure` by its basis code.
 *
 * Same ratchet as `lib/feedbackGuards.test.ts`: non-test sources under `components/**` and `lib/**`, comments blanked
 * first (line numbers kept); a hit in a file no `lib/guards/F51-INN.allow.ts` module lists fails; a listed
 * `(rule, file)` with no hit left fails as stale, naming the issue; a legitimate line carries an inline
 * `// <RULE>_OK: <why>` (`ZERO_OK:`, `CURRENCY_OK:`, `MONEY_RATIO_OK:`, `ROAS_FORMAT_OK:`; `{/* … *\/}` in JSX), and an
 * excuse on a line without a hit fails. The comment blanking and allow-module loader are a copy of the feedback
 * guards' (a test file cannot import another test file without running its suites twice). */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(LIB_DIR, "..");

function listFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.(test|stories)\.tsx?$/.test(name)) continue;
    out.push(full);
  }
  return out;
}

/** The source with every comment replaced by spaces (newlines kept, so line numbers hold); a `//`
 * inside a string or template text is not a comment. Copied from `lib/feedbackGuards.test.ts` (same reading as `components/ads/oneRuler.test.ts`). */
function blankComments(text: string): string {
  let out = "";
  let i = 0;
  const keep = (s: string) => { out += s; };
  const blank = (s: string) => { out += s.replace(/[^\n]/g, " "); };
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
        keep(text.slice(i, Math.min(j + 1, text.length)));
        i = j + 1;
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
        keep(text.slice(i, i + 2));
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
        keep(c);
        i++;
      }
    }
  }
  code(false);
  return out;
}

type RuleName = "zero" | "currency" | "money-ratio" | "roas-format";

interface Rule {
  /** Which sources the rule reads (path relative to `src/`, `/` separators). */
  applies: (rel: string) => boolean;
  /** Whether one comment-blanked line is a hit. */
  hit: (line: string) => boolean;
  /** The inline excuse marker, e.g. `ZERO_OK:`. */
  excuse: string;
}

/** `oneRulerPending/` holds `oneRuler.test.ts`'s pending entries — test data quoting the lines it excuses. */
const SOURCES = (rel: string) =>
  (rel.startsWith("components/") || rel.startsWith("lib/")) && !rel.startsWith("lib/guards/") && !rel.startsWith("components/ads/oneRulerPending/");
const ADS = (rel: string) => rel.startsWith("components/ads/");

const ZERO = /(?:\?\?|\|\|)\s*0(?![\w.])/;
const CURRENCY = [
  /(?:NT|US)\$\s?\$?\{/, // `NT$${x}`, `NT$ ${x}` (template), `NT${x}` (JSX text), `US${x}`
  /["'](?:NT|US)\$\s*["']\s*\+/, // "NT$" + x
];
/** A spend／cap operand: an identifier path whose last name ends in spend／cap (`row.spend`, `totalSpend`, `cap`). */
const SPEND_OR_CAP = String.raw`\(?\s*[\w$.?!]*?(?:spend|Spend|cap|Cap)(?![a-z])`;
const MONEY_RATIO = [
  // `a / spend`, `x/ c.cap` — a space on one side tells division from a path string (`"/api/x/spend"`).
  new RegExp(String.raw`[\w)\]]\s+\/\s*${SPEND_OR_CAP}`),
  new RegExp(String.raw`[\w)\]]\/\s+${SPEND_OR_CAP}`),
  /(?:price|Price)\w*\)?\s*\*\s*\(?[\w$.?!]*(?:result|Result|purchase|Purchase)/, // price × results
  /(?:result|Result|purchase|Purchase)\w*\)?\s*\*\s*\(?[\w$.?!]*(?:price|Price)/, // results × price
];
const ROAS_FORMAT = [
  /\bformatMetaRoas\(/,
  /\.roas(?:_conservative)?\b/, // `.roas`, `?.roas_conservative` — not a basis-named key (`.roas_all_spend`)
  /roas\w*\s*\)?\s*\??\.toFixed\(/i, // `roas.toFixed(`, `row.roas_all_spend.toFixed(`, `capRoas.toFixed(`
];

const RULES: Record<RuleName, Rule> = {
  zero: { applies: SOURCES, hit: (line) => ZERO.test(line), excuse: "ZERO_OK:" },
  currency: {
    applies: (rel) => SOURCES(rel) && rel !== "lib/format.ts",
    hit: (line) => CURRENCY.some((p) => p.test(line)),
    excuse: "CURRENCY_OK:",
  },
  "money-ratio": { applies: ADS, hit: (line) => MONEY_RATIO.some((p) => p.test(line)), excuse: "MONEY_RATIO_OK:" },
  "roas-format": { applies: ADS, hit: (line) => ROAS_FORMAT.some((p) => p.test(line)), excuse: "ROAS_FORMAT_OK:" },
};

/** Line numbers (1-based) of `rule`'s hits in `source`, split into excused and not; `strayExcuses` are excuse
 * markers on a line without a hit. */
function scan(rule: RuleName, source: string): { hits: number[]; excused: number[]; strayExcuses: number[] } {
  const { hit, excuse } = RULES[rule];
  const raw = source.split("\n");
  const code = blankComments(source).split("\n");
  const out = { hits: [] as number[], excused: [] as number[], strayExcuses: [] as number[] };
  code.forEach((line, index) => {
    const excused = raw[index]?.includes(excuse) ?? false;
    if (hit(line)) (excused ? out.excused : out.hits).push(index + 1);
    else if (excused) out.strayExcuses.push(index + 1);
  });
  return out;
}

interface AllowEntry { rule: string; file: string }
interface Allowed extends AllowEntry { issue: string }

const ALLOW_MODULES = import.meta.glob<{ default: AllowEntry[] }>("./guards/*.allow.ts", { eager: true });

function allowed(): Allowed[] {
  return Object.entries(ALLOW_MODULES).flatMap(([path, mod]) => {
    const issue = /([^/]+)\.allow\.ts$/.exec(path)?.[1] ?? path;
    return mod.default.map((entry) => ({ ...entry, issue }));
  });
}

function sourceFiles(): { rel: string; source: string }[] {
  return listFiles(SRC_DIR).map((full) => ({
    rel: relative(SRC_DIR, full).split("\\").join("/"),
    source: readFileSync(full, "utf-8"),
  }));
}

function ratchet(rule: RuleName, files: { rel: string; source: string }[], allow: Allowed[]) {
  const listed = new Map(allow.filter((a) => a.rule === rule).map((a) => [a.file, a.issue]));
  const unlisted: string[] = [];
  const stale: string[] = [];
  const stray: string[] = [];
  const seen = new Set<string>();
  for (const { rel, source } of files) {
    if (!RULES[rule].applies(rel)) continue;
    const { hits, strayExcuses } = scan(rule, source);
    if (hits.length) seen.add(rel);
    if (hits.length && !listed.has(rel)) unlisted.push(`${rel}:${hits.join(",")}`);
    for (const line of strayExcuses) stray.push(`${rel}:${line}`);
  }
  for (const [file, issue] of listed) if (!seen.has(file)) stale.push(`${issue}: ${file}`);
  return { unlisted, stale, stray };
}

describe("figure guards (F51 Contract F ratchets)", () => {
  const files = sourceFiles();
  const allow = allowed();

  for (const rule of ["zero", "currency", "money-ratio", "roas-format"] as const) {
    it(`${rule}: every hit is in a file an F51 issue still lists, or excused inline`, () => {
      expect(ratchet(rule, files, allow).unlisted).toEqual([]);
    });
    it(`${rule}: every listed file still hits (the issue that cleaned it deletes its entry)`, () => {
      expect(ratchet(rule, files, allow).stale).toEqual([]);
    });
    it(`${rule}: every inline excuse sits on a hit`, () => {
      expect(ratchet(rule, files, allow).stray).toEqual([]);
    });
  }

  it("the shared pieces are clean (layout, lib/figures, lib/format)", () => {
    const shared = (rel: string) => rel.startsWith("components/layout/") || rel === "lib/figures.ts" || rel === "lib/format.ts";
    const dirty = files.filter((f) => shared(f.rel)).flatMap((f) =>
      (Object.keys(RULES) as RuleName[]).filter((r) => RULES[r].applies(f.rel) && scan(r, f.source).hits.length).map((r) => `${r} ${f.rel}`));
    expect(dirty).toEqual([]);
  });

  it("the zero scan sees ?? 0 and || 0, and leaves other numbers alone", () => {
    const lines = (src: string) => scan("zero", src).hits;
    expect(lines("const s = row.spend ?? 0;")).toEqual([1]);
    expect(lines("total += x.results || 0;")).toEqual([1]);
    expect(lines("const a = b ?? 0.5;\nconst c = d ?? 10;\nconst e = f ?? 0x1;")).toEqual([]);
    expect(lines("const a = b ?? null; // was ?? 0")).toEqual([]);
    expect(scan("zero", "const w = width ?? 0; // ZERO_OK: a layout width, not a figure").excused).toEqual([1]);
    expect(scan("zero", "const w = 1; // ZERO_OK: nothing").strayExcuses).toEqual([1]);
    expect(RULES.zero.applies("components/ads/oneRulerPending/F51-I09.ts")).toBe(false);
    expect(RULES.zero.applies("lib/guards/F51-I09.allow.ts")).toBe(false);
  });

  it("the currency scan sees interpolated NT$／US$ prefixes and leaves the formatter and plain words alone", () => {
    const lines = (src: string) => scan("currency", src).hits;
    expect(lines("const t = `NT$${amount}`;")).toEqual([1]);
    expect(lines("const t = `NT$ ${amount}`;")).toEqual([1]);
    expect(lines("<b>NT${formatAmount(cap)}</b>")).toEqual([1]);
    expect(lines("const u = `US$${cost}`;\nconst v = \"NT$\" + x;")).toEqual([1, 2]);
    expect(lines("const m = formatMoney(v, currency);\nconst label = \"幣別 NT$\";")).toEqual([]);
    expect(RULES.currency.applies("lib/format.ts")).toBe(false);
  });

  it("the money-ratio scan sees division by spend／cap and price × results, and leaves paths and other math alone", () => {
    const lines = (src: string) => scan("money-ratio", src).hits;
    expect(lines("const roas = revenue / spend;")).toEqual([1]);
    expect(lines("const r = (price / c.cap).toFixed(1);")).toEqual([1]);
    expect(lines("const r = sales / row.totalSpend;")).toEqual([1]);
    expect(lines("const est = price * purchases;\nconst e2 = results * unitPrice;")).toEqual([1, 2]);
    expect(lines("const url = `/api/brands/${b}/spend`;\nconst p = \"/api/x/cap\";")).toEqual([]);
    expect(lines("const pct = done / total;\nconst w = width / 2;\nconst c = caption / 2;")).toEqual([]);
    expect(RULES["money-ratio"].applies("components/cockpit/X.tsx")).toBe(false);
    expect(RULES["money-ratio"].applies("lib/figures.ts")).toBe(false);
  });

  it("the roas-format scan sees formatMetaRoas, .toFixed on a ROAS and bare .roas reads, not basis-named keys", () => {
    const lines = (src: string) => scan("roas-format", src).hits;
    expect(lines("<td>{formatMetaRoas(row.roas_platform)}</td>")).toEqual([1]);
    expect(lines("const a = totals.roas;\nconst b = x?.roas_conservative;")).toEqual([1, 2]);
    expect(lines("const t = roas.toFixed(2);\nconst u = capRoas.toFixed(1);")).toEqual([1, 2]);
    expect(lines("const v = row.roas_all_spend;\n<Figure basis=\"roas_all_spend\" value={v} />")).toEqual([]);
    expect(RULES["roas-format"].applies("components/cockpit/X.tsx")).toBe(false);
  });
});
