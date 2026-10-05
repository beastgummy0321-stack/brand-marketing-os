/** F50-I12 (feature F50 Contract K, audit W11): the frontend half of "one clock".
 *
 * Root cause this guards: a screen that builds its own `Date` prints the viewer's zone and counts days from the
 * laptop's clock, so 「7 天後」, 「M/D 再看」 and every 「HH:MM」 stamp drifted from the organisation's calendar the
 * backend judges by. `lib/orgClock.ts` is the only module that may build or read a `Date`; everything under
 * `components/**` and `lib/**` formats instants with `formatInstant(…, clock.timezone, …)` and does day arithmetic on
 * `YYYY-MM-DD` strings. `formatSyncTime` (a browser-zone formatter in `lib/format.ts`) counts as a hit too.
 *
 * Excuses: an elapsed-seconds counter may keep `Date.now()` with `ELAPSED_OK: <reason>` on the same line. The
 * allowlist is a ratchet (F48 stale-entry pattern): each entry names the issue that removes it, and an entry whose
 * file no longer has a hit fails, so the list only shrinks. Test files are not scanned (fixtures and fake timers
 * build instants on purpose). */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(LIB_DIR, "..");

const PATTERNS: { name: string; re: RegExp }[] = [
  { name: "new Date(", re: /\bnew Date\(/ },
  { name: "Date.now(", re: /\bDate\.now\(/ },
  { name: "Date.parse(", re: /\bDate\.parse\(/ },
  { name: "local date getter", re: /\.(getHours|getMonth|getDate|getFullYear|setDate)\(/ },
  { name: "toLocaleDateString／toLocaleTimeString", re: /\btoLocale(Date|Time)String\b/ },
  { name: "_at sliced to a date", re: /_at\b[^\n]*?\.slice\(0,\s*10\)/ },
  { name: "formatSyncTime(", re: /\bformatSyncTime\(/ },
];

const EXCUSE = /ELAPSED_OK:\s*\S/;

/** Files outside the ads centre that still build dates today; F50-I14 moves them onto the org clock. */
const ALLOWLIST: Record<string, string> = {
  "components/inbox/InboxItemCard.tsx": "F50-I14",
  "components/intake/HistoryPage.tsx": "F50-I14",
  "components/intake/shared/IntakeJobRow.tsx": "F50-I14",
  "components/intake/steps/ScanStep.tsx": "F50-I14",
  "components/layout/ActiveJobsBell.tsx": "F50-I14",
  "components/layout/Topbar.tsx": "F50-I14",
  "components/library/tabs/FactsTab.tsx": "F50-I14",
  "components/products/ProductDetailPage.tsx": "F50-I14",
  "components/products/shared/ResearchProgressRow.tsx": "F50-I14",
  "components/products/tabs/FactsTab.tsx": "F50-I14",
  "components/workbench/FreeJobPage.tsx": "F50-I14",
  "components/workbench/PackPage.tsx": "F50-I14",
  "components/workbench/WorkbenchHomePage.tsx": "F50-I14",
  "lib/format.ts": "F50-I14",
  "lib/http.ts": "F50-I14",
};

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

/** `line:pattern` for every clock hit in `source`; comment lines and lines carrying an `ELAPSED_OK:` reason skip. */
export function clockHits(source: string): string[] {
  const hits: string[] = [];
  source.split("\n").forEach((line, index) => {
    const code = line.trim();
    if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
    if (EXCUSE.test(line)) return;
    for (const { name, re } of PATTERNS) if (re.test(line)) hits.push(`${index + 1}:${name}`);
  });
  return hits;
}

function scanned(): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  for (const top of ["components", "lib"]) {
    for (const full of listFiles(join(SRC_DIR, top))) {
      const rel = relative(SRC_DIR, full).split("\\").join("/");
      if (rel === "lib/orgClock.ts") continue;
      const hits = clockHits(readFileSync(full, "utf-8"));
      if (hits.length) found[rel] = hits;
    }
  }
  return found;
}

describe("clock guards (F50 Contract K)", () => {
  it("the detector fails on a planted clock read and honours only a reasoned ELAPSED_OK excuse", () => {
    expect(clockHits("const d = new Date();")).toEqual(["1:new Date("]);
    expect(clockHits("x\nconst m = at.getMonth() + 1;")).toEqual(["2:local date getter"]);
    expect(clockHits("const day = row.created_at.slice(0, 10);")).toEqual(["1:_at sliced to a date"]);
    expect(clockHits("return formatSyncTime(iso);")).toEqual(["1:formatSyncTime("]);
    expect(clockHits("const t = Date.now(); // ELAPSED_OK: waited-seconds counter")).toEqual([]);
    expect(clockHits("const t = Date.now(); // ELAPSED_OK")).toEqual(["1:Date.now("]);
    expect(clockHits("// new Date() in a comment")).toEqual([]);
  });

  it("only lib/orgClock.ts builds dates outside the allowlist", () => {
    const offenders = Object.keys(scanned()).filter((rel) => !(rel in ALLOWLIST));
    expect(offenders).toEqual([]);
  });

  it("every allowlist entry still has a hit and names the issue that removes it (stale entries fail)", () => {
    const found = scanned();
    const stale = Object.keys(ALLOWLIST).filter((rel) => !found[rel]);
    expect(stale).toEqual([]);
    for (const issue of Object.values(ALLOWLIST)) expect(issue).toMatch(/^F\d+-I\d+$/);
  });
});
