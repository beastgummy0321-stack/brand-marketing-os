/** 前端版 `app/tests/test_architecture_boundaries.py::FileLineCapTest`
 * （BOARD.md ③，2026-09-04）。跟後端的 `KNOWN_OVERSIZED_FILES` 同一個形狀：
 * 凍結現況的超標檔，只准變小，新的超標檔一律擋下。 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SRC_DIR, "..", "..");

const FILE_LINE_CAP = 800;
const KNOWN_OVERSIZED_FILES: Record<string, number> = {
  "frontend/src/components/schedule/SchedulePage.tsx": 851,
};

function listSourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...listSourceFiles(full));
      continue;
    }
    if (!/\.tsx?$/.test(name)) continue;
    if (/\.(test|stories)\.tsx?$/.test(name)) continue;
    out.push(full);
  }
  return out;
}

function lineCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const full of listSourceFiles(SRC_DIR)) {
    const rel = relative(REPO_ROOT, full).split("\\").join("/");
    const lines = readFileSync(full, "utf-8").split("\n");
    // Python 的 splitlines()（後端那支對應測試用的）遇到結尾換行不會多算一個空字串，
    // 這裡跟著丟掉最後那個空字串，行數才會跟 `wc -l`／編輯器上看到的一致，不是 split() 的原始長度。
    if (lines[lines.length - 1] === "") lines.pop();
    counts[rel] = lines.length;
  }
  return counts;
}

describe("FileLineCapTest (frontend)", () => {
  it("no file grows past its frozen size", () => {
    const problems: string[] = [];
    for (const [rel, count] of Object.entries(lineCounts()).sort()) {
      if (count <= FILE_LINE_CAP) continue;
      const frozen = KNOWN_OVERSIZED_FILES[rel];
      if (frozen === undefined) {
        problems.push(`  ${rel}：${count} 行，新超過 ${FILE_LINE_CAP} 行上限——先拆再加`);
      } else if (count > frozen) {
        problems.push(`  ${rel}：${count} 行，比凍結值 ${frozen} 大——只准變小`);
      }
    }
    expect(problems, `單檔行數違規：\n${problems.join("\n")}`).toEqual([]);
  });

  it("KNOWN_OVERSIZED_FILES 沒有過期的項目", () => {
    const counts = lineCounts();
    const stale = Object.keys(KNOWN_OVERSIZED_FILES)
      .filter((rel) => (counts[rel] ?? 0) <= FILE_LINE_CAP)
      .sort();
    expect(
      stale,
      `以下檔案已經拆到上限以下，請從 KNOWN_OVERSIZED_FILES 劃掉：\n${stale.join("\n")}`,
    ).toEqual([]);
  });
});
