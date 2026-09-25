/** F29-I01 static falsifier for ads.md §6.33 "One ruler": every judgement on the ads screens uses
 * the cap grade (`grade`) or the row kind (`kind_key`); the trend `class` is a footnote no screen
 * decides with. Scans every non-test source under `components/ads` (and the `lib/ads*` read
 * modules) for a comparison against `.class` — `x.class === …`, `… !== y.class`, a `switch
 * (x.class)` or a `["class"]` read — and names the file and line of each. Mirrors the backend
 * `app/tests/test_ads_one_ruler.py`. */
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

function sources(dir: string, keep: (name: string) => boolean): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...sources(full, keep));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.(test|stories)\.tsx?$/.test(name) || !keep(name)) continue;
    out.push(full);
  }
  return out;
}

function classComparisons(text: string): number[] {
  const lines: number[] = [];
  text.split("\n").forEach((line, index) => {
    const code = line.replace(/\/\/.*$/, "");
    if (CLASS_COMPARE.some((pattern) => pattern.test(code))) lines.push(index + 1);
  });
  return lines;
}

describe("one ruler (ads.md §6.33)", () => {
  it("no ads screen decides with the trend `class`", () => {
    const files = [
      ...sources(ADS_DIR, () => true),
      ...sources(LIB_DIR, (name) => name.startsWith("ads")),
    ];
    expect(files.length).toBeGreaterThan(20);
    const offenders = files.flatMap((full) =>
      classComparisons(readFileSync(full, "utf-8")).map(
        (line) => `${relative(SRC_DIR, full).split("\\").join("/")}:${line}`,
      ),
    );
    expect(offenders).toEqual([]);
  });

  it("the scan sees every comparison shape and ignores other uses of the word", () => {
    expect(classComparisons('if (item.class === "worse") x();')).toEqual([1]);
    expect(classComparisons('const a = "flat" !== item.triage.class;')).toEqual([1]);
    expect(classComparisons("switch (row.triage.class) {}")).toEqual([1]);
    expect(classComparisons('const c = item["class"];')).toEqual([1]);
    expect(classComparisons('<div className="p-2" />')).toEqual([]);
    expect(classComparisons('const t = { class: "flat" };')).toEqual([]);
    expect(classComparisons('// was: item.class === "worse"')).toEqual([]);
  });
});
