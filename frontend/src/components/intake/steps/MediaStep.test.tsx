/** frontend/src/components/intake/steps/MediaStep.test.tsx — brand onboarding `#/b5` 素材 (F42-I10): the saved
 * answer is shown, a never-answered brand shows 「只有照片」 picked but nothing is written until 下一步, 下一步 sends
 * `PUT …/onboarding/media` with the picked value and a failed save keeps the user on the step, and the cards follow
 * the radio keyboard pattern. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingMedia: vi.fn(), saveOnboardingMedia: vi.fn() };
});

import { fetchOnboardingMedia, saveOnboardingMedia } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { MediaStep } from "./MediaStep";

const mockFetch = vi.mocked(fetchOnboardingMedia);
const mockSave = vi.mocked(saveOnboardingMedia);
const nav: StepNav = { crumb: brandCrumb("Beast Gummy"), steps: BRAND_STEPS, current: 5 };

function renderStep(onNext = vi.fn(), back = { label: "證據與政策", onClick: vi.fn() }) {
  render(
    <MemoryRouter initialEntries={["/brands/brd_1/intake"]}>
      <Routes>
        <Route path="/brands/:brandId/intake" element={<MediaStep nav={nav} back={back} onNext={onNext} />} />
      </Routes>
    </MemoryRouter>,
  );
  return { onNext, back };
}

const card = (name: string) => screen.getByRole("radio", { name: new RegExp(name) });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MediaStep", () => {
  it("shows the saved answer picked", async () => {
    mockFetch.mockResolvedValue({ media: "photo_video" });
    renderStep();
    await waitFor(() => expect(card("照片和影片都能交").getAttribute("aria-checked")).toBe("true"));
    expect(card("只有照片").getAttribute("aria-checked")).toBe("false");
    expect(mockFetch).toHaveBeenCalledWith("brd_1");
    expect(screen.getByText("之後拍得出影片了，回到「品牌資料」改就好。")).toBeTruthy();
  });

  it("shows 只有照片 for a never-answered brand and writes it only on 下一步", async () => {
    mockFetch.mockResolvedValue({ media: null });
    mockSave.mockResolvedValue({ media: "photo" });
    const { onNext } = renderStep();
    await waitFor(() => expect(card("只有照片").getAttribute("aria-checked")).toBe("true"));
    expect(mockSave).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect(mockSave).toHaveBeenCalledWith("brd_1", "photo");
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  });

  it("sends the picked value on 下一步", async () => {
    mockFetch.mockResolvedValue({ media: "photo" });
    mockSave.mockResolvedValue({ media: "photo_video" });
    const { onNext } = renderStep();
    await waitFor(() => expect(card("只有照片").getAttribute("aria-checked")).toBe("true"));
    await userEvent.click(card("照片和影片都能交"));
    expect(mockSave).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect(mockSave).toHaveBeenCalledWith("brd_1", "photo_video");
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  });

  it("keeps the user on the step when the save fails", async () => {
    mockFetch.mockResolvedValue({ media: null });
    mockSave.mockRejectedValue(new Error("素材能力只能是 photo 或 photo_video"));
    const { onNext } = renderStep();
    await waitFor(() => expect(card("只有照片").getAttribute("aria-checked")).toBe("true"));
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect((await screen.findByRole("alert")).textContent).toBe("素材能力只能是 photo 或 photo_video");
    expect(onNext).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "下一步 →" })).toHaveProperty("disabled", false);
  });

  it("goes back through the bar", async () => {
    mockFetch.mockResolvedValue({ media: null });
    const { back } = renderStep();
    await userEvent.click(screen.getByRole("button", { name: "← 證據與政策" }));
    expect(back.onClick).toHaveBeenCalledTimes(1);
  });

  it("picks cards with the keyboard", async () => {
    mockFetch.mockResolvedValue({ media: null });
    mockSave.mockResolvedValue({ media: "photo_video" });
    renderStep();
    await waitFor(() => expect(card("只有照片").getAttribute("aria-checked")).toBe("true"));
    await userEvent.tab();
    expect(document.activeElement).toBe(card("只有照片"));
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(card("照片和影片都能交"));
    expect(card("照片和影片都能交").getAttribute("aria-checked")).toBe("true");
    expect(card("只有照片").getAttribute("aria-checked")).toBe("false");
    await userEvent.keyboard("{ArrowRight}");
    expect(card("只有照片").getAttribute("aria-checked")).toBe("true");
    await userEvent.keyboard("{End}");
    expect(card("照片和影片都能交").getAttribute("aria-checked")).toBe("true");
    expect(mockSave).not.toHaveBeenCalled();
  });
});
