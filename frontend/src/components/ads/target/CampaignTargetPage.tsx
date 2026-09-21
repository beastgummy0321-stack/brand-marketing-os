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

// F19-I05 Blocked-if：這個活動能接受的 result_kind 清單，沒有任何既有 API 或共用常數可查
// （`app/ads/targets.py`／`app/ads/repository.py::save_campaign_target` 對 `result_kind` 完全
// 不驗證，是自由字串；沒有任何路由回傳「這個活動能接受哪些成果」）。依票面指示：不假造一份
// 平台專屬清單，Card 1 因此只唯讀顯示目前已知的成果，不提供選擇——這裡的翻譯只是把已知的
// 少數代碼轉成中文顯示，未知代碼原樣顯示，不是在編一份選項清單。
const RESULT_KIND_LABEL: Record<string, string> = { purchase: "購買", engagement: "互動", lead: "名單" };
function resultKindLabel(kind: string | null): string | null {
  if (!kind) return null;
  return RESULT_KIND_LABEL[kind] ?? kind;
}

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

// 逐字對照 `app/ads/routes.py::_TARGET_ERRORS["target_conflict"]`——用來把「版本衝突」跟其他
// 4xx 錯誤分開處理；`adsTriageApi.ts` 的 `TriageRequestRejected` 只帶訊息，不帶狀態碼。
const TARGET_CONFLICT_MESSAGE = "目標設定已被更新，請重新載入後再試一次。";

interface Draft {
  basis: Basis;
  ownValue: string;
  productId: string;
  price: string;
  variableCost: string;
}

function draftFrom(target: CampaignTarget): Draft {
  const basis: Basis = target.basis ?? "trailing_30";
  return {
    basis,
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

  const [draft, setDraft] = useState<Draft>({ basis: "trailing_30", ownValue: "", productId: "", price: "", variableCost: "" });
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
      if (err instanceof TriageRequestRejected && err.message === TARGET_CONFLICT_MESSAGE) {
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

  const resultKind = resultKindLabel(target.result_kind);
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
          {resultKind ? (
            <Badge variant="secondary">{resultKind}</Badge>
          ) : (
            <p className="text-sm text-muted-foreground">
              尚未知道——累積到這個活動自己的投放資料後才會知道。
            </p>
          )}
        </div>
      </section>

      <section className="surface" aria-labelledby="target-cost-heading">
        <div className="surface-header">
          <h2 id="target-cost-heading">{resultKind ? `每次${resultKind}最多花多少` : "每次成果最多花多少"}</h2>
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
              目標每次{resultKind ?? "成果"}成本
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
