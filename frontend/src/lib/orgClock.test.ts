/** F36-I08 (Contract U): the org clock must answer from the org's timezone, not the machine's.
 * Kiritimati (UTC+14) and Pago Pago (UTC-11) sit on opposite sides of the date line, so at a
 * fixed instant they are on different calendar days — the one case a browser-clock helper
 * cannot pass. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import {
  DEFAULT_ORG_TIMEZONE,
  addDays,
  dayList,
  daysBetween,
  formatDay,
  formatInstant,
  orgDateOf,
  orgDateShift,
  shiftMonth,
  orgToday,
  resolveOrgTimezone,
  useOrgClock,
} from "@/lib/orgClock";

const mockUseWorkspace = vi.fn();
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => mockUseWorkspace(),
}));

// 2026-03-01 05:00Z: Kiritimati is 2026-03-01 19:00, Pago Pago is 2026-02-28 18:00.
const FIXED_INSTANT = new Date("2026-03-01T05:00:00Z");

describe("orgToday / orgDateShift", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_INSTANT);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("two zones across the date line differ by a day at the same instant", () => {
    expect(orgToday("Pacific/Kiritimati")).toBe("2026-03-01");
    expect(orgToday("Pacific/Pago_Pago")).toBe("2026-02-28");
  });

  it("shift crosses month boundaries in both directions", () => {
    expect(orgDateShift("Pacific/Kiritimati", -1)).toBe("2026-02-28");
    expect(orgDateShift("Pacific/Pago_Pago", -1)).toBe("2026-02-27");
    expect(orgDateShift("Pacific/Pago_Pago", 1)).toBe("2026-03-01");
    expect(orgDateShift("Pacific/Kiritimati", -60)).toBe("2025-12-31");
    expect(orgDateShift("Pacific/Kiritimati", 0)).toBe(orgToday("Pacific/Kiritimati"));
  });

  it("unknown or empty timezone falls back to Asia/Taipei instead of throwing", () => {
    expect(resolveOrgTimezone("Not/AZone")).toBe(DEFAULT_ORG_TIMEZONE);
    expect(resolveOrgTimezone("")).toBe(DEFAULT_ORG_TIMEZONE);
    expect(resolveOrgTimezone(undefined)).toBe(DEFAULT_ORG_TIMEZONE);
    expect(resolveOrgTimezone("Pacific/Pago_Pago")).toBe("Pacific/Pago_Pago");
    expect(orgToday("Not/AZone")).toBe(orgToday("Asia/Taipei"));
    expect(orgToday("Asia/Taipei")).toBe("2026-03-01");
  });
});

describe("useOrgClock", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_INSTANT);
  });
  afterEach(() => {
    vi.useRealTimers();
    mockUseWorkspace.mockReset();
  });

  it("reads the timezone from the workspace org and recomputes today from it", () => {
    mockUseWorkspace.mockReturnValue({
      identity: {
        user: { id: "u1", email: "a@example.com" },
        // `today` from /me is a stale boot value on purpose: the hook must not echo it.
        org: { id: "org_1", name: "測試", kind: "personal", role: "owner", timezone: "Pacific/Pago_Pago", today: "2020-01-01" },
        orgs: [],
      },
    });
    const { result } = renderHook(() => useOrgClock());
    expect(result.current.timezone).toBe("Pacific/Pago_Pago");
    expect(result.current.today).toBe("2026-02-28");
    expect(result.current.shift(-7)).toBe("2026-02-21");
  });

  it("falls back to Asia/Taipei when the org has no usable timezone", () => {
    mockUseWorkspace.mockReturnValue({
      identity: {
        user: { id: "u1", email: "a@example.com" },
        org: { id: "org_1", name: "測試", kind: "personal", role: "owner", timezone: "", today: "" },
        orgs: [],
      },
    });
    const { result } = renderHook(() => useOrgClock());
    expect(result.current.timezone).toBe(DEFAULT_ORG_TIMEZONE);
    expect(result.current.today).toBe("2026-03-01");
  });
});

describe("F50-I12 pure day helpers and instant printing (Contract K)", () => {
  it("prints an instant on the org clock whatever the runner's zone", () => {
    // 2026-10-31T17:00Z is already 11/01 01:00 in Taipei and still 10/31 in Pago Pago.
    const iso = "2026-10-31T17:00:00Z";
    expect(formatInstant(iso, "Asia/Taipei", "md")).toBe("11/1");
    expect(formatInstant(iso, "Asia/Taipei", "mmdd")).toBe("11/01");
    expect(formatInstant(iso, "Asia/Taipei", "md_hm")).toBe("11/01 01:00");
    expect(formatInstant(iso, "Asia/Taipei", "hm")).toBe("01:00");
    expect(formatInstant(iso, "Asia/Taipei", "ymd")).toBe("2026/11/01");
    expect(formatInstant(iso, "Pacific/Pago_Pago", "md_hm")).toBe("10/31 06:00");
    expect(orgDateOf(iso, "Asia/Taipei")).toBe("2026-11-01");
    expect(orgDateOf(iso, "Pacific/Pago_Pago")).toBe("2026-10-31");
  });

  it("reads Python's own text form, midnight as 00 and unreadable as empty", () => {
    expect(formatInstant("2026-10-01 15:10:33.055275+00:00", "Asia/Taipei", "md_hm")).toBe("10/01 23:10");
    expect(formatInstant("2026-11-07T16:00:00+00:00", "Asia/Taipei", "md_hm")).toBe("11/08 00:00");
    expect(formatInstant(null, "Asia/Taipei", "md")).toBe("");
    expect(formatInstant("not a time", "Asia/Taipei", "md")).toBe("");
    expect(formatInstant("2026-10-01", "Asia/Taipei", "md")).toBe("");
    expect(orgDateOf("2026-10-01", "Asia/Taipei")).toBe("2026-10-01");
    expect(orgDateOf("garbage", "Asia/Taipei")).toBeNull();
  });

  it("does day arithmetic on calendar strings only", () => {
    expect(formatDay("2026-10-03", "md")).toBe("10/3");
    expect(formatDay("2026-10-03", "mmdd")).toBe("10/03");
    expect(formatDay("2026-10-03", "ymd")).toBe("2026/10/03");
    expect(formatDay("10/03", "md")).toBe("");
    expect(addDays("2026-10-31", 8)).toBe("2026-11-08");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(daysBetween("2026-10-01", "2026-10-07")).toBe(7);
    expect(daysBetween("2026-10-01", "2026-10-01")).toBe(1);
    expect(daysBetween("2026-10-01", "x")).toBeNull();
    expect(dayList("2026-09-29", "2026-10-02")).toEqual(["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]);
    expect(dayList("2026-10-02", "2026-10-01")).toEqual([]);
    expect(dayList("2026-01-01", "2026-12-31", 3)).toHaveLength(3);
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-10", 0)).toBe("2026-10");
  });
});
