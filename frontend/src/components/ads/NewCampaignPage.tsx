import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Sparkles, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { createCampaign } from "@/lib/adsApi";

const CONSTRAINT_FIELDS: { key: string; label: string }[] = [
  { key: "budget", label: "預算上限" },
  { key: "platform", label: "必須使用的平台" },
  { key: "product", label: "指定商品" },
  { key: "audience", label: "指定受眾" },
  { key: "other", label: "其他限制" },
];

function todayIso(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

/** 建立 Campaign（F03-I13）：一句話＋投放期間＋選填限制條件 → `POST /campaigns`。
 * 原型 `screen-new.js` 的版面，改用 kit 元件；解析中的讀取狀態說明正在讀什麼，
 * `parsed: false` 不擋路，照樣導去策略頁，只是帶一句提醒（透過 navigate state，
 * 由工作區頁面顯示——不做成死路）。 */
export function NewCampaignPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [goalText, setGoalText] = useState("");
  const [startDate, setStartDate] = useState(todayIso(0));
  const [endDate, setEndDate] = useState(todayIso(30));
  const [openConstraints, setOpenConstraints] = useState<Record<string, boolean>>({});
  const [constraintValues, setConstraintValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleConstraint(key: string) {
    setOpenConstraints((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSubmit() {
    if (!goalText.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    const constraints: Record<string, unknown> = {};
    for (const field of CONSTRAINT_FIELDS) {
      const value = constraintValues[field.key]?.trim();
      if (openConstraints[field.key] && value) constraints[field.key] = value;
    }
    try {
      const draft = await createCampaign(brandId, {
        goal_text: goalText,
        start_date: startDate,
        end_date: endDate,
        ...(Object.keys(constraints).length > 0 ? { constraints } : {}),
      });
      navigate(`/brands/${brandId}/ads/campaigns/${draft.id}?tab=strategy`, {
        state: draft.parsed
          ? undefined
          : { parseWarning: "這句話沒有完全被理解，欄位可能需要手動修正。" },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立 Campaign 失敗，請稍後再試。");
      setSubmitting(false);
    }
  }

  if (submitting) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <div className="mx-auto mb-4 size-6 animate-spin rounded-full border-2 border-border border-t-primary" />
        <p className="text-sm font-medium">讀取品牌／商品／投放紀錄…</p>
        <p className="mt-1 text-sm text-muted-foreground">
          行銷駕駛艙正在整理這個品牌的資料，準備第一版策略。
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="建立 Campaign"
        description="用一句話描述你想達成的目標，行銷駕駛艙會幫你規劃初版策略。"
      />
      <div className="surface max-w-3xl">
        <div className="surface-body flex flex-col gap-4">
          <div>
            <label className="mb-2 block text-sm font-medium" htmlFor="goal-textarea">
              你這次想做到什麼？
            </label>
            <Textarea
              id="goal-textarea"
              value={goalText}
              onChange={(e) => setGoalText(e.target.value)}
              placeholder="9 月想推 Beast Gummy，上班族為主，希望增加購買，預算大約三萬。"
              className="min-h-28"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-sm text-muted-foreground" htmlFor="goal-start">
                開始日期
              </label>
              <Input
                id="goal-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-muted-foreground" htmlFor="goal-end">
                結束日期
              </label>
              <Input
                id="goal-end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="mb-2 block text-sm text-muted-foreground">限制條件（選填）</label>
            <div className="flex flex-wrap gap-2">
              {CONSTRAINT_FIELDS.map((field) =>
                openConstraints[field.key] ? (
                  <span
                    key={field.key}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border py-1 pl-3 pr-1.5 text-sm"
                  >
                    {field.label}
                    <Input
                      aria-label={field.label}
                      value={constraintValues[field.key] ?? ""}
                      onChange={(e) =>
                        setConstraintValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                      }
                      placeholder="輸入…"
                      className="h-7 w-36 px-2 text-xs"
                    />
                    <button
                      type="button"
                      aria-label={`移除${field.label}`}
                      onClick={() => toggleConstraint(field.key)}
                      className="rounded-full p-0.5 hover:bg-muted"
                    >
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    key={field.key}
                    type="button"
                    onClick={() => toggleConstraint(field.key)}
                    className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-sm text-muted-foreground hover:bg-muted"
                  >
                    <Plus size={13} />
                    {field.label}
                  </button>
                ),
              )}
            </div>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button onClick={handleSubmit} disabled={!goalText.trim()}>
              <Sparkles size={15} />
              讓行銷駕駛艙規劃
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
