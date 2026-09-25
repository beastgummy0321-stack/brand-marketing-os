import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { getLaunchSettings, type LaunchSettingsView } from "@/lib/adsLaunchSettingsApi";
import { useApiRead } from "@/lib/useApiRead";
import { ReadFailed } from "../patterns";

/** F29-I16 platform stage (prototype v10 `pubPlatform()` 投放設定 box, hash `pub/fall/platform`): the approved launch
 * settings as plain values, each with 複製, to pick the same choices on the platform. Read only; the labels come
 * from the options the API sent with the values. */

const label = <T extends string>(options: { value: T; label: string }[], value: T | null | undefined) =>
  options.find((o) => o.value === value)?.label ?? (value ? String(value) : "沒有設定");

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
    { key: "bid_strategy", label: "出價方式", value: label(o.bid_strategy, v.bid_strategy) },
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
