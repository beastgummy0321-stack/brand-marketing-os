import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Target } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import {
  getTarget, getTriage, putTarget, TriageRequestRejected, type CampaignTarget, type TargetRequest, type TriageItem,
} from "@/lib/adsTriageApi";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import { Chip, Disclosure, Segmented, TargetRuler, formatAmount, type RulerAd, type RulerCap } from "../patterns";

/** F28-I09: the strategy tab's 「一個上限」 card (prototype v9 `targetBlock()`): the one cost-per-result cap, edited in
 * place and saved through `PUT .../target` (revision guard), beside the mid ruler of this campaign's graded ads.
 * Every number comes from `campaign.cap` (`app/ads/targets.py::resolve`) — nothing is recomputed or defaulted here. */

const TARGET_CONFLICT = "target_conflict";
const fmt = (v: number | null | undefined) => formatAmount(v) ?? "未知";
/** ROAS 參考 = price ÷ cap, two decimals at most (kit formatter). */
const roas = (price: number, cap: number) => formatAmount(Math.round((price / cap) * 100) / 100);
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

type Triage = { status: "idle" | "loading" } | { status: "error"; message: string } | { status: "ready"; items: TriageItem[] };

export function CapBlock({ brandId, campaign: c, onCampaignChange }: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const cap = c.cap;
  const hasCap = cap.value !== null;
  const [editOpen, setEditOpen] = useState(false);
  const editing = editOpen || !hasCap;
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [triage, setTriage] = useState<Triage>({ status: "idle" });
  const [triageReload, setTriageReload] = useState(0);

  // Mid ruler: this campaign's graded active ads. A draft has none, so it is not asked for. Keyed on the cap's
  // revision (primitive), so a saved cap regrades once, not on every campaign refetch.
  const isDraft = c.status === "draft";
  useEffect(() => {
    if (isDraft) return;
    let cancelled = false;
    setTriage({ status: "loading" });
    getTriage(brandId, c.id)
      .then((t) => { if (!cancelled) setTriage({ status: "ready", items: t.items }); })
      .catch((err: unknown) => { if (!cancelled) setTriage({ status: "error", message: errorText(err, "讀取廣告失敗。") }); });
    return () => { cancelled = true; };
  }, [brandId, c.id, isDraft, cap.revision, cap.value, triageReload]);

  // 暫用打平: the 打平線 line subtracts 成本含運 from the price. The cost lives on the target read (`GET .../target`,
  // F29 Contract D), not on the campaign's cap view, so it is read only in that state. Until it arrives, or when the
  // read fails, the line keeps the price and ROAS without the subtraction — never a made-up cost.
  const showsBreakEven = !editing && cap.basis === "break_even";
  const [cost, setCost] = useState<number | null>(null);
  useEffect(() => {
    setCost(null);
    if (!showsBreakEven) return;
    let cancelled = false;
    getTarget(brandId, c.id)
      .then((t) => { if (!cancelled) setCost(t.cost); })
      .catch(() => { /* the line stays without the subtraction */ });
    return () => { cancelled = true; };
  }, [brandId, c.id, showsBreakEven, cap.revision, cap.value]);

  const trimmed = value.trim();
  const typed = /^[1-9]\d*$/.test(trimmed) ? Number(trimmed) : null;
  const breakEven = cap.break_even;
  const price = cap.price;

  async function save(body: TargetRequest) {
    setSaving(true);
    setError(null);
    setConflict(false);
    try {
      await putTarget(brandId, c.id, body);
      // Budget scenarios are projected from the cap, so the whole campaign is re-read, not patched locally.
      onCampaignChange(await getCampaign(brandId, c.id));
      setEditOpen(false);
      setValue("");
    } catch (err) {
      if (err instanceof TriageRequestRejected && err.code === TARGET_CONFLICT) setConflict(true);
      else setError(errorText(err, "儲存上限失敗，請稍後再試。"));
    } finally {
      setSaving(false);
    }
  }

  async function reload() {
    setError(null);
    try {
      onCampaignChange(await getCampaign(brandId, c.id));
      setConflict(false);
    } catch (err) {
      setError(errorText(err, "重新讀取失敗，請稍後再試。"));
    }
  }

  const saveOwn = (v: number) => void save({ basis: "own", value: v, expected_revision: cap.revision });

  let left;
  if (editing) {
    const preview = !trimmed
      ? <span className="text-muted-foreground">填一個整數金額</span>
      : typed === null
        ? <span className="text-danger">請填大於 0 的整數金額</span>
        : <span className="text-muted-foreground">{[
            breakEven !== null && (typed >= breakEven ? `比打平 ${fmt(breakEven)} 高 ${fmt(typed - breakEven)}` : `比打平 ${fmt(breakEven)} 低 ${fmt(breakEven - typed)}`),
            price !== null && `ROAS 參考 ${roas(price, typed)}`,
          ].filter(Boolean).join("・")}</span>;
    const beFill = breakEven !== null ? Math.round(breakEven) : null;
    left = (
      <div>
        <div className="text-sm text-muted-foreground">上限・每賣一筆最多花</div>
        <div className="mt-2 flex flex-wrap items-end gap-2.5">
          <label className="inline-flex w-[180px] items-center rounded-lg border border-input bg-card px-3 focus-within:border-primary focus-within:ring-[3px] focus-within:ring-accent">
            <span className="text-muted-foreground">NT$</span>
            <input
              type="number" min={1} step={1} inputMode="numeric" placeholder="例如 450" value={value}
              aria-label="每賣一筆最多花多少（上限）"
              className="numeric w-full border-0 bg-transparent px-2 py-2 text-base font-semibold outline-none"
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && typed !== null && !saving) saveOwn(typed); }}
              autoFocus={editOpen}
            />
          </label>
          {beFill !== null && <Button variant="outline" size="sm" onClick={() => setValue(String(beFill))}>用打平 {fmt(beFill)}</Button>}
          <Button variant="outline" disabled={typed === null || saving} onClick={() => typed !== null && saveOwn(typed)}>{saving ? "儲存中…" : "儲存上限"}</Button>
          {editOpen && hasCap && <Button variant="ghost" size="sm" disabled={saving} onClick={() => { setEditOpen(false); setValue(""); setError(null); }}>取消</Button>}
        </div>
        <div className="mt-2 min-h-5 text-sm" aria-live="polite">{preview}</div>
        {cap.missing.includes("product_cost") && (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Chip tone="warn">沒有商品成本</Chip>
            <Button asChild variant="link" size="sm" className="h-auto px-0">
              <Link to={cap.knowledge_product_id ? `/brands/${brandId}/products/${cap.knowledge_product_id}/onboarding?step=4` : `/brands/${brandId}/products`}>去填商品成本</Link>
            </Button>
          </div>
        )}
      </div>
    );
  } else if (cap.basis === "break_even") {
    const v = cap.value as number;
    left = (
      <div>
        <div className="text-sm text-muted-foreground">上限・每賣一筆最多花</div>
        <div className="mt-1 flex flex-wrap items-center gap-2.5"><CapValue value={v} /><Chip tone="warn">暫用打平</Chip></div>
        <div className="numeric mt-1 text-xs text-muted-foreground">
          {`打平線 ${fmt(v)}`}
          {price !== null && (cost !== null ? `：售價 ${fmt(price)} − 成本含運 ${fmt(cost)}・ROAS 參考 ${roas(price, v)}` : `・售價 ${fmt(price)}・ROAS 參考 ${roas(price, v)}`)}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={saving} onClick={() => saveOwn(v)}>就用 {fmt(v)}</Button>
          <Button variant="ghost" size="sm" disabled={saving} onClick={() => setEditOpen(true)}>設定自己的上限</Button>
        </div>
      </div>
    );
  } else {
    const v = cap.value as number;
    // The stored source wins (as on ConfirmBriefPage): the target writer resets it to `user` when the cap changes.
    // F50: a cap the model read from the 一句話 sentence (`parsed`, like `system`) is a guess, never 「自己填」.
    const source = c.context_json?.field_sources?.cap;
    const ownWord = source === "parsed" || source === "system" ? "猜的，請確認"
      : source === "copied" ? "沿用上一期" : source === "break_even" ? "打平線"
      : breakEven !== null && cap.own_value === breakEven ? "打平值" : "自己填";
    left = (
      <div>
        <div className="text-sm text-muted-foreground">上限・每賣一筆最多花</div>
        <div className="mt-1 flex flex-wrap items-center gap-2.5"><CapValue value={v} /><Chip>{ownWord}</Chip></div>
        {(price !== null || breakEven !== null) && (
          <div className="numeric mt-1 text-xs text-muted-foreground">
            {[price !== null && `ROAS 參考 ${roas(price, v)}`, breakEven !== null && `打平 ${fmt(breakEven)}`].filter(Boolean).join("・")}
          </div>
        )}
        <div className="mt-3"><Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>修改</Button></div>
      </div>
    );
  }

  const rulerCap: RulerCap | null = hasCap && cap.basis ? { value: cap.value as number, basis: cap.basis } : null;
  const items = triage.status === "ready" ? triage.items : [];
  const ads: RulerAd[] = items.map((item) => ({
    id: item.entity_id,
    name: item.name ?? "（未命名廣告）",
    grade: item.grade,
    gradeLabel: item.grade_label,
    costPerResult: item.current.cost_per_result,
    spend: item.current.spend,
    thumbnailUrl: item.thumbnail_url,
  }));
  const needsSource = cap.missing.includes("product") || cap.missing.includes("result_kind");

  return (
    <section className="surface px-[22px] py-5" aria-labelledby="cap-block-title">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 id="cap-block-title" className="text-[15px] font-semibold">一個上限</h2>
        <span className="text-sm text-muted-foreground">分等級・清理・加預算都看這個數字</span>
      </div>
      <div className="grid grid-cols-[44px_minmax(220px,300px)_minmax(0,1fr)] items-center gap-x-6 gap-y-[18px]">
        <span
          className={cn("grid size-11 place-items-center rounded-xl", cap.basis === "own" ? "bg-accent text-accent-foreground" : "bg-zone-watch text-warning")}
          aria-hidden="true"
        >
          <Target className="size-5" />
        </span>
        {left}
        <div className="min-w-0">
          <TargetRuler ads={ads} cap={rulerCap} breakEven={breakEven} size="mid" tray={false} />
          {triage.status === "error" && (
            <p role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-xs text-warning">
              廣告讀取失敗：{triage.message}
              <Button variant="link" size="sm" className="h-auto px-0" onClick={() => setTriageReload((n) => n + 1)}>重新讀取</Button>
            </p>
          )}
        </div>
      </div>
      {conflict && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
          <span className="flex-1">這個活動的上限剛被更新，你的數字還沒存。重新讀取後再改一次。</span>
          <Button variant="outline" size="sm" onClick={() => void reload()}>重新讀取</Button>
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      {needsSource && (
        <div className="mt-4">
          <Disclosure label={cap.missing.includes("product") ? "選商品與成果（算打平要用）" : "選這個活動算哪一種成果"}>
            <CapSourceForm brandId={brandId} campaignId={c.id} onSaved={onCampaignChange} />
          </Disclosure>
        </div>
      )}
    </section>
  );
}

