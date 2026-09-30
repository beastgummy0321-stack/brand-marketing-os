/** frontend/src/components/intake/steps/DoneStep.test.tsx — brand onboarding `#/b7` 完成 (F42-I12): entering the
 * step calls `complete` once; the readiness rows print verbatim; a red 商品 row carries the one primary
 * 「建第一個商品 →」, an all-green brand has no red CTA, a yellow row gets 「去改」 to its step; a failed read keeps the
 * head and bar and offers the retry. No server: the API calls are fakes with the shape of
 * `app/ads/readiness.py::launch_readiness()`. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/adsLaunchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLaunchApi")>("@/lib/adsLaunchApi");
  return { ...actual, fetchLaunchReadiness: vi.fn() };
});
vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, completeOnboarding: vi.fn() };
});

import { fetchLaunchReadiness, type LaunchReadiness, type ReadinessItem } from "@/lib/adsLaunchApi";
import { completeOnboarding, type OnboardingStatus } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { DoneStep } from "./DoneStep";

const mockReadiness = vi.mocked(fetchLaunchReadiness);
const mockComplete = vi.mocked(completeOnboarding);
const nav: StepNav = { crumb: brandCrumb("Beast Gummy"), steps: BRAND_STEPS, current: 7 };
const B = "brd_1";

const done: OnboardingStatus = {
  step: 7, completed: true, skipped_scan: false, prefill_status: "none", prefill_error: null,
} as OnboardingStatus;

const identity: ReadinessItem = {
  key: "identity", label: "品牌是誰", state: "green", reason: "一句話和口氣已確認。",
  fix_label: "去改", fix_href: `/brands/${B}/intake?step=3`,
};
const evidence: ReadinessItem = {
  key: "evidence", label: "證據與政策", state: "green", reason: "品牌證據 1 項・政策 2 項",
  fix_label: "去改", fix_href: `/brands/${B}/intake?step=4`,
};
const evidenceYellow: ReadinessItem = {
  ...evidence, state: "yellow", reason: "還沒有登記證據或政策；廣告只會講產品本身", fix_label: "去登記證據與政策",
};
const media: ReadinessItem = {
  key: "media", label: "素材", state: "green", reason: "素材：只有照片",
  fix_label: "去改", fix_href: `/brands/${B}/intake?step=5`,
};
const channel: ReadinessItem = {
  key: "channel", label: "廣告帳戶", state: "green", reason: "已接上 Meta，花費資料齊全・成效目標：購買",
  fix_label: "去接廣告帳戶", fix_href: `/brands/${B}/intake?step=6`,
};
const noProduct: ReadinessItem = {
  key: "offering", label: "商品", state: "red", reason: "還沒有商品",
  fix_label: "建第一個商品", fix_href: `/brands/${B}/products`,
};
const offeringGreen: ReadinessItem = {
  ...noProduct, state: "green", reason: "有賣法算得出打平 CPA。", fix_label: "去補商品與數字",
};

function readiness(items: ReadinessItem[], state: LaunchReadiness["state"], label: string): LaunchReadiness {
  return {
    state, items,
    notes: [{ key: "knowledge", text: "品牌知識 5 條（已確認）" }],
    primary: { label, href: `/brands/${B}/ads` },
    secondary: null,
  };
}

function renderStep(back = { label: "接工具", onClick: vi.fn() }) {
  render(
    <MemoryRouter>
      <DoneStep brandId={B} nav={nav} back={back} />
    </MemoryRouter>,
  );
  return { back };
}

const row = (label: string) => screen.getByText(label, { selector: "b" }).closest("li") as HTMLElement;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DoneStep", () => {
  it("calls complete once on entry and prints every row verbatim", async () => {
    mockComplete.mockResolvedValue(done);
    mockReadiness.mockResolvedValue(readiness([identity, evidence, media, channel, noProduct], "red", "先補齊地基"));
    renderStep();
    await screen.findByText("還沒有商品");
    expect(mockComplete).toHaveBeenCalledTimes(1);
    expect(mockComplete).toHaveBeenCalledWith(B);
    expect(mockReadiness).toHaveBeenCalledWith(B);
    const card = screen.getByRole("region", { name: "可以開始投放了嗎" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("品牌證據 1 項・政策 2 項")).toBeTruthy();
    expect(screen.getByText("已接上 Meta，花費資料齊全・成效目標：購買")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "品牌建好了" })).toBeTruthy();
  });

  it("gives a red 商品 row the primary 建第一個商品 → and the chip 還差商品", async () => {
    mockComplete.mockResolvedValue(done);
    mockReadiness.mockResolvedValue(readiness([identity, evidence, media, channel, noProduct], "red", "先補齊地基"));
    renderStep();
    const cta = await screen.findByRole("link", { name: "建第一個商品 →" });
    expect(cta.getAttribute("href")).toBe(`/brands/${B}/products`);
    expect(within(row("商品")).getByRole("link", { name: "建第一個商品 →" })).toBe(cta);
    expect(screen.getByText("還差商品").getAttribute("data-tone")).toBe("warn");
    // Green rows carry no action.
    expect(within(row("品牌是誰")).queryByRole("link")).toBeNull();
  });

  it("has no red CTA and no 去改 when every row is green", async () => {
    mockComplete.mockResolvedValue(done);
    mockReadiness.mockResolvedValue(readiness([identity, evidence, media, channel, offeringGreen], "green", "進入投放中心"));
    renderStep();
    await screen.findByText("有賣法算得出打平 CPA。");
    expect(screen.queryByRole("link", { name: /→$/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "去改" })).toBeNull();
    expect(screen.queryByText("還差商品")).toBeNull();
    expect(screen.getByText("進入投放中心").getAttribute("data-tone")).toBe("ok");
  });

  it("gives a yellow row 去改 to its step", async () => {
    mockComplete.mockResolvedValue(done);
    mockReadiness.mockResolvedValue(
      readiness([identity, evidenceYellow, media, channel, offeringGreen], "yellow", "進入投放中心（有假設值）"),
    );
    renderStep();
    await screen.findByText("還沒有登記證據或政策；廣告只會講產品本身");
    const fix = within(row("證據與政策")).getByRole("link", { name: "去改" });
    expect(fix.getAttribute("href")).toBe(`/brands/${B}/intake?step=4`);
    expect(screen.getAllByRole("link", { name: "去改" })).toHaveLength(1);
    expect(screen.getByText("進入投放中心（有假設值）").getAttribute("data-tone")).toBe("warn");
  });

  it("keeps the head and bar when the read fails and retries in the rows area", async () => {
    mockComplete.mockResolvedValue(done);
    mockReadiness.mockRejectedValueOnce(new Error("讀取可投放檢查表失敗。"));
    mockReadiness.mockResolvedValueOnce(readiness([identity, evidence, media, channel, noProduct], "red", "先補齊地基"));
    const { back } = renderStep();
    expect((await screen.findByRole("alert")).textContent).toBe("讀取可投放檢查表失敗。");
    expect(screen.getByRole("heading", { name: "可以開始投放了嗎" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "先看商品頁" }).getAttribute("href")).toBe(`/brands/${B}/products`);
    await userEvent.click(screen.getByRole("button", { name: "← 接工具" }));
    expect(back.onClick).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await screen.findByText("還沒有商品");
    expect(mockReadiness).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(1));
  });
});
