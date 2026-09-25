import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadCsv, toCsv } from "./csv";

describe("csv（F29-I09 Contract K）", () => {
  afterEach(() => vi.restoreAllMocks());

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
