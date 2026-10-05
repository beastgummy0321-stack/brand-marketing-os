/** F51 Contract F: the one browser money ratio (`roasAtCap`, rounded once), imported rows' ROAS (`roasOf`) and
 * value formatting by basis unit — unknown stays `null`, never 0. */
import { describe, expect, it } from "vitest";
import { formatFigure, roasAtCap, roasOf } from "./figures";

describe("roasAtCap", () => {
  it("is price ÷ cap rounded once to 2 decimals", () => {
    expect(roasAtCap(999, 450)).toBe(2.22);
    expect(roasAtCap(1000, 300)).toBe(3.33);
    expect(roasAtCap(1001, 600)).toBe(1.67); // 1.66833… rounds up
    expect(roasAtCap(450, 450)).toBe(1);
  });

  it("is null when the price or cap is unknown or the cap is not positive", () => {
    expect(roasAtCap(null, 450)).toBeNull();
    expect(roasAtCap(999, null)).toBeNull();
    expect(roasAtCap(999, 0)).toBeNull();
    expect(roasAtCap(999, -1)).toBeNull();
    expect(roasAtCap(Number.NaN, 450)).toBeNull();
  });
});

describe("roasOf", () => {
  it("is revenue ÷ spend of imported rows, null when revenue is untracked or spend is unknown／zero", () => {
    expect(roasOf(2450, 1000)).toBeCloseTo(2.45);
    expect(roasOf(0, 1000)).toBe(0);
    expect(roasOf(null, 1000)).toBeNull();
    expect(roasOf(2450, null)).toBeNull();
    expect(roasOf(2450, 0)).toBeNull();
  });
});

describe("formatFigure", () => {
  it("prints a ratio as 2.10x, money with its currency, a count with separators", () => {
    expect(formatFigure("ratio", 2.1)).toBe("2.10x");
    expect(formatFigure("money", 12345.6, "TWD")).toBe("12,346 TWD");
    expect(formatFigure("count", 12345)).toBe("12,345");
  });
});
