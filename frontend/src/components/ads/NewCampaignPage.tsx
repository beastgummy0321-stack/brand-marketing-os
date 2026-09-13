import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Boxes, ImageIcon, LineChart, Plus, Share2, Sparkles, Target, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { createCampaign } from "@/lib/adsApi";

const CONSTRAINT_FIELDS: { key: string; label: string; placeholder: string; isDate?: boolean }[] = [
  { key: "budget", label: "預算上限", placeholder: "例如 NT$ 30,000" },
  { key: "platform", label: "指定平台", placeholder: "例如 Facebook" },
  { key: "product", label: "指定商品", placeholder: "選擇商品" },
  { key: "dates", label: "日期", placeholder: "", isDate: true },
  { key: "other", label: "其他限制", placeholder: "例如受眾、地區等" },
];

/** 右欄說明卡（圖 3）：純靜態文字，不畫插圖／貼紙（R6 裁決）。 */
const AUTO_ITEMS: { icon: typeof Boxes; title: string; detail: string }[] = [
  { icon: Boxes, title: "商品", detail: "判斷主打商品與賣點" },
  { icon: Target, title: "目標", detail: "設定行銷目標與關鍵指標" },
  { icon: Share2, title: "平台", detail: "建議最適合的廣告平台與版位" },
  { icon: LineChart, title: "預算建議", detail: "分配預算並提供投放時程建議" },
  { icon: ImageIcon, title: "素材需求", detail: "建議所需素材類型與數量" },
];

/** 建立 Campaign 步驟一（F04-I12，圖 3）：一句話＋選填限制條件 → `POST /campaigns`。
 * 日期不是必填欄位（F04-I11 後端會從句子判斷，判斷不出來就今天～+30 天並標「系統帶入」）；
 * 這裡只在「只填一邊」時擋下來。送出成功後導去步驟二（`ConfirmBriefPage`）確認理解，
 * 不再直接進策略頁——那一步才是第二次、也是最後一次模型呼叫。 */
export function NewCampaignPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [goalText, setGoalText] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [openConstraints, setOpenConstraints] = useState<Record<string, boolean>>({});
  const [constraintValues, setConstraintValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleConstraint(key: string) {
    setOpenConstraints((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSubmit() {
    if (!goalText.trim() || submitting) return;
    if ((startDate && !endDate) || (!startDate && endDate)) {
      setError("開始與結束日期請一起填，或兩個都留空。");
      return;
    }
    setSubmitting(true);
    setError(null);
    const constraints: Record<string, unknown> = {};
    for (const field of CONSTRAINT_FIELDS) {
      if (field.isDate) continue;
      const value = constraintValues[field.key]?.trim();
      if (openConstraints[field.key] && value) constraints[field.key] = value;
    }
    try {
      const draft = await createCampaign(brandId, {
        goal_text: goalText,
        ...(startDate && endDate ? { start_date: startDate, end_date: endDate } : {}),
        ...(Object.keys(constraints).length > 0 ? { constraints } : {}),
      });
      navigate(`/brands/${brandId}/ads/new/${draft.id}`, {
        state: draft.parsed
          ? undefined
          : { parseWarning: "這句話沒有完全被理解，請確認下面的欄位。" },
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
      <Link
        to={`/brands/${brandId}/ads`}
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> 投放中心
      </Link>
      <PageHeader
        title="建立投放計畫"
        description="只要告訴我們你的目標，行銷駕駛艙會幫你整理投放策略、預算、素材與排程。"
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="surface">
          <div className="surface-body flex flex-col gap-4">
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="goal-textarea">
                你這次想做到什麼？
              </label>
              <p className="mb-2 text-sm text-muted-foreground">
                用自然語言告訴我們你的想法，越詳細越好。
              </p>
              <Textarea
                id="goal-textarea"
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                placeholder="9 月想推 Beast Gummy，上班族為主，希望增加購買，預算大約三萬。"
                className="min-h-28"
                maxLength={500}
              />
              <p className="mt-1 text-right text-xs text-muted-foreground">
                {goalText.length} / 500
              </p>
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
                      {field.isDate ? (
                        <span className="flex items-center gap-1">
                          <Input
                            aria-label="開始日期"
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="h-7 w-32 px-2 text-xs"
                          />
                          <span className="text-muted-foreground">~</span>
                          <Input
                            aria-label="結束日期"
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="h-7 w-32 px-2 text-xs"
                          />
                        </span>
                      ) : (
                        <Input
                          aria-label={field.label}
                          value={constraintValues[field.key] ?? ""}
                          onChange={(e) =>
                            setConstraintValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                          }
                          placeholder={field.placeholder}
                          className="h-7 w-36 px-2 text-xs"
                        />
                      )}
                      <button
                        type="button"
                        aria-label={`移除${field.label}`}
                        onClick={() => {
                          toggleConstraint(field.key);
                          if (field.isDate) {
                            setStartDate("");
                            setEndDate("");
                          }
                        }}
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
                產生建議
              </Button>
            </div>
          </div>
        </div>
        <div className="surface">
          <div className="surface-body flex flex-col gap-4">
            <div>
              <h2 className="flex items-center gap-1.5 text-[15px] font-semibold">
                <Sparkles size={15} className="text-primary" /> 行銷駕駛艙會自動幫你整理
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                我們會根據你的描述，快速產生完整的投放計畫。
              </p>
            </div>
            <div className="flex flex-col gap-3">
              {AUTO_ITEMS.map((item) => (
                <div key={item.title} className="flex items-center gap-3">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent">
                    <item.icon className="size-4 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
