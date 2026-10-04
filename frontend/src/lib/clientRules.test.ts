/** F50 Contract I／R (audit W12／W13, decision 11) — static falsifier: the browser keeps no input rule of its own.
 * Backend twin: `app/tests/test_input_rules_gate.py`. The rule table is `app/core/input_rules.py`; a screen sends what
 * was typed (`lib/typedNumber.ts`) and prints the server's sentence. Every non-test source under
 * `components/intake`, `components/products` and `components/settings` is read with comments blanked out (line numbers
 * kept), and each hit names its file and line:
 *
 * 1. `money_literal` — a money／rate-named value compared with a literal 0, 1 or 100 (`price <= 0`, `0 < closeRate`):
 *    the bound is the server's (`positive`／`non_negative`／`percent`／`count`).
 * 2. `rate_scale` — a rate／margin／percent value multiplied or divided by 100: the stored scale is 0–100 and the
 *    one multiplier is the server's `rate_fraction`.
 * 3. `length_ready` — readiness derived from a list length into `ok`／`ready` (`ok: groups.length > 0`): readiness is
 *    served (`product_readiness`, `status().checklist`).
 * 4. `number_cast` — `Number(` outside `lib/typedNumber.ts`: a typed string is sent as typed (`typedValue`), the server
 *    parses and refuses; `Number("")` is 0, which is how a blank field used to be saved as 0.
 *
 * Ratchet (F48's pattern): `PENDING` lists today's hits with the issue that removes them. A hit not listed fails; a
 * listed entry the scan no longer finds is stale and fails, so the list only shrinks. `NOT_INPUT` is permanent: a hit
 * that does not read a typed field, with the reason. Never add an entry to hide a new hit. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCANNED = ["components/intake", "components/products", "components/settings"];

type Rule = "money_literal" | "rate_scale" | "length_ready" | "number_cast";

const MONEY = String.raw`[A-Za-z_]*(?:[Pp]rice|[Cc]ost|[Ss]hipping|[Bb]udget|[Rr]evenue|cap_per_sale|[Cc]apPerSale|[Qq]uantity|[Qq]ty|close_rate|[Cc]loseRate|[Mm]argin)[A-Za-z_]*`;

export const RULES: Record<Rule, RegExp[]> = {
  money_literal: [
    new RegExp(String.raw`\b${MONEY}\??\s*(?:<=|>=|<|>)\s*(?:0|1|100)(?![\d.])`),
    new RegExp(String.raw`(?<![\w.])(?:0|1|100)\s*(?:<=|>=|<|>)\s*(?:[\w.]*\.)?${MONEY}`),
  ],
  rate_scale: [
    /(?:[Rr]ate|[Mm]argin|[Pp]ercent|[Pp]ct)\w*(?:\.\w+)*\)?\s*[*/]\s*100\b/,
    /\b100\s*\*\s*\(?[\w.]*(?:[Rr]ate|[Mm]argin|[Pp]ercent|[Pp]ct)/,
  ],
  length_ready: [/\b(?:ok|ready)\b\s*[:=]\s*[^,;\n]*\.length\b/],
  number_cast: [/\bNumber\(/],
};

interface Pending { file: string; rule: Rule; text: string; issue: string }

/** Today's hits (file relative to `src/`, the trimmed line) with the issue that removes each: the sell-way editors,
 * the economics panel and the rule cards move to the server's percent scale and sentences in F50-I04; the product
 * done page reads the served checklist in F50-I15. */
const PENDING: Pending[] = [
  { file: "components/intake/product/ProductDoneStep.tsx", rule: "length_ready", issue: "F50-I15",
    text: '{ step: 1, ok: saved(1) && whatParts.length > 0, label: "商品是什麼", detail: whatParts.join("、") },' },
  { file: "components/intake/product/ProductDoneStep.tsx", rule: "length_ready", issue: "F50-I15",
    text: "ok: saved(2) && groups.length > 0," },
  { file: "components/intake/product/ProductDoneStep.tsx", rule: "length_ready", issue: "F50-I15",
    text: "ok: saved(3) && proof.length + claims.length > 0," },
  { file: "components/intake/product/ProductDoneStep.tsx", rule: "length_ready", issue: "F50-I15",
    text: '{ step: 4, ok: saved(4) && ways.length > 0, label: `賣法 ${ways.length} 種`, detail: ways.map(sellWayText).join("・") },' },
  { file: "components/intake/product/SellWayContents.tsx", rule: "number_cast", issue: "F50-I04",
    text: "export const qtyOf = (raw: string): number | null => (/^\\d+$/.test(raw.trim()) && Number(raw) > 0 ? Number(raw) : null);" },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "rate_scale", issue: "F50-I04",
    text: 'if (field === "close_rate" && bm.close_rate) value = String(Number((bm.close_rate.value * 100).toFixed(2)));' },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "number_cast", issue: "F50-I04",
    text: 'if (field === "close_rate" && bm.close_rate) value = String(Number((bm.close_rate.value * 100).toFixed(2)));' },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "number_cast", issue: "F50-I04",
    text: "const price = Number(r.draft.price);" },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "money_literal", issue: "F50-I04",
    text: 'if (r.shape === "composed" || !(price > 0)) return r;' },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "number_cast", issue: "F50-I04",
    text: "price: b.server?.price ?? (Number(b.draft.price) > 0 ? Number(b.draft.price) : null)," },
  { file: "components/intake/product/SellWaysStep.tsx", rule: "number_cast", issue: "F50-I04",
    text: 'cost: b.server?.cost ?? (b.draft.cost.trim() !== "" && Number(b.draft.cost) >= 0 ? Number(b.draft.cost) : null),' },
  { file: "components/intake/product/SellWayTable.tsx", rule: "number_cast", issue: "F50-I04",
    text: "const n = Number(t);" },
  { file: "components/intake/product/SellWayTable.tsx", rule: "rate_scale", issue: "F50-I04",
    text: 'rate == null ? "" : String(Number((rate * 100).toFixed(2)));' },
  { file: "components/intake/product/SellWayTable.tsx", rule: "number_cast", issue: "F50-I04",
    text: 'rate == null ? "" : String(Number((rate * 100).toFixed(2)));' },
  { file: "components/intake/product/SellWayTable.tsx", rule: "money_literal", issue: "F50-I04",
    text: '} else if (Number.isNaN(price) || price <= 0) out.price = "售價要大於 0";' },
  { file: "components/intake/product/SellWayTable.tsx", rule: "rate_scale", issue: "F50-I04",
    text: "if (showCloseRate) input.close_rate = rate === null ? null : Number((rate / 100).toFixed(4));" },
  { file: "components/intake/product/SellWayTable.tsx", rule: "number_cast", issue: "F50-I04",
    text: "if (showCloseRate) input.close_rate = rate === null ? null : Number((rate / 100).toFixed(4));" },
  { file: "components/products/panels/EconomicsPanel.tsx", rule: "number_cast", issue: "F50-I04",
    text: 'return raw.trim() === "" ? null : Number(raw);' },
  { file: "components/settings/RuleCardsSection.tsx", rule: "number_cast", issue: "F50-I04",
    text: 'for (const [key, raw] of Object.entries(values)) if (raw.trim() !== "") typed[key] = Number(raw);' },
];

