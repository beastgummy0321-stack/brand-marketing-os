import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { getLaunchSettings, type BidStrategy, type LaunchSettingsView } from "@/lib/adsLaunchSettingsApi";
import { useApiRead } from "@/lib/useApiRead";
import { ReadFailed, formatAmount } from "../patterns";

/** F29-I16 platform stage (prototype v10 `pubPlatform()` 投放設定 box, hash `pub/fall/platform`): the approved launch
 * settings as plain values, each with 複製, to pick the same choices on the platform. Read only; the labels come
 * from the options the API sent with the values. */

const label = <T extends string>(options: { value: T; label: string }[], value: T | null | undefined) =>
  options.find((o) => o.value === value)?.label ?? (value ? String(value) : "沒有設定");

/** The strategies whose platform setting carries one amount (F47-I06, `launch_settings.CAPPED_BIDS`). */
export const isCappedBid = (strategy: BidStrategy) => strategy === "cost_cap" || strategy === "bid_cap";

/** 出價方式 with its amount for a capped strategy (F47-I06): 「單次成果成本上限 450」; 「金額還沒填」 when unset. */
function bidText({ values: v, options: o }: LaunchSettingsView) {
  const name = label(o.bid_strategy, v.bid_strategy);
  if (!isCappedBid(v.bid_strategy)) return name;
  return v.bid_amount === null || v.bid_amount === undefined ? `${name}（金額還沒填）` : `${name} ${formatAmount(v.bid_amount)}`;
}

/** One display row per value, in the prototype's order (`setRows()`). */
function settingRows(view: LaunchSettingsView): { key: string; label: string; value: string }[] {
  const { values: v, options: o } = view;
  const age = `${v.audience.age_min}–${v.audience.age_max}${v.audience.age_max === 65 ? "+" : ""} 歲`;
  const positions = v.placement.positions.map((p) => label(o.positions, p)).join("、");
  const pixel = v.pixel_id === null
    ? "沒有選像素"
    : (() => { const name = o.pixels?.find((p) => p.id === v.pixel_id)?.name; return name ? `${name}（${v.pixel_id}）` : v.pixel_id; })();
  return [
    { key: "optimization_event", label: "優化事件", value: label(o.optimization_event, v.optimization_event) },
    { key: "bid_strategy", label: "出價方式", value: bidText(view) },
    { key: "placement", label: "版位", value: v.placement.mode === "auto" ? "自動版位" : `手動：${positions || "還沒選"}` },
    { key: "age", label: "年齡", value: age },
    { key: "gender", label: "性別", value: label(o.genders, v.audience.gender) },
    { key: "countries", label: "地區", value: v.audience.countries.map((c) => label(o.countries, c)).join("、") || "沒有地區" },
    { key: "pixel_id", label: "像素", value: pixel },
    { key: "utm", label: "UTM", value: v.utm || "沒有設定" },
  ];
}

export function LaunchSettingsCopy({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const read = useApiRead((signal) => getLaunchSettings(brandId, campaignId, signal), [brandId, campaignId]);
  return (
    <section aria-label="投放設定" data-slot="launch-settings-copy" className="surface px-[22px] py-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">投放設定</h2>
        <span className="text-sm text-muted-foreground">建每個廣告組時照這組選</span>
      </div>
      {read.status === "error" ? (
        <ReadFailed what={`投放設定讀不到：${read.error}。核准的設定沒有變，重試後再照著選。`} onRetry={read.reload} />
      ) : !read.data ? (
        <p role="status" className="text-sm text-muted-foreground">讀取投放設定…</p>
      ) : (
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground">
          {settingRows(read.data).map((row) => (
            <span key={row.key} className="inline-flex min-w-0 items-start gap-1.5">
              <span className="shrink-0">{row.label}</span>
              <b className="font-semibold text-foreground [overflow-wrap:anywhere]">{row.value}</b>
              <CopyIconButton label="複製" ariaLabel={`複製${row.label}`} getText={() => row.value} className="px-1.5 py-px" />
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
