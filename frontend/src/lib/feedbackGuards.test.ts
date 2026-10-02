/** F47-I02 (feature F47 Contract B): two repo-wide guards for "one way to give feedback".
 *
 * 1. A failed response becomes a sentence in one place. A `src/lib/*.ts` file that throws a
 *    「…（狀態碼 N）」 message straight away drops the sentence the server sent (drill-10 V2: the AI
 *    limit and rule-card saves showed 「儲存失敗（狀態碼 400）」 while the server said why). Such a
 *    text may exist only as the fallback handed to `throwIfFailed` / `errorMessageFromResponse` /
 *    `errorMessageFrom` (or a file-local wrapper that passes it on).
 * 2. Copy feedback lives in two components. `navigator.clipboard` outside `CopyIconButton` and
 *    `ads/patterns/CopyField` is a hand-rolled copy that has, every time so far, given no visible
 *    feedback (drill-10 publish step 2, prompts, invite link). Test files may stub it. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(LIB_DIR, "..");

/** Calls that take a fallback and read the server's sentence first. `extractError` / `readOrThrow`
 * are file-local wrappers (intakeApi / metaApi) that forward to `errorMessageFromResponse`. */
const ROUTED = /\b(throwIfFailed|errorMessageFromResponse|errorMessageFrom|extractError|readOrThrow)\(/;

/** Direct status-code throws that predate this guard and live in files outside F47-I02's touch
 * (scheduleApi is do_not_touch). Each is a read helper's `getJson` turning any non-404 failure into
 * 「讀取失敗（狀態碼 N）」. Shrink-only: fix the file, then delete its entry — the test below fails
 * when an entry no longer matches anything, so a fixed file cannot stay listed. */
const KNOWN_DIRECT_THROWS: Record<string, number> = {
  "intakeApi.ts": 1,
  "intakeT2Api.ts": 1,
  "ordersApi.ts": 1,
  "productsApi.ts": 1,
  "scheduleApi.ts": 1,
};

function listFiles(dir: string, recurse: boolean): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (recurse) out.push(...listFiles(full, true));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.(test|stories)\.tsx?$/.test(name)) continue;
    out.push(full);
  }
  return out;
}

/** Every `throw new Error(…)` argument in `source`, matched by paren depth (they span lines). */
function thrownArguments(source: string): string[] {
  const out: string[] = [];
  const marker = "throw new Error(";
  let at = source.indexOf(marker);
  while (at !== -1) {
    let depth = 1;
    let i = at + marker.length;
    for (; i < source.length && depth > 0; i++) {
      if (source[i] === "(") depth++;
      else if (source[i] === ")") depth--;
    }
    out.push(source.slice(at + marker.length, i - 1));
    at = source.indexOf(marker, i);
  }
  return out;
}

function directStatusThrows(source: string): number {
  return thrownArguments(source).filter((arg) => arg.includes("狀態碼") && !ROUTED.test(arg)).length;
}

function clipboardOffenders(files: { rel: string; source: string }[]): string[] {
  const allowed = new Set(["components/layout/CopyIconButton.tsx", "components/ads/patterns/CopyField.tsx"]);
  return files.filter((f) => !allowed.has(f.rel) && f.source.includes("navigator.clipboard")).map((f) => f.rel);
}

describe("feedback guards (F47 Contract B)", () => {
  it("no src/lib/*.ts file throws a 「（狀態碼 N）」 message without routing it through the helper", () => {
    const found: Record<string, number> = {};
    for (const full of listFiles(LIB_DIR, false)) {
      const count = directStatusThrows(readFileSync(full, "utf-8"));
      if (count) found[relative(LIB_DIR, full).split("\\").join("/")] = count;
    }
    expect(found).toEqual(KNOWN_DIRECT_THROWS);
  });

  it("navigator.clipboard is only called inside CopyIconButton and CopyField", () => {
    const files = listFiles(SRC_DIR, true).map((full) => ({
      rel: relative(SRC_DIR, full).split("\\").join("/"),
      source: readFileSync(full, "utf-8"),
    }));
    expect(clipboardOffenders(files)).toEqual([]);
  });

  it("the detectors see what they are meant to see", () => {
    expect(directStatusThrows("throw new Error(`儲存失敗（狀態碼 ${res.status}）`);")).toBe(1);
    expect(directStatusThrows("throw new Error(\n  a ? \"x\" : `讀取失敗（狀態碼 ${s}）`,\n);")).toBe(1);
    expect(directStatusThrows("throw new Error(await errorMessageFromResponse(res, `處理失敗（狀態碼 ${s}）`));")).toBe(0);
    expect(directStatusThrows("await throwIfFailed(res, `讀取失敗（狀態碼 ${res.status}）`);")).toBe(0);
    expect(clipboardOffenders([{ rel: "components/x/Y.tsx", source: "navigator.clipboard.writeText(t)" }])).toEqual([
      "components/x/Y.tsx",
    ]);
  });
});