/** Permanent: hits that do not read a typed field, with the reason (a stale entry still fails). */
const NOT_INPUT: { file: string; rule: Rule; text: string; why: string }[] = [
  { file: "components/intake/IntakeWizard.tsx", rule: "number_cast", text: "const n = Number(raw);",
    why: "reads the `?step=` URL parameter (which wizard step to open), not a typed field" },
  { file: "components/intake/product/ProductOnboarding.tsx", rule: "number_cast", text: "const n = Number(raw);",
    why: "reads the `?step=` URL parameter (which onboarding step to open), not a typed field" },
];

/** The source with every comment replaced by spaces (newlines kept, so line numbers hold). A `//` inside a string or
 * a URL is not a comment. */
export function blankComments(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const c = text[i], n = text[i + 1];
    if (c === "/" && n === "/") {
      const e = text.indexOf("\n", i);
      const stop = e === -1 ? text.length : e;
      out += " ".repeat(stop - i);
      i = stop;
    } else if (c === "/" && n === "*") {
      const e = text.indexOf("*/", i + 2);
      const stop = e === -1 ? text.length : e + 2;
      out += text.slice(i, stop).replace(/[^\n]/g, " ");
      i = stop;
    } else if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      while (j < text.length && text[j] !== c && (c === "`" || text[j] !== "\n")) j += text[j] === "\\" ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j + 1;
    } else {
      out += c;
      i++;
    }
  }
  return out;
}

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...sources(full));
    } else if (/\.tsx?$/.test(name) && !/\.(test|stories)\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

export function scanText(source: string): { rule: Rule; line: number; text: string }[] {
  const hits: { rule: Rule; line: number; text: string }[] = [];
  blankComments(source).split("\n").forEach((code, index) => {
    for (const [rule, patterns] of Object.entries(RULES) as [Rule, RegExp[]][]) {
      if (patterns.some((re) => re.test(code))) hits.push({ rule, line: index + 1, text: code.trim() });
    }
  });
  return hits;
}

function scan(): { file: string; rule: Rule; line: number; text: string }[] {
  return SCANNED.flatMap((dir) => sources(join(SRC_DIR, dir))).flatMap((full) => {
    const file = relative(SRC_DIR, full).split("\\").join("/");
    return scanText(readFileSync(full, "utf8")).map((hit) => ({ file, ...hit }));
  });
}

const key = (h: { file: string; rule: Rule; text: string }) => `${h.file} [${h.rule}] ${h.text}`;

describe("clientRules — the browser keeps no input rule (F50 Contract I／R)", () => {
  it("no unlisted hit", () => {
    const listed = new Set([...PENDING, ...NOT_INPUT].map(key));
    const unlisted = scan().filter((h) => !listed.has(key(h))).map((h) => `${h.file}:${h.line} [${h.rule}] ${h.text}`);
    expect(unlisted).toEqual([]);
  });

  it("no stale PENDING entry", () => {
    const found = new Set(scan().map(key));
    expect(PENDING.filter((p) => !found.has(key(p))).map((p) => `${key(p)} (${p.issue})`)).toEqual([]);
    expect(NOT_INPUT.filter((p) => !found.has(key(p))).map((p) => `${key(p)} (${p.why})`)).toEqual([]);
  });

  it("every PENDING entry names an issue and every NOT_INPUT entry a reason", () => {
    for (const p of PENDING) expect(p.issue).toMatch(/^F\d+-I\d+$/);
    for (const p of NOT_INPUT) expect(p.why.trim()).not.toBe("");
  });

  it("the scan sees each shape", () => {
    const sample = [
      "if (price <= 0) return;",
      "const bad = 0 < form.closeRate;",
      "const pct = closeRate * 100;",
      "const shown = row.margin_rate / 100;",
      "const s = { ok: groups.length > 0 };",
      "save(Number(text));",
      "// price <= 0 in a comment is not code",
      "const fine = price.toFixed(0);",
    ].join("\n");
    expect(scanText(sample).map((h) => h.rule)).toEqual([
      "money_literal", "money_literal", "rate_scale", "rate_scale", "length_ready", "number_cast",
    ]);
  });
});