function CapValue({ value }: { value: number }) {
  return <span className="numeric text-[30px] leading-[1.1] font-[650] tracking-[-0.025em]">NT${fmt(value)}</span>;
}

/** The fold for a campaign that has no product or no result kind yet: the product break-even needs one, grading
 * needs the other. Mounted only when the fold is first opened (Disclosure), so its reads never run otherwise. A
 * derived `result_kind` is never re-sent (it would freeze the guess into the column) — only a changed pick is. */
function CapSourceForm({ brandId, campaignId, onSaved }: {
  brandId: string; campaignId: string; onSaved: (campaign: CampaignDetail) => void;
}) {
  const [target, setTarget] = useState<CampaignTarget | null>(null);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [productId, setProductId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    Promise.all([getTarget(brandId, campaignId), fetchProductList(brandId)])
      .then(([t, list]) => {
        if (cancelled) return;
        setTarget(t);
        // F50 Contract R: the break-even needs money, and money lives on sellable sell-ways only.
        setProducts(list.filter((p) => p.kind === "sell_way"));
        setKind(t.result_kind);
        setProductId(t.product_ids[0] ?? "");
      })
      .catch((err: unknown) => { if (!cancelled) setLoadError(errorText(err, "讀取失敗。")); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, reloadKey]);

  if (loadError) {
    return (
      <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-warning">
        {loadError}
        <Button variant="link" size="sm" className="h-auto px-0" onClick={() => setReloadKey((n) => n + 1)}>重新讀取</Button>
      </p>
    );
  }
  if (!target) return <p className="text-sm text-muted-foreground">讀取中…</p>;

  const kindChanged = kind !== target.result_kind;
  const productChanged = productId !== (target.product_ids[0] ?? "");
  const needsProduct = (kind ?? target.result_kind) === "purchase";

  async function save() {
    if (!target) return;
    setSaving(true);
    setError(null);
    const body: TargetRequest = { expected_revision: target.revision };
    if (kindChanged) body.result_kind = kind;
    if (productChanged && productId) body.product_id = productId;
    try {
      await putTarget(brandId, campaignId, body);
      onSaved(await getCampaign(brandId, campaignId));
    } catch (err) {
      if (err instanceof TriageRequestRejected && err.code === TARGET_CONFLICT) {
        setError("這個活動的設定剛被更新，已重新讀取，請再選一次。");
        setReloadKey((n) => n + 1);
      } else {
        setError(errorText(err, "儲存失敗，請稍後再試。"));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-muted-foreground">這個活動算哪一種成果</span>
        {/* No option is pressed until the backend knows one: an honest unpicked state, not a guessed default. */}
        <Segmented<string>
          label="這個活動算哪一種成果"
          options={target.result_kinds.map((o) => ({ value: o.kind, label: o.label }))}
          value={kind ?? ""}
          onChange={setKind}
        />
      </div>
      {needsProduct && (
        <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
          商品
          <select
            className="h-9 min-w-56 rounded-md border border-input bg-card px-3 text-sm text-foreground"
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
          >
            <option value="">請選擇商品</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}{p.economics_status === "none" ? "（還沒有成本）" : ""}</option>
            ))}
          </select>
        </label>
      )}
      <Button variant="outline" disabled={saving || (!kindChanged && !(productChanged && productId))} onClick={() => void save()}>
        {saving ? "儲存中…" : "儲存"}
      </Button>
      {error && <p role="alert" className="w-full text-sm text-danger">{error}</p>}
    </div>
  );
}
