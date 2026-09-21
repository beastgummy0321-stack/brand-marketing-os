import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Badge } from "@/components/layout/ui/badge";
import { getCampaign } from "@/lib/adsApi";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import {
  getTarget,
  putTarget,
  TriageRequestRejected,
  type CampaignTarget,
  type TargetRequest,
} from "@/lib/adsTriageApi";
import { useAssetDraftGuard } from "../useAssetDraftGuard";

type Basis = NonNullable<CampaignTarget["basis"]>;

// 三種依據直接照抄 `adsTriageApi.ts` 的 `CampaignTarget["basis"]`／`TargetRequest["basis"]`
// 聯集型別——不是另外發明的清單，跟契約同一份詞彙。
const BASIS_OPTIONS: { key: Basis; label: string; hint: string }[] = [
  { key: "break_even", label: "打平值", hint: "賣一件剛好不虧" },
  { key: "trailing_30", label: "自己近 30 天", hint: "近 30 天的實際成本" },
  { key: "own", label: "自訂", hint: "自己填一個更嚴格的數字" },
];

const MISSING_LABEL: Record<string, string> = {
  product: "尚未選商品",
  product_cost: "商品還沒有成本",
  trailing_30: "近 30 天資料不足",
  mixed_result_definition: "近期成果定義不一致",
  needs_resync: "資料需要重新同步",
  result_unknown_days: "這段期間看不出成果",
};
function missingLabel(reason: string): string {
  return MISSING_LABEL[reason] ?? reason;
}

// F19-I06：版本衝突用錯誤信封的 `code`（`app/shared/web.py::ApiError` → `TriageRequestRejected
// .code`）認出來，不再比對中文訊息字串——訊息文字以後改了也不會讓前端誤判成別種錯誤。
const TARGET_CONFLICT_CODE = "target_conflict";

interface Draft {
  basis: Basis;
  resultKind: string | null;
  ownValue: string;
  productId: string;
  price: string;
  variableCost: string;
}

function draftFrom(target: CampaignTarget): Draft {
  const basis: Basis = target.basis ?? "trailing_30";
  return {
    basis,
    resultKind: target.result_kind,
    ownValue: basis === "own" && target.value !== null ? String(target.value) : "",
    productId: target.product_ids[0] ?? "",
    price: "",
    variableCost: "",
  };
}

// F19 re-review A：「建議」只准落在後端這次真的算出來、目前生效的依據上——`target.basis`
// 是 break_even 或 trailing_30 時才有「建議」，own（使用者自訂覆寫）一律不顯示，因為 own
// 生效時 `resolve()` 直接提早回傳（`app/ads/targets.py:88`），根本沒有評估過 break_even／
// trailing_30，這時候在任何一張卡上放「建議」都是編出來的、不是後端真的推薦了什麼。
function recommendedBasis(target: CampaignTarget): Basis | null {
  return target.basis === "break_even" || target.basis === "trailing_30" ? target.basis : null;
}

/** 設定目標頁（F19-I05，v7 原型 ≈ 326–345 行）：這個活動被判斷用的成果與目標成本，純畫面，
 * 不算數——`resolve()` 的結果一律照 GET／PUT 回傳的 `value`／`missing` 顯示，前端不重算打平值。 */
