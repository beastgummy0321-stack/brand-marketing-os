import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadCsv, perSaleAmount, toCsv } from "./csv";
import { stampText, yuan } from "../settle/settleCsv";
import { mmdd } from "../month/monthCsv";

describe("csv（F29-I09 Contract K）", () => {
  afterEach(() => vi.restoreAllMocks());

  it("F50-I12: the CSV builders print instants on the org clock and days as they are, whatever the runner's zone", () => {
    // 2026-10-31T17:00Z is 11/01 01:00 in Taipei and 10/31 06:00 in Pago Pago.
    expect(stampText("2026-10-31T17:00:00Z", "Asia/Taipei")).toBe("11/01 01:00");
    expect(stampText("2026-10-31T17:00:00Z", "Pacific/Pago_Pago")).toBe("10/31 06:00");
    expect(stampText("not a time", "Asia/Taipei")).toBe("");
    expect(mmdd("2026-09-05")).toBe("09/05");
  });

  it("CRLF 分行；逗號、雙引號、換行要加引號；null 是空格，不是 0", () => {
    const text = toCsv([
      ["廣告", "花費", "每筆"],
      ["晨光隨行杯・日常出發", 1440, 48],
      ['說 "你好", 再見', null, undefined],
      ["兩行\n文案", 0, Number.NaN],
    ]);
    expect(text).toBe(
      "廣告,花費,每筆\r\n" +
      "晨光隨行杯・日常出發,1440,48\r\n" +
      '"說 ""你好"", 再見",,\r\n' +
      '"兩行\n文案",0,\r\n',
    );
  });

  it("F47-I06：數字四捨五入到小數兩位，沒有浮點尾巴，整數不補零", () => {
    expect(toCsv([["花費", 3286.2400000000002, 1440, 48.005, 0.1 + 0.2, -12.345]])).toBe("花費,3286.24,1440,48.01,0.3,-12.34\r\n");
  });

  it("F47-I06：每筆金額只有一條規則——四捨五入到整數元，不無條件捨去；未知仍是 null", () => {
    expect(perSaleAmount(2014.6)).toBe("2,015");
    expect(perSaleAmount(617.5)).toBe("618");
    expect(perSaleAmount(421.4)).toBe("421");
    expect(perSaleAmount(null)).toBeNull();
    expect(perSaleAmount(Number.NaN)).toBeNull();
    expect(yuan(2014.6)).toBe("2,015 元"); // the settle words use the same rule
    expect(yuan(null)).toBe("未知");
  });

  it("downloadCsv 下載 <name>.csv，內容開頭是 UTF-8 BOM", async () => {
    let blob: Blob | null = null;
    const create = vi.fn((b: Blob) => { blob = b; return "blob:csv"; });
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const clicked: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this); });

    downloadCsv("結算-2026-08", [["a", 1], ["b", null]]);

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("結算-2026-08.csv");
    expect(clicked[0].isConnected).toBe(false);
    const bytes = new Uint8Array(await (blob as unknown as Blob).arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(new TextDecoder().decode(bytes.slice(3))).toBe("a,1\r\nb,\r\n");
    expect((blob as unknown as Blob).type).toBe("text/csv;charset=utf-8");
  });
});
