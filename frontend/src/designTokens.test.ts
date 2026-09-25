// docs/design-system.md §2 / §9: raw colours and font families live in tokens.css only
// (chartColors.ts mirrors the chart palette for canvas). Proven red 2026-09-07 by adding
// `color: "#123456"` to a component and watching it fail.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);
const ALLOWED_HEX = new Set(["lib/chartColors.ts"]);
const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const FONT_FAMILY = /font-family\s*:|fontFamily\s*:/;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(ts|tsx)$/.test(name) && !/\.(test|stories)\.tsx?$/.test(name) ? [full] : [];
  });
}

describe("design tokens are the only colour and font source", () => {
  const files = sources(SRC).map((f) => [relative(SRC, f).replace(/\\/g, "/"), f] as const);

  it("no raw hex colour outside tokens.css and chartColors.ts", () => {
    const offenders = files
      .filter(([rel]) => !ALLOWED_HEX.has(rel))
      .flatMap(([rel, full]) =>
        readFileSync(full, "utf8")
          .split("\n")
          .flatMap((line, i) => (line.match(HEX) ? [`${rel}:${i + 1}: ${line.trim()}`] : [])),
      );
    expect(offenders).toEqual([]);
  });

  it("v10 strong text shades are tokens (F29-I09: 有賺／對上了, 不一樣)", () => {
    const css = readFileSync(join(SRC, "styles/tokens.css"), "utf8");
    expect(css).toMatch(/--color-success-strong:\s*#1d6e59;/);
    expect(css).toMatch(/--color-warning-strong:\s*#8f560d;/);
  });

  it("no font-family outside tokens.css", () => {
    const offenders = files
      .filter(([, full]) => FONT_FAMILY.test(readFileSync(full, "utf8")))
      .map(([rel]) => rel);
    expect(offenders).toEqual([]);
  });
});
