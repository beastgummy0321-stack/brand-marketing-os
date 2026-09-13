import { useEffect, useState } from "react";
import type { IntakeDraft, Offering, OfferingAssumptionField, OfferingInput, OfferingsData } from "@/lib/intakeApi";
import { fetchOfferings, saveOfferings } from "@/lib/intakeApi";
import { Badge } from "../shared/Badge";

type SellType = "product" | "service" | "both";
type AdDelivery = "direct" | "ask" | "lead";

interface VariantRow {
  productId?: string;
  label: string;
  price: string;
  cost: string;
  costAssumed: boolean;
  shipping: string;
  shippingAssumed: boolean;
}

interface ProductGroup {
  productId?: string;
  name: string;
  variants: VariantRow[];
}

interface ServiceState {
  productId?: string;
  price: string;
  noCost: boolean;
  cost: string;
  costAssumed: boolean;
  closeRateChoice: "3" | "5" | "10" | "custom" | null;
  closeRateCustom: string;
  closeRateAssumed: boolean;
}

const SELL_TYPE_OPTIONS: { v: SellType; l: string }[] = [
  { v: "product", l: "商品" },
  { v: "service", l: "服務" },
  { v: "both", l: "兩者" },
];

const AD_DELIVERY_OPTIONS: { v: AdDelivery; l: string }[] = [
  { v: "direct", l: "直接下單" },
  { v: "ask", l: "先詢問再成交" },
  { v: "lead", l: "留資料（名單）" },
];

const CLOSE_RATE_OPTIONS: { v: "3" | "5" | "10" | "custom"; l: string }[] = [
  { v: "3", l: "1 of 3" },
  { v: "5", l: "1 of 5" },
  { v: "10", l: "1 of 10" },
  { v: "custom", l: "自己填" },
];

function blankVariant(label: string): VariantRow {
  return { label, price: "", cost: "", costAssumed: false, shipping: "", shippingAssumed: false };
}

function blankProductGroup(): ProductGroup {
  return { name: "", variants: [blankVariant("單品")] };
}

function blankService(): ServiceState {
  return {
    price: "", noCost: false, cost: "", costAssumed: false,
    closeRateChoice: null, closeRateCustom: "", closeRateAssumed: false,
  };
}

/** 從既有 offerings 反推畫面狀態：有 `close_rate` 的是服務、沒有的是商品
 * （票面規則，不開新欄位判斷業務類型）。 */
function deriveFromOfferings(offerings: Offering[]): { products: ProductGroup[]; service: ServiceState | null } {
  const parents = offerings.filter((o) => o.parent_id === null);
  const products: ProductGroup[] = [];
  let service: ServiceState | null = null;

  for (const parent of parents) {
    const variants = offerings.filter((o) => o.parent_id === parent.product_id);
    const rows = variants.length > 0 ? variants : [parent];
    const isService = rows.some((r) => r.close_rate !== null);
    if (isService) {
      const r = rows[0];
      service = {
        productId: r.product_id,
        price: r.selling_price != null ? String(r.selling_price) : "",
        noCost: r.unit_variable_cost === 0,
        cost: r.unit_variable_cost != null ? String(r.unit_variable_cost) : "",
        costAssumed: r.assumptions.includes("cost"),
        closeRateChoice: r.close_rate != null ? closeRateToChoice(r.close_rate) : null,
        closeRateCustom: r.close_rate != null ? String(Math.round(r.close_rate * 100)) : "",
        closeRateAssumed: r.assumptions.includes("close_rate"),
      };
    } else {
      products.push({
        productId: parent.product_id,
        name: variants.length > 0 ? parent.name : "",
        variants: rows.map((r) => ({
          productId: variants.length > 0 ? r.product_id : undefined,
          label: variants.length > 0 ? labelFromName(parent.name, r.name) : "單品",
          price: r.selling_price != null ? String(r.selling_price) : "",
          cost: r.unit_variable_cost != null ? String(r.unit_variable_cost) : "",
          costAssumed: r.assumptions.includes("cost"),
          shipping: r.shipping_cost != null ? String(r.shipping_cost) : "",
          shippingAssumed: r.assumptions.includes("shipping"),
        })),
      });
    }
  }
  return { products, service };
}

