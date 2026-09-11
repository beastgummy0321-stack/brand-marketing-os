import { describe, expect, it } from "vitest";
import { specToCreateBody } from "./FreeJobPage";
import type { FreeParseSpec } from "@/lib/workbenchApi";

function spec(overrides: Partial<FreeParseSpec> = {}): FreeParseSpec {
  return {
    topic: "夜跑廣告",
    outputs: [{ part: "image_prompt", count: 5 }],
    style_hint: "ugc",
    platform: "Meta",
    size: "4:5",
    audience: "運動族群",
    key_message: "提升表現",
    ...overrides,
  };
}

describe("specToCreateBody（F02-I10 唯一的分支邏輯）", () => {
  it("count 有給值：required_outputs 跟同一輪的產出數量用同一個數字", () => {
    const body = specToCreateBody(spec(), { text: "幫我做五張夜跑廣告", productId: null });
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5 });
    expect(body.sets[0].request?.image_prompt_count).toBe(5);
  });

  it("outputs 沒給 count：預設 1", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "copy", count: undefined as unknown as number }] }),
      { text: "文案", productId: null },
    );
    expect(body.sets[0].required_outputs).toEqual({ copy: 1 });
    expect(body.sets[0].request?.copy_count).toBe(1);
  });

  it("parsed: false 沿用使用者填的預設值，仍然可以送出", () => {
    const fallback = spec({
      topic: null, style_hint: null, platform: null, size: null, audience: null, key_message: null,
    });
    const body = specToCreateBody(fallback, { text: "隨便做點什麼", productId: null });
    expect(body.free_text).toBe("隨便做點什麼");
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5 });
    expect(body.style_key).toBeNull();
  });

  it("多種產出類型：outputs 每一項各自進 required_outputs", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "image_prompt", count: 5 }, { part: "copy", count: 1 }] }),
      { text: "混合任務", productId: "prod_1" },
    );
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5, copy: 1 });
    expect(body.product_id).toBe("prod_1");
  });
});
