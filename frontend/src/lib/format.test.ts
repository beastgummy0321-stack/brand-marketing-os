/** 票 past-ads-07：`formatMoney` 帶幣別，跟系統自己 TWD 的 `formatCurrency` 分開驗證——
 * 這個 vitest 案例本身就是防呆：實作若忽略 `currency` 永遠印 TWD，USD 案例會抓到。 */
import { describe, expect, it } from "vitest";
import { formatMoney } from "@/lib/format";

describe("formatMoney", () => {
  it("四捨五入、千分位、幣別代碼接在數字後面", () => {
    expect(formatMoney(28860.4, "TWD")).toBe("28,860 TWD");
    expect(formatMoney(1250, "USD")).toBe("1,250 USD");
  });

  it("null 一律「累積中」，不分幣別", () => {
    expect(formatMoney(null, "USD")).toBe("累積中");
  });
});
