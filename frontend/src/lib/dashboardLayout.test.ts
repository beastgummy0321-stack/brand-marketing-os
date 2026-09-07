import { describe, expect, it } from "vitest";
import {
  defaultLayout,
  layoutKey,
  parseLayout,
  reorderWidgets,
} from "./dashboardLayout";
describe("scoped dashboard preferences", () => {
  it("isolates every user, organization and brand, including separator characters", () => {
    expect(
      new Set([
        layoutKey("u", "o", "b"),
        layoutKey("u2", "o", "b"),
        layoutKey("u", "o2", "b"),
        layoutKey("u", "o", "b2"),
        layoutKey("u:o", "b", "x"),
        layoutKey("u", "o:b", "x"),
      ]).size,
    ).toBe(6);
  });
  it("recovers malformed, outdated and entirely empty saved layouts", () => {
    for (const raw of [
      null,
      "{",
      JSON.stringify({ version: 2, views: [] }),
      JSON.stringify({
        version: 1,
        views: [{ id: "x", name: "", metrics: [], widgets: [] }],
      }),
    ])
      expect(parseLayout(raw)).toEqual(defaultLayout());
  });
  it("drops unknown and duplicate widgets and repairs the active view", () => {
    const layout = parseLayout(
      JSON.stringify({
        version: 1,
        activeId: "removed",
        views: [
          {
            id: "mine",
            name: " 成效 ",
            metrics: ["spend", "followers"],
            widgets: [
              { id: "inbox", width: "half" },
              { id: "inbox", width: "full" },
              { id: "reels", width: "half" },
              { id: "spend", width: "invalid" },
            ],
          },
        ],
      }),
    );
    expect(layout.activeId).toBe("mine");
    expect(layout.views[0]).toEqual({
      id: "mine",
      name: "成效",
      metrics: ["spend"],
      widgets: [{ id: "inbox", width: "half" }],
    });
  });
  it("reorders a widget without mutating or losing its width", () => {
    const original = defaultLayout().views[0];
    const next = reorderWidgets(original, "inbox", "spend");
    expect(next.widgets[0]).toEqual({ id: "inbox", width: "narrow" });
    expect(original.widgets[0].id).toBe("spend");
    expect(reorderWidgets(original, "commerce", "inbox")).toBe(original);
  });
});
