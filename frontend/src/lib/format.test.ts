/** 票 past-ads-07：`formatMoney` 帶幣別，跟系統自己 TWD 的 `formatCurrency` 分開驗證——
 * 這個 vitest 案例本身就是防呆：實作若忽略 `currency` 永遠印 TWD，USD 案例會抓到。 */
import { describe, expect, it } from "vitest";
import { formatMoney, formatRelativeHours, formatUpdatedAt, secondsSince } from "@/lib/format";

describe("formatMoney", () => {
  it("四捨五入、千分位、幣別代碼接在數字後面", () => {
    expect(formatMoney(28860.4, "TWD")).toBe("28,860 TWD");
    expect(formatMoney(1250, "USD")).toBe("1,250 USD");
  });

  it("null 一律「累積中」，不分幣別", () => {
    expect(formatMoney(null, "USD")).toBe("累積中");
  });
});

/** F50-I14 (Contract K): elapsed counters and 「更新於」 stamps — durations from now, dates on the org clock. */
describe("secondsSince／formatRelativeHours／formatUpdatedAt", () => {
  const NOW = Date.parse("2026-10-04T00:30:00Z");

  it("secondsSince counts from a real instant (also Python's text form) and is null without one", () => {
    expect(secondsSince("2026-10-04T00:29:00Z", NOW)).toBe(60);
    expect(secondsSince("2026-10-04 00:29:30.123456+00:00", NOW)).toBe(30);
    expect(secondsSince(null, NOW)).toBeNull();
    expect(secondsSince("", NOW)).toBeNull();
    expect(secondsSince("not a time", NOW)).toBeNull();
  });

  it("formatUpdatedAt: relative under 24 hours, else MM/DD HH:mm in the org zone; '' when unreadable", () => {
    const recent = new Date(Date.now() - 2 * 3_600_000).toISOString();
    expect(formatUpdatedAt(recent, "Asia/Taipei")).toBe("2 小時前");
    expect(formatUpdatedAt("2026-01-01T00:30:00Z", "Asia/Taipei")).toBe("01/01 08:30");
    expect(formatUpdatedAt("2026-01-01T00:30:00Z", "America/New_York")).toBe("12/31 19:30");
    expect(formatUpdatedAt("", "Asia/Taipei")).toBe("");
    expect(formatRelativeHours("garbage")).toBe("");
  });
});
