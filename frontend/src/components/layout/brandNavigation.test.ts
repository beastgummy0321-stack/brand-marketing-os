import { describe, expect, it } from "vitest";
import { brandDestination } from "./brandNavigation";

describe("switch brand", () => {
  it.each(["ads/campaigns/old", "ads/new/draft", "workbench/packs/old/sets/old", "products/old", "orders/old"])("drops resource identifiers from %s", (path) => {
    expect(brandDestination("new", `/brands/old/${path}`, "?tab=structure&ad=old")).toBe(`/brands/new/${path.split("/")[0]}`);
  });
  it("retains only the library category", () => {
    expect(brandDestination("new", "/brands/old/library", "?tab=customer-voice&product=old")).toBe("/brands/new/library?tab=customer-voice");
  });
  it("leaves brand-specific intake state", () => {
    expect(brandDestination("new", "/brands/old/intake/history", "?id=old")).toBe("/brands/new");
  });
});
