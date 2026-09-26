/** frontend/src/components/intake/steps/OfferingsStep.test.tsx — 票 F05-I16：回到步驟 3 時，
 * 只有一個賣法的商品品名被清空（`deriveFromOfferings` 誤把 name 也套上母子判斷）。
 * 全程假 fetchOfferings，不連任何伺服器（跟 IntakeWizard.test.tsx 同一套假法）。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, fetchOfferings: vi.fn(), saveOfferings: vi.fn() };
});

import type { IntakeDraft, Offering, OfferingsChoice, OfferingsData } from "@/lib/intakeApi";
import { fetchOfferings, saveOfferings } from "@/lib/intakeApi";
import { OfferingsStep } from "./OfferingsStep";

const mockFetchOfferings = vi.mocked(fetchOfferings);
const mockSaveOfferings = vi.mocked(saveOfferings);

const draft = { brand_id: "brd_x", completed: false, step: 3 } as unknown as IntakeDraft;

function offeringsData(offerings: Offering[], choice: OfferingsChoice | null = null): OfferingsData {
  return {
    offerings,
    choice,
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

  // F31-I01 Contract M: the two choices come back from the draft. Before, 廣告帶來的是什麼 was
  // never restored (revisiting blocked Next) and a service sold directly (no close_rate) was read
  // back as a product named 「服務」.
  const turmeric: Offering = {
    product_id: "prd_1",
    name: "薑黃錠",
    parent_id: null,
    selling_price: 690,
    unit_variable_cost: 200,
    shipping_cost: 80,
    close_rate: null,
    assumptions: [],
  };

  it("存過的選擇回來後不再要求重選，下一步可以按", async () => {
    mockFetchOfferings.mockResolvedValue(offeringsData([turmeric], { sell_type: "product", ad_delivery: "ask" }));

    render(<OfferingsStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={vi.fn()} />);

    await waitFor(() => expect(screen.getByDisplayValue("薑黃錠")).toBeTruthy());
    expect(screen.queryByText("選一下廣告帶來的是什麼。")).toBeNull();
    expect(screen.getByRole("button", { name: "先詢問再成交" }).className).toContain("border-primary");
    expect(screen.queryByText("服務／課程／KOL")).toBeNull();
    expect((screen.getByRole("button", { name: "下一步" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("直接下單的服務（沒有 close_rate）回來還是服務，不會變成叫「服務」的商品", async () => {
    mockFetchOfferings.mockResolvedValue(
      offeringsData(
        [
          { ...turmeric, product_id: "prd_s", name: "服務", selling_price: null, unit_variable_cost: null, shipping_cost: null },
          { ...turmeric, product_id: "prd_s1", name: "服務 · 方案", parent_id: "prd_s", selling_price: 5000, unit_variable_cost: 0, shipping_cost: 0 },
        ],
        { sell_type: "service", ad_delivery: "direct" },
      ),
    );

    render(<OfferingsStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("服務／課程／KOL")).toBeTruthy());
    expect(screen.getByDisplayValue("5000")).toBeTruthy();
    expect(screen.queryByDisplayValue("服務")).toBeNull();
    expect((screen.getByRole("button", { name: "下一步" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("按下一步會把兩個選擇一起送出", async () => {
    mockFetchOfferings.mockResolvedValue(offeringsData([turmeric]));
    mockSaveOfferings.mockResolvedValue(undefined);
    const onNext = vi.fn();

    render(<OfferingsStep brandId="brd_x" draft={draft} onRefresh={vi.fn()} onNext={onNext} />);

    await waitFor(() => expect(screen.getByDisplayValue("薑黃錠")).toBeTruthy());
    await userEvent.click(screen.getByRole("button", { name: "直接下單" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSaveOfferings).toHaveBeenCalledWith("brd_x", expect.any(Array), { sell_type: "product", ad_delivery: "direct" });
  });
});
