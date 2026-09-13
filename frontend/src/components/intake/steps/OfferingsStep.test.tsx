/** frontend/src/components/intake/steps/OfferingsStep.test.tsx — 票 F05-I16：回到步驟 3 時，
 * 只有一個賣法的商品品名被清空（`deriveFromOfferings` 誤把 name 也套上母子判斷）。
 * 全程假 fetchOfferings，不連任何伺服器（跟 IntakeWizard.test.tsx 同一套假法）。 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, fetchOfferings: vi.fn(), saveOfferings: vi.fn() };
});

import type { IntakeDraft, Offering, OfferingsData } from "@/lib/intakeApi";
import { fetchOfferings } from "@/lib/intakeApi";
import { OfferingsStep } from "./OfferingsStep";

const mockFetchOfferings = vi.mocked(fetchOfferings);

const draft = { brand_id: "brd_x", completed: false, step: 3 } as unknown as IntakeDraft;

function offeringsData(offerings: Offering[]): OfferingsData {
  return {
    offerings,
    benchmarks: {
      gross_margin: { value: 0.45, source_text: "x" },
      shipping_cost: { value: 80, source_text: "x" },
      close_rate: { value: 0.2, source_text: "x" },
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("OfferingsStep", () => {
  it("只有一個賣法的商品，回到步驟 3 品名不會被清空", async () => {
    mockFetchOfferings.mockResolvedValue(
      offeringsData([
        {
          product_id: "prd_1",
          name: "薑黃錠",
          parent_id: null,
          selling_price: 690,
          unit_variable_cost: 200,
          shipping_cost: 80,
          close_rate: null,
          assumptions: [],
        },
      ]),
    );

    render(<OfferingsStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={vi.fn()} />);

    await waitFor(() => expect(screen.getByDisplayValue("薑黃錠")).toBeTruthy());
  });

  it("有子列（賣法）的商品，母列品名照舊、賣法標籤是子列的差異部分", async () => {
    mockFetchOfferings.mockResolvedValue(
      offeringsData([
        {
          product_id: "prd_1",
          name: "薑黃錠",
          parent_id: null,
          selling_price: null,
          unit_variable_cost: null,
          shipping_cost: null,
          close_rate: null,
          assumptions: [],
        },
        {
          product_id: "prd_2",
          name: "薑黃錠 · 3 入組",
          parent_id: "prd_1",
          selling_price: 1890,
          unit_variable_cost: 550,
          shipping_cost: 80,
          close_rate: null,
          assumptions: [],
        },
      ]),
    );

    render(<OfferingsStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={vi.fn()} />);

    await waitFor(() => expect(screen.getByDisplayValue("薑黃錠")).toBeTruthy());
    expect(screen.getByDisplayValue("3 入組")).toBeTruthy();
  });
});
