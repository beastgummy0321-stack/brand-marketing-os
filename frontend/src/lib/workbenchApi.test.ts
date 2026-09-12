/** F02-I14：`parseFreeText` 沒有拆掉 `{parse: ...}` 信封，`result.spec` 一直是 `undefined`，
 * 自由創作在第一次點擊就死掉。跟 `http.test.ts` 一樣的假法：假 `@/lib/http` 的 `apiFetch`，
 * 不連任何伺服器。 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/http", () => ({
  apiFetch: vi.fn(),
  errorMessageFrom: vi.fn(),
}));

import { apiFetch } from "@/lib/http";
import { parseFreeText } from "@/lib/workbenchApi";

describe("parseFreeText", () => {
  it("拆開 {parse: ...} 信封，回傳裡面的 FreeParseResult", async () => {
    const envelope = {
      parse: {
        parsed: true,
        note: null,
        spec: {
          topic: "夜跑",
          outputs: [{ part: "image_prompt", count: 5 }],
          style_hint: null,
          platform: null,
          size: null,
          audience: null,
          key_message: null,
        },
      },
    };
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(JSON.stringify(envelope), { status: 200 }),
    );

    const result = await parseFreeText("brd_x", "五張夜跑廣告", {});

    expect(result.spec.outputs).toEqual(envelope.parse.spec.outputs);
  });
});
