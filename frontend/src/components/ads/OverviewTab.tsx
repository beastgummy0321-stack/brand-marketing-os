import { Check, Sparkles } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { currentBudgetTotal, type ActionRow, type CampaignDetail } from "@/lib/adsApi";

const STAGE_LABELS = ["草稿", "策略", "投放結構", "素材", "投放中", "結案"] as const;
type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";

/** 依「backend state」推出目前走到哪一階段：每個條件只會把 idx 往前推，不回退——
 * 沿著 草稿→策略→投放結構→素材→投放中→結案 的既定順序。 */
function currentStageIndex(c: CampaignDetail): number {
  let idx = 0;
  if (c.budget_basis_json.strategy) idx = 1;
  if (c.groups.length > 0) idx = 2;
  if (c.asset_readiness.total > 0 && c.asset_readiness.ready_count >= c.asset_readiness.total) idx = 3;
  if (c.status === "live" || c.status === "ended") idx = 4;
  if (c.status === "closed") idx = 5;
  return idx;
}

const ACTION_KIND_LABEL: Record<ActionRow["kind"], string> = {
  publish: "發布",
  bind: "配對",
  budget: "預算",
  date: "日期",
  pause: "暫停",
  creative: "素材",
};

const SYNC_STATE_LABEL: Record<ActionRow["sync_state"], string> = {
  pending_manual: "待手動同步",
  confirmed_manual: "已手動同步",
  auto_synced: "自動同步",
};

function diffSummary(action: ActionRow): string {
  const keys = Object.keys(action.after_json);
  if (keys.length === 0) return "－";
  return keys
    .map((key) => `${key}：${String(action.before_json[key] ?? "－")} → ${String(action.after_json[key] ?? "－")}`)
    .join("、");
}

function nextActionFor(c: CampaignDetail, idx: number): { text: string; tab: WorkspaceTab; label: string } {
  if (idx === 5) return { text: "Campaign 已結案，學習已寫入品牌智庫。", tab: "performance", label: "查看成效紀錄" };
  if (idx === 4) {
    return c.status === "ended"
      ? { text: "投放已結束，7 天後自動結案，也可以提前手動結案。", tab: "performance", label: "查看最終成效" }
      : { text: "查看成效與投放狀況。", tab: "performance", label: "查看成效" };
  }
  if (idx === 3) return { text: "素材已就位，接下來完成發布前的檢查與發布。", tab: "structure", label: "前往投放結構" };
  if (idx === 2) return { text: "投放結構已建立，交棒素材或勾選素材已就位。", tab: "assets", label: "前往素材" };
  return { text: "先確認推薦策略與預算情境。", tab: "strategy", label: "前往策略" };
}

export function OverviewTab({
  campaign: c,
  onChangeTab,
}: {
  campaign: CampaignDetail;
  onChangeTab: (tab: WorkspaceTab) => void;
}) {
  const idx = currentStageIndex(c);
  const published = idx >= 4;
  const next = nextActionFor(c, idx);
  const t = currentBudgetTotal(c);
  const hasOutcome = c.outcome.spend > 0 || c.outcome.purchases > 0 || c.outcome.revenue > 0;

  const budgetTile = {
    label: "目前投放組合計",
    value: t.total !== null ? formatCurrency(t.total) : "尚未設定",
    caption:
      t.total !== null
        ? `日預算 ${formatCurrency(t.dailySum)}／天 × ${t.days} 天`
        : "還沒設定投放起訖日",
  };
  const planTile = {
    label: "採用時的計畫",
    value: c.budget_planned !== null ? formatCurrency(c.budget_planned) : "尚未設定",
    caption: c.budget_planned !== null ? "採用策略時的情境金額" : "還沒採用預算情境",
  };

  const tiles = published
    ? [
        {
          label: "花費",
          value: hasOutcome ? formatCurrency(c.outcome.spend) : "還沒有成效資料",
          caption: hasOutcome ? "累計花費・平台回報" : "發布後才會有花費資料",
        },
        budgetTile,
        planTile,
        {
          label: "投放期間",
          value: c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "尚未設定",
          caption: t.days !== null ? `共 ${t.days} 天` : "還沒設定起訖日",
        },
      ]
    : [
        {
          label: "投放平台",
          value: c.groups.length > 0 ? [...new Set(c.groups.map((g) => g.channel_key))].join("・") : "尚未設定",
          caption: c.groups.length > 0 ? "已建立的投放組通路" : "採用策略後才會建立",
        },
        budgetTile,
        planTile,
        {
          label: "投放期間",
          value: c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "尚未設定",
          caption: t.days !== null ? `共 ${t.days} 天` : "還沒設定起訖日",
        },
      ];

  return (
    <div className="flex flex-col gap-4">
      <div className="surface">
        <div className="surface-header">
          <h2>狀態時間軸</h2>
        </div>
        <div className="surface-body flex items-center gap-0 pt-2">
          {STAGE_LABELS.map((label, i) => {
            const done = i < idx;
            const current = i === idx;
            return (
              <div key={label} className="relative flex-1 text-center">
                {i > 0 && (
                  <div
                    className={`absolute top-[9px] right-1/2 left-[-50%] h-0.5 ${
                      done || current ? "bg-primary" : "bg-border"
                    }`}
                  />
                )}
                <div
                  className={`relative z-10 mx-auto mb-1.5 flex size-[18px] items-center justify-center rounded-full text-primary-foreground ${
                    done ? "bg-success" : current ? "bg-primary" : "bg-border"
                  }`}
                >
                  {done && <Check size={11} />}
                </div>
                <div className={`text-sm ${current ? "font-semibold" : ""}`}>{label}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {tiles.map((tile) => (
          <article className="surface p-5" key={tile.label}>
            <div className="mb-3 text-xs text-muted-foreground">{tile.label}</div>
            <p className="metric-number">{tile.value}</p>
            <div className="mt-1 text-xs text-muted-foreground">{tile.caption}</div>
          </article>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        購買、CPA、ROAS 等成效數字在成效分頁——那裡分得出「未追蹤」與 0。
      </p>

      <div className="surface">
        <div className="surface-header">
          <h2 className="flex items-center gap-1.5">
            <Sparkles size={15} /> 下一步
          </h2>
        </div>
        <div className="surface-body flex items-center justify-between gap-4">
          <span className="text-sm">{next.text}</span>
          <Button variant="outline" size="sm" onClick={() => onChangeTab(next.tab)}>
            {next.label}
          </Button>
        </div>
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>近期異動紀錄</h2>
        </div>
        <div className="surface-body">
          {c.actions.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">還沒有異動紀錄。</p>
          ) : (
            c.actions.map((a) => (
              <div key={a.id} className="flex flex-col gap-1 border-t border-border py-2 first:border-t-0">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{ACTION_KIND_LABEL[a.kind]}</span>
                  <span className="text-muted-foreground">{diffSummary(a)}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {a.approved_by ?? "系統"} ・ {SYNC_STATE_LABEL[a.sync_state]} ・ {a.created_at}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
