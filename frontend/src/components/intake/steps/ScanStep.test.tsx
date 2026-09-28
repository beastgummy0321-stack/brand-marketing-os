/** frontend/src/components/intake/steps/ScanStep.test.tsx — F36-I01 (drill-6 #6): the empty message
 * 「這次沒有讀出可建立的產品」 keys on photo cards ∪ scanned names, not photo cards alone. Before, a
 * URL-only scan (names in `scan_products`, `product_card_drafts` empty) showed the message right
 * above the checklist of detected names. No server: the draft is a fixture with `scan_done: true`
 * so the step never starts the background job (same importActual+override pattern as
 * OfferingsStep.test.tsx). */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, startScan: vi.fn(), fetchScanStatus: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({ useAuthedImage: vi.fn(() => ({ src: null, failed: true })) }));

import type { IntakeDraft, ProductCardDraft } from "@/lib/intakeApi";
import { ScanStep } from "./ScanStep";

const EMPTY_MESSAGE = "這次沒有讀出可建立的產品；你仍可照原本流程往下回答問題。";

function scannedDraft(overrides: Partial<IntakeDraft>): IntakeDraft {
  return {
    id: "itk_1",
    brand_id: "brd_x",
    brand_name: "虛構品牌",
    step: 2,
    completed: false,
    is_restart: false,
    description: "一句描述",
    urls: [],
    photos: [],
    scan_done: true,
    scan_impressions: [{ looks_like: "官網", title: "首頁", content: "賣保健食品", basis: "網址 1" }],
    scan_products: [],
    product_card_drafts: [],
    created_product_names: [],
    url_results: [],
    qa_done: false,
    current_q: null,
    answers: [],
    question_index: 0,
    handoff_depth: null,
    handoff_generated: false,
    handoff_prompt: null,
    paste_raw: "",
    paste_errors: [],
    paste_fix_used: false,
    pending_item_count: 0,
    budget_limit: 5,
    cost_spent: 0.3,
    cost_items: [],
    ...overrides,
  };
}

function readyCard(name: string, token: string): ProductCardDraft {
  return { status: "ready", name, specification: "60 顆", selling_points: ["好吞"], source_photo_token: token, gaps: [], message: null };
}

function renderStep(draft: IntakeDraft) {
  return render(<ScanStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={vi.fn()} />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScanStep 產品卡草稿的空狀態", () => {
  it("只有網址掃出三個名稱：顯示勾選清單，不顯示「沒有讀出可建立的產品」", () => {
    renderStep(
      scannedDraft({
        urls: ["https://a.example"],
        url_results: [{ url: "https://a.example", ok: true }],
        scan_products: ["薑黃錠", "益生菌", "魚油"],
      }),
    );

    expect(screen.getByText("薑黃錠")).toBeTruthy();
    expect(screen.getByText("益生菌")).toBeTruthy();
    expect(screen.getByText("魚油")).toBeTruthy();
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "建立勾選的產品" })).toBeTruthy();
    expect(screen.queryByText(EMPTY_MESSAGE)).toBeNull();
  });

  it("沒有產品卡也沒有名稱：顯示「沒有讀出可建立的產品」", () => {
    renderStep(
      scannedDraft({
        urls: ["https://a.example"],
        url_results: [{ url: "https://a.example", ok: true }],
      }),
    );

    expect(screen.getByText(EMPTY_MESSAGE)).toBeTruthy();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "建立勾選的產品" })).toBeNull();
  });

  it("只有照片產品卡：顯示卡片，不顯示「沒有讀出可建立的產品」", () => {
    renderStep(
      scannedDraft({
        photos: [{ token: "pho_1", name: "front.jpg", size_mb: 1.2 }],
        product_card_drafts: [readyCard("薑黃錠", "pho_1")],
      }),
    );

    expect(screen.getByText("薑黃錠")).toBeTruthy();
    expect(screen.getByRole("button", { name: "＋建立為產品" })).toBeTruthy();
    expect(screen.queryByText(EMPTY_MESSAGE)).toBeNull();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });
});
