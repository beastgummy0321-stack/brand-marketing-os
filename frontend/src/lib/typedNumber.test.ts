import { describe, expect, it } from "vitest";
import { typedValue } from "./typedNumber";

describe("typedValue — send what was typed (F50 Contract I)", () => {
  it("a blank field is null, never 0", () => {
    expect(typedValue("")).toBeNull();
    expect(typedValue("   ")).toBeNull();
  });

  it("typed text is sent trimmed and unparsed — the server parses and refuses", () => {
    expect(typedValue(" 30 ")).toBe("30");
    expect(typedValue("1,200")).toBe("1,200");
    expect(typedValue("-5")).toBe("-5");
    expect(typedValue("abc")).toBe("abc");
    expect(typedValue("0")).toBe("0");
  });
});