export function CampaignTargetPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;

  const [campaignName, setCampaignName] = useState<string | null>(null);
  const [target, setTarget] = useState<CampaignTarget | null>(null);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [draft, setDraft] = useState<Draft>({ basis: "trailing_30", resultKind: null, ownValue: "", productId: "", price: "", variableCost: "" });
  const [baseline, setBaseline] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([getCampaign(brandId, campaignId), getTarget(brandId, campaignId), fetchProductList(brandId)])
      .then(([campaign, t, productList]) => {
        if (cancelled) return;
        setCampaignName(campaign.name);
        setTarget(t);
        setProducts(productList);
        const next = draftFrom(t);
        setDraft(next);
        setBaseline(JSON.stringify(next));
        setConflict(false);
        setSaveError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "讀取目標設定失敗，請稍後再試。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, campaignId, reloadKey]);

  const dirty = baseline !== "" && JSON.stringify(draft) !== baseline;
  useAssetDraftGuard(dirty, "這個活動的目標還沒儲存，離開將放棄這次編輯。確定離開？");

  // F19 repair #1：0 不是有效目標——0 會讓每一則廣告的花費都「超過門檻」，一律判定停損。
  const ownValid = draft.ownValue.trim() !== "" && Number.isFinite(Number(draft.ownValue)) && Number(draft.ownValue) > 0;
  // F19 repair #2：商品沒有成本（`economics_status==="none"`）送出價格一定會被後端拒絕
  // （product_economics_unknown）——選單本身就不給選，這裡是第二層防呆（例如載入時
  // 商品清單還沒到，或既有的 `product_ids` 剛好是這種商品）。
  const selectedProduct = products.find((p) => p.id === draft.productId);
  const breakEvenValid = draft.productId !== "" && selectedProduct?.economics_status !== "none";
  const valid = draft.basis === "own" ? ownValid : draft.basis === "break_even" ? breakEvenValid : true;
  // F19 repair #4：主按鈕關閉時要說缺什麼，照抄 v7 `setBar({hint})` 的位置（按鈕左邊一小行字）。
  const hint =
    draft.basis === "own" && !ownValid
      ? "還差一個數字"
      : draft.basis === "break_even" && !breakEvenValid
        ? "還差一個商品"
        : "";

  async function save() {
    if (!target || saving || !valid) return;
    setSaving(true);
    setSaveError(null);
    setConflict(false);
    const body: TargetRequest = { basis: draft.basis, expected_revision: target.revision };
    // review fix: `target.result_kind` may already be a *derived* value (`resolve()` returns
    // `"purchase"` for break_even, or the observed kind for trailing_30, even while
    // `ads_campaign.result_kind` is still NULL) — the segmented control pre-selects it so the
    // heading reads right, but re-sending it on every save would freeze that derived guess into
    // the column and permanently block `external_sync.py`'s `... AND result_kind IS NULL` from
    // ever filling it from the real sync. Only send `result_kind` when the user actually picked
    // a different one than what was loaded.
    if (draft.resultKind !== target.result_kind) body.result_kind = draft.resultKind;
    if (draft.basis === "own") body.value = Number(draft.ownValue);
    if (draft.basis === "break_even") {
      body.product_id = draft.productId;
      if (draft.price.trim() !== "") body.price = Number(draft.price);
      if (draft.variableCost.trim() !== "") body.variable_cost = Number(draft.variableCost);
    }
    try {
      const updated = await putTarget(brandId, campaignId, body);
      setTarget(updated);
      const next = draftFrom(updated);
      setDraft(next);
      setBaseline(JSON.stringify(next));
      // F19 repair #3：只有真的解出數字才算「完成」回投放中心；解不出來（value 仍是
      // null）就留在這頁，讓使用者看到最新的 missing 原因，不假裝存檔就等於判斷得出來。
      if (updated.value !== null) navigate(homeHref);
    } catch (err) {
      if (err instanceof TriageRequestRejected && err.code === TARGET_CONFLICT_CODE) {
        setConflict(true);
      } else {
        setSaveError(err instanceof Error ? err.message : "儲存失敗，請稍後再試。");
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "目標" }]} />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  }

  if (loadError || !target) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "目標" }]} />
        <EmptyState
          title="讀取失敗"
          description={loadError ?? "找不到這個活動的目標設定。"}
          onAction={() => setReloadKey((k) => k + 1)}
          actionLabel="重新讀取"
        />
      </div>
    );
  }

  // F19-I06：標題跟著「目前編輯中」的選擇即時反映（v7 `targetPage()` 同一種即時標題），不是
  // 只等存檔後的 `target.result_label`——選項清單一律讀 `target.result_kinds`，不是本地翻譯表。
  const selectedLabel = target.result_kinds.find((o) => o.kind === draft.resultKind)?.label ?? null;
  const recommended = recommendedBasis(target);

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb
        items={[
          { label: "投放中心", href: homeHref },
          { label: campaignName ?? "活動", href: `/brands/${brandId}/ads/campaigns/${campaignId}` },
          { label: "目標" },
        ]}
      />
      <PageHeader title="這個活動的目標" description="設定判斷這個活動好壞的成果與成本門檻。" />

      <section className="surface" aria-labelledby="target-result-heading">
        <div className="surface-header">
          <h2 id="target-result-heading">看什麼成果</h2>
        </div>
        <div className="surface-body">
          {/* F19-I06（v7 原型 `.seg`，prototype-v7-ads-center.html:329）：分段選單，選項讀
           * `target.result_kinds`；沒有任何一個已知時沒有按鈕預選——誠實的未選狀態，不是猜一個
           * 預設。 */}
          {/* review fix: no `overflow-hidden` on the container — the global `:focus-visible`
           * style is an outset outline (tokens.css, 3px offset) and `overflow-hidden` clipped it
           * on the first/last buttons. Corners are rounded per-button instead
           * (`first:rounded-l-md last:rounded-r-md`); `relative focus-visible:z-10` keeps a
           * focused middle button's outline painting over its touching siblings. */}
          <div
            role="group"
            aria-label="看什麼成果"
            className="inline-flex divide-x divide-border rounded-md border border-border"
          >
            {target.result_kinds.map((option) => (
              <button
                key={option.kind}
                type="button"
                aria-pressed={draft.resultKind === option.kind}
                onClick={() => setDraft((d) => ({ ...d, resultKind: option.kind }))}
                className={`relative px-3.5 py-2 text-sm transition-colors first:rounded-l-md last:rounded-r-md focus-visible:z-10 ${
                  draft.resultKind === option.kind
                    ? "bg-accent font-semibold text-accent-foreground"
                    : "bg-card text-foreground hover:bg-muted"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="surface" aria-labelledby="target-cost-heading">
        <div className="surface-header">
          <h2 id="target-cost-heading">{selectedLabel ? `每次${selectedLabel}最多花多少` : "每次成果最多花多少"}</h2>
        </div>
        <div className="surface-body flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" role="group" aria-label="目標依據">
            {BASIS_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-pressed={draft.basis === option.key}
                onClick={() => setDraft((d) => ({ ...d, basis: option.key }))}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  draft.basis === option.key ? "border-primary bg-accent" : "border-border hover:border-primary"
                }`}
              >
                {/* min-h 保留固定高度：不管這張卡有沒有 chip，標題都對齊同一條基線。 */}
                <div className="flex min-h-5 flex-wrap items-center gap-1.5">
                  {option.key === recommended && <Badge variant="secondary">建議</Badge>}
                  {option.key === "trailing_30" && <Badge variant="outline">暫定</Badge>}
                </div>
                <p className="mt-2 text-sm font-semibold">{option.label}</p>
                {/* own 卡的數字只在「不是目前編輯中的依據」時顯示一次；選到 own 時輸入框與
                 * 下面「目前判斷用的目標線」已經各秀一次，這裡不重複第三次（re-review 附加）。 */}
                {option.key === "own" && draft.basis !== "own" && (
                  <p className="metric-number numeric">
                    {target.own_value !== null ? target.own_value.toLocaleString("zh-TW") : "—"}
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">{option.hint}</p>
              </button>
            ))}
          </div>

          {draft.basis === "own" && (
            <label className="flex max-w-xs flex-col gap-1 text-sm">
              目標每次{selectedLabel ?? "成果"}成本
              <Input
                type="number"
                min="0"
                step="0.01"
                value={draft.ownValue}
                onChange={(e) => setDraft((d) => ({ ...d, ownValue: e.target.value }))}
                className="w-40"
              />
            </label>
          )}

          {draft.basis === "break_even" && (
            <div className="grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-sm">
                商品
                <select
                  className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                  value={draft.productId}
                  onChange={(e) => setDraft((d) => ({ ...d, productId: e.target.value }))}
                >
                  <option value="">請選擇商品</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id} disabled={p.economics_status === "none"}>
                      {p.name}
                      {p.economics_status === "none" ? "（尚無售價）" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                售價
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.price}
                  onChange={(e) => setDraft((d) => ({ ...d, price: e.target.value }))}
                  aria-label="售價"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                成本（含運費）
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.variableCost}
                  onChange={(e) => setDraft((d) => ({ ...d, variableCost: e.target.value }))}
                  aria-label="成本（含運費）"
                />
              </label>
            </div>
          )}

          <div>
            {target.value !== null ? (
              <p className="metric-number numeric">{target.value.toLocaleString("zh-TW")}</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {target.missing.length > 0 ? (
                  target.missing.map((reason) => (
                    <Badge key={reason} variant="secondary">
                      {missingLabel(reason)}
                    </Badge>
                  ))
                ) : (
                  <Badge variant="secondary">尚未算出</Badge>
                )}
              </div>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {target.value !== null ? "目前判斷用的目標線" : "填齊後儲存才會算出目標線"}
            </p>
          </div>
        </div>
      </section>

      {conflict && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md bg-warning/10 p-3 text-sm text-warning">
          <p className="flex-1">這個活動的目標已被更新，你的編輯尚未覆蓋新版本。</p>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
            重新讀取最新版本
          </Button>
        </div>
      )}
      {saveError && (
        <p role="alert" className="text-sm text-destructive">
          {saveError}
        </p>
      )}

      {/* re-review B：改回 `sticky`，活在頁面自己的內容流裡——不用猜側欄現在是展開（232／
       * 208px）還是收合（76px），負的左右外距直接抵消 `app-main` 自己的內距（22px／xl 起
       * 28px，跟 tokens.css 的中斷點同一個 1280px），視覺上貼齊內容區左右邊；bar 內距補回
       * 同樣數字，按鈕位置跟上面卡片對齊。外層 `min-h` 讓內容短的頁面 bar 也能貼在畫面最下面
       * （模擬 v7 `.page{flex:1}` 的效果，這裡不能改 AppShell，用自己的 min-height／flex-1
       * 撐開代替）；sticky 元素本身仍在文件流裡，不會蓋到前一張卡，不需要額外的 pb。 */}
      <div className="flex-1" />
      <div className="sticky bottom-0 z-10 -mx-[22px] flex flex-wrap items-center gap-3 border-t border-border bg-card px-[22px] py-3 xl:-mx-7 xl:px-7">
        <Button variant="ghost" asChild>
          <Link to={homeHref}>← 投放中心</Link>
        </Button>
        <div className="ml-auto flex items-center gap-3">
          {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
          <Button onClick={() => void save()} disabled={!dirty || !valid || saving}>
            {saving ? "儲存中…" : "儲存目標"}
          </Button>
        </div>
      </div>
    </div>
  );
}
