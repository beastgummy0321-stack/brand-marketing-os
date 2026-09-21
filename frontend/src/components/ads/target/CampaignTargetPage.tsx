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

  const valid =
    draft.basis === "own"
      ? draft.ownValue.trim() !== "" && Number.isFinite(Number(draft.ownValue)) && Number(draft.ownValue) >= 0
      : draft.basis === "break_even"
        ? draft.productId !== ""
        : true;

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
      await putTarget(brandId, campaignId, body);
      navigate(homeHref);
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
      <div className="flex max-w-3xl flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "目標" }]} />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  }

  if (loadError || !target) {
    return (
      <div className="flex max-w-3xl flex-col gap-4">
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

  return (
    <div className="flex max-w-3xl flex-col gap-4 pb-4">
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
                <p className="text-sm font-semibold">{option.label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{option.hint}</p>
              </button>
            ))}
          </div>

          {draft.basis === "own" && (
            <label className="flex flex-col gap-1 text-sm">
              目標每次{resultKind ?? "成果"}成本
              <Input
                type="number"
                min="0"
                step="0.01"
                value={draft.ownValue}
                onChange={(e) => setDraft((d) => ({ ...d, ownValue: e.target.value }))}
                className="w-40"
                aria-label={`目標每次${resultKind ?? "成果"}成本`}
              />
            </label>
          )}

          {draft.basis === "break_even" && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-sm">
                商品
                <select
                  className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                  value={draft.productId}
                  onChange={(e) => setDraft((d) => ({ ...d, productId: e.target.value }))}
                  aria-label="打平值商品"
                >
                  <option value="">請選擇商品</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
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

      <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-border bg-card py-3">
        <Button variant="ghost" asChild>
          <Link to={homeHref}>← 投放中心</Link>
        </Button>
        <div className="ml-auto flex items-center gap-3">
          {dirty && <span className="text-xs text-warning">尚未儲存</span>}
          <Button onClick={() => void save()} disabled={!dirty || !valid || saving}>
            {saving ? "儲存中…" : "儲存目標"}
          </Button>
        </div>
      </div>
    </div>
  );
}