function labelFromName(parentName: string, fullName: string): string {
  const prefix = `${parentName} · `;
  return fullName.startsWith(prefix) ? fullName.slice(prefix.length) : fullName;
}

function closeRateToChoice(rate: number): "3" | "5" | "10" | "custom" {
  if (Math.abs(rate - 1 / 3) < 0.001) return "3";
  if (Math.abs(rate - 1 / 5) < 0.001) return "5";
  if (Math.abs(rate - 1 / 10) < 0.001) return "10";
  return "custom";
}

function closeRateValue(service: ServiceState): number | null {
  if (service.closeRateChoice === "custom") {
    const pct = parseFloat(service.closeRateCustom);
    return Number.isFinite(pct) && pct > 0 ? pct / 100 : null;
  }
  if (service.closeRateChoice) return 1 / Number(service.closeRateChoice);
  return null;
}

/** 精靈第 3 步「賣什麼與數字」（F05-I07）：把「母產品＋賣法」寫成結構化欄位，
 * 「不知道」按下去才把基準值填進欄位並標假設（ARCHITECTURE.md §8 第 3 條）。 */
export function OfferingsStep({
  brandId,
  onRefresh,
  onNext,
}: {
  brandId: string;
  draft: IntakeDraft;
  onRefresh: () => void;
  onNext: () => void;
}) {
  const [data, setData] = useState<OfferingsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sellType, setSellType] = useState<SellType | null>(null);
  const [adDelivery, setAdDelivery] = useState<AdDelivery | null>(null);
  const [products, setProducts] = useState<ProductGroup[]>([blankProductGroup()]);
  const [service, setService] = useState<ServiceState>(blankService());
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchOfferings(brandId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        const { products: p, service: s } = deriveFromOfferings(res.offerings);
        if (p.length > 0) setProducts(p);
        if (s) setService(s);
        if (p.length > 0 && s) setSellType("both");
        else if (s) setSellType("service");
        else if (p.length > 0 && res.offerings.length > 0) setSellType("product");
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const showProduct = sellType === "product" || sellType === "both";
  const showService = sellType === "service" || sellType === "both";
  const asksCloseRate = adDelivery === "ask" || adDelivery === "lead";

  function applyAssumedCost(groupIdx: number, variantIdx: number) {
    if (!data) return;
    setProducts((prev) => {
      const next = [...prev];
      const group = { ...next[groupIdx] };
      const variants = [...group.variants];
      const price = parseFloat(variants[variantIdx].price);
      const margin = data.benchmarks.gross_margin.value;
      const assumedCost = Number.isFinite(price) ? Math.round(price * (1 - margin)) : 0;
      variants[variantIdx] = { ...variants[variantIdx], cost: String(assumedCost), costAssumed: true };
      group.variants = variants;
      next[groupIdx] = group;
      return next;
    });
  }

  function applyAssumedShipping(groupIdx: number, variantIdx: number) {
    if (!data) return;
    setProducts((prev) => {
      const next = [...prev];
      const group = { ...next[groupIdx] };
      const variants = [...group.variants];
      variants[variantIdx] = {
        ...variants[variantIdx],
        shipping: String(data.benchmarks.shipping_cost.value),
        shippingAssumed: true,
      };
      group.variants = variants;
      next[groupIdx] = group;
      return next;
    });
  }

  function applyAssumedServiceCost() {
    if (!data) return;
    const price = parseFloat(service.price);
    const margin = data.benchmarks.gross_margin.value;
    const assumedCost = Number.isFinite(price) ? Math.round(price * (1 - margin)) : 0;
    setService((prev) => ({ ...prev, cost: String(assumedCost), costAssumed: true }));
  }

  function applyAssumedCloseRate() {
    if (!data) return;
    setService((prev) => ({
      ...prev,
      closeRateChoice: "custom",
      closeRateCustom: String(Math.round(data.benchmarks.close_rate.value * 100)),
      closeRateAssumed: true,
    }));
  }

  function serviceCost(): number {
    if (service.noCost) return 0;
    const n = parseFloat(service.cost);
    return Number.isFinite(n) ? n : 0;
  }

  function serviceGrossProfit(): number {
    const price = parseFloat(service.price);
    return (Number.isFinite(price) ? price : 0) - serviceCost();
  }

  function leadValue(): number {
    const rate = closeRateValue(service);
    if (!rate) return 0;
    return Math.round(serviceGrossProfit() * rate);
  }

  function missingFieldMessage(): string | null {
    if (!sellType) return "先選一個。";
    if (!adDelivery) return "選一下廣告帶來的是什麼。";
    if (showProduct) {
      for (const group of products) {
        if (!group.name.trim()) return "商品品名還沒填。";
        for (const v of group.variants) {
          if (v.price === "") return `「${group.name || "這項商品"} · ${v.label}」的售價還沒填。`;
          if (v.cost === "") return `「${group.name || "這項商品"} · ${v.label}」的成本還沒填，填不出來就點「不知道」。`;
          if (v.shipping === "") return `「${group.name || "這項商品"} · ${v.label}」的運費還沒填，沒有運費就填 0。`;
        }
      }
    }
    if (showService) {
      if (service.price === "") return "服務的成交金額還沒填。";
      if (!service.noCost && service.cost === "") return "服務的每單成本還沒填，填不出來就點「不知道」。";
      if (asksCloseRate && closeRateValue(service) === null) return "成交率還沒選，填不出來就點「不知道」。";
    }
    return null;
  }

  const helper = missingFieldMessage();

  function buildPayload(): OfferingInput[] {
    const out: OfferingInput[] = [];
    if (showProduct) {
      for (const group of products) {
        out.push({
          parent: { product_id: group.productId, name: group.name.trim() },
          variants: group.variants.map((v) => {
            const assumptions: OfferingAssumptionField[] = [];
            if (v.costAssumed) assumptions.push("cost");
            if (v.shippingAssumed) assumptions.push("shipping");
            return {
              product_id: v.productId,
              label: v.label.trim() || "單品",
              selling_price: parseFloat(v.price),
              unit_variable_cost: parseFloat(v.cost),
              shipping_cost: parseFloat(v.shipping),
              assumptions,
            };
          }),
        });
      }
    }
    if (showService) {
      const assumptions: OfferingAssumptionField[] = [];
      if (service.costAssumed) assumptions.push("cost");
      if (asksCloseRate && service.closeRateAssumed) assumptions.push("close_rate");
      out.push({
        parent: { product_id: service.productId, name: "服務" },
        variants: [{
          product_id: service.productId,
          label: "方案",
          selling_price: parseFloat(service.price),
          unit_variable_cost: serviceCost(),
          shipping_cost: 0,
          close_rate: asksCloseRate ? closeRateValue(service) : null,
          assumptions,
        }],
      });
    }
    return out;
  }

  async function handleSubmit() {
    setSaving(true);
    setSubmitError(null);
    try {
      await saveOfferings(brandId, buildPayload());
      onRefresh();
      onNext();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "儲存失敗，請再試一次。");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-lg text-foreground">你賣的是什麼、一次成交值多少</h2>

      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium text-foreground">你賣的是什麼</p>
        <div className="flex gap-2">
          {SELL_TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.v}
              type="button"
              onClick={() => setSellType(opt.v)}
              className={`flex-1 rounded-md border px-4 py-2.5 text-sm font-medium ${
                sellType === opt.v ? "border-primary bg-primary/5 text-primary" : "border-border text-foreground hover:border-primary hover:text-primary"
              }`}
            >
              {opt.l}
            </button>
          ))}
        </div>
      </div>

      {sellType && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium text-foreground">廣告帶來的是什麼</p>
          <div className="flex gap-2">
            {AD_DELIVERY_OPTIONS.map((opt) => (
              <button
                key={opt.v}
                type="button"
                onClick={() => setAdDelivery(opt.v)}
                className={`flex-1 rounded-md border px-4 py-2.5 text-sm font-medium ${
                  adDelivery === opt.v ? "border-primary bg-primary/5 text-primary" : "border-border text-foreground hover:border-primary hover:text-primary"
                }`}
              >
                {opt.l}
              </button>
            ))}
          </div>
        </div>
      )}

      {showProduct && (
        <div className="flex flex-col gap-4">
          {products.map((group, gi) => (
            <div key={gi} className="flex flex-col gap-2 rounded-md border border-border p-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={group.name}
                  onChange={(e) => setProducts((prev) => prev.map((g, i) => (i === gi ? { ...g, name: e.target.value } : g)))}
                  placeholder="品名"
                  className="w-48 rounded-md border border-border px-2 py-1.5 text-sm"
                />
                {products.length > 1 && (
                  <button type="button" onClick={() => setProducts((prev) => prev.filter((_, i) => i !== gi))} className="text-xs text-muted-foreground hover:text-danger">
                    移除商品
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                有多組入？每種組合各一列（例：薑黃錠 3 入組）。售價填組合價、成本填整組的、運費填一次。
              </p>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-background text-xs font-medium text-muted-foreground">
                      <th className="px-3 py-2 text-left">賣法</th>
                      <th className="px-3 py-2 text-left">售價</th>
                      <th className="px-3 py-2 text-left">單位成本</th>
                      <th className="px-3 py-2 text-left">運費</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.variants.map((v, vi) => (
                      <tr key={vi} className="border-t border-border align-top">
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={v.label}
                            onChange={(e) =>
                              setProducts((prev) =>
                                prev.map((g, i) => (i === gi ? { ...g, variants: g.variants.map((row, j) => (j === vi ? { ...row, label: e.target.value } : row)) } : g)),
                              )
                            }
                            className="w-28 rounded-md border border-border px-2 py-1.5 text-sm"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            value={v.price}
                            placeholder="NT$"
                            onChange={(e) =>
                              setProducts((prev) =>
                                prev.map((g, i) => (i === gi ? { ...g, variants: g.variants.map((row, j) => (j === vi ? { ...row, price: e.target.value } : row)) } : g)),
                              )
                            }
                            className="numeric w-24 rounded-md border border-border px-2 py-1.5 text-sm"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            value={v.cost}
                            placeholder="NT$"
                            onChange={(e) =>
                              setProducts((prev) =>
                                prev.map((g, i) =>
                                  i === gi
                                    ? { ...g, variants: g.variants.map((row, j) => (j === vi ? { ...row, cost: e.target.value, costAssumed: false } : row)) }
                                    : g,
                                ),
                              )
                            }
                            className="numeric w-24 rounded-md border border-border px-2 py-1.5 text-sm"
                          />
                          {v.cost === "" && !v.costAssumed && (
                            <button type="button" onClick={() => applyAssumedCost(gi, vi)} className="mt-1 block text-xs font-medium text-primary hover:underline">
                              不知道
                            </button>
                          )}
                          {v.costAssumed && (
                            <div className="mt-1 flex flex-col gap-0.5">
                              <Badge tone="warning">假設</Badge>
                              <span className="text-[11px] text-muted-foreground">{data.benchmarks.gross_margin.source_text}</span>
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            value={v.shipping}
                            placeholder="0"
                            onChange={(e) =>
                              setProducts((prev) =>
                                prev.map((g, i) =>
                                  i === gi
                                    ? { ...g, variants: g.variants.map((row, j) => (j === vi ? { ...row, shipping: e.target.value, shippingAssumed: false } : row)) }
                                    : g,
                                ),
                              )
                            }
                            className="numeric w-20 rounded-md border border-border px-2 py-1.5 text-sm"
                          />
                          {v.shipping === "" && !v.shippingAssumed && (
                            <button type="button" onClick={() => applyAssumedShipping(gi, vi)} className="mt-1 block text-xs font-medium text-primary hover:underline">
                              不知道
                            </button>
                          )}
                          {v.shippingAssumed && (
                            <div className="mt-1 flex flex-col gap-0.5">
                              <Badge tone="warning">假設</Badge>
                              <span className="text-[11px] text-muted-foreground">{data.benchmarks.shipping_cost.source_text}</span>
                            </div>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <button
                            type="button"
                            onClick={() =>
                              setProducts((prev) => prev.map((g, i) => (i === gi ? { ...g, variants: [...g.variants, { ...g.variants[vi], costAssumed: false, shippingAssumed: false }] } : g)))
                            }
                            className="text-xs font-medium text-primary hover:underline"
                          >
                            複製這列
                          </button>
                          {group.variants.length > 1 && (
                            <button
                              type="button"
                              onClick={() => setProducts((prev) => prev.map((g, i) => (i === gi ? { ...g, variants: g.variants.filter((_, j) => j !== vi) } : g)))}
                              className="ml-2 text-xs font-medium text-muted-foreground hover:text-danger"
                            >
                              移除
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                onClick={() => setProducts((prev) => prev.map((g, i) => (i === gi ? { ...g, variants: [...g.variants, blankVariant("新賣法")] } : g)))}
                className="self-start text-sm font-medium text-primary hover:underline"
              >
                ＋新增賣法
              </button>
            </div>
          ))}
          <button type="button" onClick={() => setProducts((prev) => [...prev, blankProductGroup()])} className="self-start text-sm font-medium text-primary hover:underline">
            ＋新增商品
          </button>
        </div>
      )}

      {showService && (
        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
          <p className="text-sm font-medium text-foreground">服務／課程／KOL</p>

          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">一次成交你收到多少錢</span>
            <input
              type="number"
              value={service.price}
              onChange={(e) => setService((prev) => ({ ...prev, price: e.target.value }))}
              className="numeric w-36 rounded-md border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={service.noCost}
              onChange={(e) => setService((prev) => ({ ...prev, noCost: e.target.checked, cost: "", costAssumed: false }))}
            />
            <span className="text-foreground">幾乎沒有每單成本（課程、數位商品、諮詢）</span>
          </label>

          {!service.noCost && (
            <div className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">每單成本</span>
              <input
                type="number"
                value={service.cost}
                onChange={(e) => setService((prev) => ({ ...prev, cost: e.target.value, costAssumed: false }))}
                className="numeric w-36 rounded-md border border-border px-3 py-2 text-sm"
              />
              {service.cost === "" && !service.costAssumed && (
                <button type="button" onClick={applyAssumedServiceCost} className="self-start text-xs font-medium text-primary hover:underline">
                  不知道
                </button>
              )}
              {service.costAssumed && (
                <div className="flex flex-col gap-0.5">
                  <Badge tone="warning">假設</Badge>
                  <span className="text-[11px] text-muted-foreground">{data.benchmarks.gross_margin.source_text}</span>
                </div>
              )}
            </div>
          )}

          {asksCloseRate && (
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-foreground">大概幾個詢問成交一個</span>
              <div className="flex flex-wrap gap-2">
                {CLOSE_RATE_OPTIONS.map((opt) => (
                  <button
                    key={opt.v}
                    type="button"
                    onClick={() => setService((prev) => ({ ...prev, closeRateChoice: opt.v, closeRateAssumed: false }))}
                    className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                      service.closeRateChoice === opt.v ? "border-primary bg-primary/5 text-primary" : "border-border text-foreground hover:border-primary hover:text-primary"
                    }`}
                  >
                    {opt.l}
                  </button>
                ))}
                {!service.closeRateChoice && !service.closeRateAssumed && (
                  <button type="button" onClick={applyAssumedCloseRate} className="text-xs font-medium text-primary hover:underline">
                    不知道
                  </button>
                )}
              </div>
              {service.closeRateChoice === "custom" && (
                <input
                  type="number"
                  value={service.closeRateCustom}
                  onChange={(e) => setService((prev) => ({ ...prev, closeRateCustom: e.target.value, closeRateAssumed: false }))}
                  placeholder="成交率 %"
                  className="numeric w-28 rounded-md border border-border px-3 py-2 text-sm"
                />
              )}
              {service.closeRateAssumed && (
                <div className="flex flex-col gap-0.5">
                  <Badge tone="warning">假設</Badge>
                  <span className="text-[11px] text-muted-foreground">{data.benchmarks.close_rate.source_text}</span>
                </div>
              )}
            </div>
          )}

          {adDelivery === "direct" && (
            <p className="text-sm text-foreground">
              每單毛利：<span className="numeric font-semibold">NT$ {serviceGrossProfit().toLocaleString()}</span>
            </p>
          )}
          {asksCloseRate && (
            <p className="text-sm text-foreground">
              一筆名單值多少錢：<span className="numeric font-semibold">NT$ {leadValue().toLocaleString()}</span>
              {(service.costAssumed || service.closeRateAssumed) && <span className="text-warning">（假設）</span>}
            </p>
          )}
        </div>
      )}

      {helper && <p className="text-sm text-warning">{helper}</p>}
      {submitError && <p role="alert" className="text-sm text-danger">{submitError}</p>}

      <button
        type="button"
        disabled={!!helper || saving}
        onClick={() => void handleSubmit()}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? "儲存中…" : "下一步"}
      </button>
    </div>
  );
}
