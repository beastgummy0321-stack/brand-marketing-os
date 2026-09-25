import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/scheduleApi", () => ({
  fetchDiagnosis: vi.fn(),
  runDiagnosis: vi.fn(),
  adoptSuggestion: vi.fn(),
}));

import {
  adoptSuggestion,
  fetchDiagnosis,
  runDiagnosis,
  type Diagnosis,
  type DiagnosisSuggestion,
} from "@/lib/scheduleApi";
import { DiagnosisResult, DiagnosisRunButton, useDiagnosisPanel } from "./DiagnosisPanel";

// Real shape of GET /api/schedule/brands/{b}/diagnosis (app/schedule/diagnosis.py
// brand_diagnosis_response), including Contract K's per-suggestion `adopted`.
function suggestion(overrides: Partial<DiagnosisSuggestion> = {}): DiagnosisSuggestion {
  return {
    dimension: "audience",
    coordinate_key: "cold_problem_aware",
    coordinate_label: "陌生・知道問題",
    direction: "scale_up",
    impact_spend: 500,
    headline: "下一輪把預算往「陌生・知道問題」加碼",
    evidence: "這群人保守 ROAS 2.58x／樂觀 3.17x、覆蓋率 75%",
    agreed_by: ["budget"],
    currency: "TWD",
    numbers: {
      label: "陌生・知道問題", spend: 2000, ad_count: 3, roas: 3.17,
      roas_conservative: 2.58, roas_coverage: 0.75,
    },
    compared_with: [],
    adopted: false,
    ...overrides,
  };
}

function diagnosis(overrides: Partial<Diagnosis> = {}): Diagnosis {
  return {
    status: "succeeded",
    window: { start_date: "2026-09-01", end_date: "2026-09-30", days_with_data: 25 },
    breakeven: { roas: 1.43, source: "規則卡毛利率 70%" },
    directional_only: true,
    suggestions: [suggestion()],
    lenses: {},
    no_tagged_spend: false,
    ...overrides,
  };
}

function Harness() {
  const panel = useDiagnosisPanel("brd_1");
  return (
    <>
      <DiagnosisRunButton panel={panel} />
      <DiagnosisResult panel={panel} />
    </>
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("DiagnosisPanel 採用", () => {
  it("伺服器說已採用的建議，重新整理後仍是已採用", async () => {
    vi.mocked(fetchDiagnosis).mockResolvedValue(
      diagnosis({ suggestions: [suggestion({ adopted: true }), suggestion({ headline: "另一條" })] }),
    );
    render(<Harness />);
    const adopted = await screen.findByRole("button", { name: "已採用" });
    expect((adopted as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "採用" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("新一輪送出中（busy）時，上一輪的採用按不下去", async () => {
    const previous = diagnosis();
    vi.mocked(fetchDiagnosis).mockResolvedValue(previous);
    // POST answers with the previous (still succeeded) round: the new round has not started yet.
    vi.mocked(runDiagnosis).mockResolvedValue(previous);
    render(<Harness />);
    const adopt = await screen.findByRole("button", { name: "採用" });
    expect((adopt as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "跑一次判讀" }));
    await screen.findByRole("button", { name: "判讀中…" });
    expect((screen.getByRole("button", { name: "採用" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("按下採用後重新讀取，已採用由伺服器的旗標撐住", async () => {
    vi.mocked(fetchDiagnosis).mockResolvedValueOnce(diagnosis());
    vi.mocked(adoptSuggestion).mockResolvedValue({ id: "rule_1", content: "x" });
    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: "採用" }));

    vi.mocked(fetchDiagnosis).mockResolvedValue(
      diagnosis({ suggestions: [suggestion({ adopted: true })] }),
    );
    await waitFor(() => expect(fetchDiagnosis).toHaveBeenCalledTimes(2));
    expect(adoptSuggestion).toHaveBeenCalledWith("brd_1", 0);
    expect(await screen.findByRole("button", { name: "已採用" })).toBeTruthy();
  });
});
