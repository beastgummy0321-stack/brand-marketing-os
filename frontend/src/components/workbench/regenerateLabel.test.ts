/** F40-I11 (drill-7 #16): the regenerate button's four states, decided by one pure rule. */
import { describe, expect, it } from "vitest";
import { regenerateLabel, type RegenerateLabelInput } from "./regenerateLabel";

const base: RegenerateLabelInput = {
  part: "image_prompt",
  generating: false,
  ownRequestInFlight: false,
  runningPart: null,
  productState: "待選定",
  idleLabel: "再生成一輪（10 張）",
};

describe("regenerateLabel", () => {
  it("idle → the idle label, no title", () => {
    expect(regenerateLabel(base)).toEqual({ label: "再生成一輪（10 張）" });
  });

  it("own part running → 生成中…, whether by in-flight request or by the remembered part", () => {
    expect(regenerateLabel({ ...base, generating: true, ownRequestInFlight: true }))
      .toEqual({ label: "生成中…" });
    expect(regenerateLabel({ ...base, generating: true, runningPart: "image_prompt" }))
      .toEqual({ label: "生成中…" });
  });

  it("another part known → names it, same sentence as title", () => {
    expect(regenerateLabel({ ...base, generating: true, runningPart: "copy" })).toEqual({
      label: "正在生成文案，完成後才能再生成",
      title: "正在生成文案，完成後才能再生成",
    });
  });

  it("starter unknown → 另一個部分 when the product has versions, 生成中… when it is empty", () => {
    expect(regenerateLabel({ ...base, generating: true })).toEqual({
      label: "正在生成另一個部分，完成後才能再生成",
      title: "正在生成另一個部分，完成後才能再生成",
    });
    expect(regenerateLabel({ ...base, generating: true, productState: "未生成" }))
      .toEqual({ label: "生成中…" });
  });
});
