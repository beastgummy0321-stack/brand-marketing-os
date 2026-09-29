/**
 * Truth card: answers are client-only state, so the re-read after a side-panel save must keep them
 * (drill-7 #13a). Fake fetchTruthCard/confirmTruthCard; the side panel is a stub that only fires onSaved.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { TruthCardStep } from "./TruthCardStep";
import { confirmTruthCard, fetchTruthCard, type TruthCard, type TruthCardItem } from "@/lib/intakeT2Api";

vi.mock("@/lib/intakeT2Api", () => ({
  fetchTruthCard: vi.fn(),
  confirmTruthCard: vi.fn().mockResolvedValue(undefined),
  moveTruthCardItem: vi.fn(),
}));
vi.mock("./TruthCardItemPanel", () => ({
  TruthCardItemPanel: ({ onSaved }: { onSaved: () => void }) => (
    <button type="button" onClick={onSaved}>儲存調整</button>
  ),
}));

const mockFetchTruthCard = vi.mocked(fetchTruthCard);
const mockConfirmTruthCard = vi.mocked(confirmTruthCard);

function item(id: string, i: number, title: string, answer_kind: TruthCardItem["answer_kind"]): TruthCardItem {
  return {
    id,
    i,
    kind: "產品事實",
    category: "產品",
    title,
    content: "",
    scope: "整個品牌",
    evidence: "",
    outcome: "pending",
    status: "pending",
    landed: false,
    landed_pending: false,
    answer_kind,
  };
}

const price = item("itm-price", 1, "軟糖 60 粒", "price");
const claimA = item("itm-claim-a", 2, "幫助消化", "claim_permission");
const claimB = item("itm-claim-b", 3, "睡得更好", "claim_permission");

function card(needs: TruthCardItem[]): TruthCard {
  return { accepted: [], needs_confirmation: needs, forbidden: [] };
}

async function answerTwoAndSaveFromPanelOf(title: string) {
  await userEvent.type(await screen.findByRole("textbox", { name: "軟糖 60 粒的售價" }), "480");
  const rowA = screen.getByText("幫助消化可以講嗎？").closest("div")!;
  await userEvent.click(within(rowA).getByRole("button", { name: "可以" }));
  const rowB = screen.getByText(title + "可以講嗎？").closest("div")!;
  await userEvent.click(within(rowB).getByRole("button", { name: "改" }));
  await userEvent.click(screen.getByRole("button", { name: "儲存調整" }));
}

beforeEach(() => {
  mockFetchTruthCard.mockReset();
  mockConfirmTruthCard.mockClear();
});

it("keeps the answers already given when a side-panel save re-reads the card, and submits them", async () => {
  mockFetchTruthCard.mockResolvedValue(card([price, claimA, claimB]));
  const onCompleted = vi.fn();
  render(<TruthCardStep brandId="brd" knownProducts={[]} onCompleted={onCompleted} />);

  await answerTwoAndSaveFromPanelOf("睡得更好");
  await waitFor(() => expect(mockFetchTruthCard).toHaveBeenCalledTimes(2));

  expect((await screen.findByRole("textbox", { name: "軟糖 60 粒的售價" })).getAttribute("value")).toBe("480");
  const rowA = screen.getByText("幫助消化可以講嗎？").closest("div")!;
  expect(within(rowA).getByRole("button", { name: "可以" }).className).toContain("border-primary");
  expect(screen.getByRole("status").textContent).toBe("還缺：睡得更好。答完就能按。");

  const rowB = screen.getByText("睡得更好可以講嗎？").closest("div")!;
  await userEvent.click(within(rowB).getByRole("button", { name: "不能講" }));
  await userEvent.click(screen.getByRole("button", { name: "✅ 這張卡正確，完成建檔" }));
  await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
  expect(mockConfirmTruthCard).toHaveBeenCalledWith("brd", {
    "itm-price": { value: "480" },
    "itm-claim-a": { decision: "can_say" },
    "itm-claim-b": { decision: "cannot_say" },
  });
});

it("drops the answer of an item the re-read no longer lists, keeps the rest", async () => {
  mockFetchTruthCard.mockResolvedValueOnce(card([price, claimA, claimB])).mockResolvedValueOnce(card([claimA, claimB]));
  const onCompleted = vi.fn();
  render(<TruthCardStep brandId="brd" knownProducts={[]} onCompleted={onCompleted} />);

  await answerTwoAndSaveFromPanelOf("睡得更好");
  await waitFor(() => expect(mockFetchTruthCard).toHaveBeenCalledTimes(2));

  await waitFor(() => expect(screen.queryByRole("textbox", { name: "軟糖 60 粒的售價" })).toBeNull());
  const rowA = screen.getByText("幫助消化可以講嗎？").closest("div")!;
  expect(within(rowA).getByRole("button", { name: "可以" }).className).toContain("border-primary");

  const rowB = screen.getByText("睡得更好可以講嗎？").closest("div")!;
  await userEvent.click(within(rowB).getByRole("button", { name: "可以" }));
  await userEvent.click(screen.getByRole("button", { name: "✅ 這張卡正確，完成建檔" }));
  await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
  expect(mockConfirmTruthCard).toHaveBeenCalledWith("brd", {
    "itm-claim-a": { decision: "can_say" },
    "itm-claim-b": { decision: "can_say" },
  });
});
