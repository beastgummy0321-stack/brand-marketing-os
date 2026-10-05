import { useEffect, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { ApiResponseError } from "@/lib/http";
import type { Bundle, BundleInput, BundlePreview, ProductCardData, SellWayNumbers } from "@/lib/intakeProductApi";
import { createBundle, fetchBundle, fetchProductsPage, previewBundle, saveBundle } from "@/lib/intakeProductApi";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar } from "../OnboardingStepHead";
import { EvidenceCard, INPUT } from "../steps/PolicyCard";
import { SellWayContents, type BaseOption } from "./SellWayContents";
import { adoptAssumedCost, draftFromMoney, emptyDraft, PriceBlock, stepMoneyInput, type MoneyDraft, type RowErrors } from "./SellWayTable";

/** 新增組合 / 編輯組合 (F45), prototype `.harness/scratch/prototype/f45-sell-way-components/variant-bundle.html`: 組合名稱,
 * 裡面有什麼 (base sell-ways of any finished product × qty, each row with that base's own 售價・成本; the picker groups
 * every finished product's bases by product, 「＋再放一種賣法」), 價格 (step 4's `PriceBlock`: an empty 售價 / 原價 / 成本
 * is derived from the bases and labelled 推算, 「這個賣法免運」, 打平 and the offer sentences), 落地頁 (required here,
 * optional server-side), and 「廣告會用到的」 (customer groups and proof reused from the bases' products).
 *
 * Nothing is computed on the page: every number (each base's 售價・成本, the derived ones with their 「推算：…」 notes,
 * 打平, the default 每筆上限, the offer sentences) is the server's view. An existing bundle saves (PUT, raw inputs only)
 * whenever focus leaves a field or the contents change, and shows the recomputed numbers; a new bundle asks
 * `POST …/bundles/preview` (nothing written) at the same moments; 「建立組合」 posts it. The page keeps no money or
 * quantity rule of its own (F50 Contract I): numbers and quantities go as typed and the server's refusals are shown as
 * it words them — a field's sentence (`field_errors`: `price`, `close_rate`, `components.{i}.qty`, …) under that field
 * once the form was touched, the rest (fewer than two products, a taken name …) under the form. The UI itself only
 * asks for a name, a quantity and a landing page before sending. */

interface Comp {
  sell_way_id: string;
  /** As typed. */
  qty: string;
}

const productsPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}/products`;
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/** What the form still lacks before it is sent (the server checks every number, quantity and the product count, and
 * says why). */
function formErrors(name: string, comps: Comp[], draft: MoneyDraft) {
  return {
    name: name.trim() ? null : "請填組合名稱",
    comps: comps.length === 0,
    /** A quantity not typed yet: nothing to send for it (a typed one goes as typed). */
    qty: comps.some((c) => c.qty.trim() === ""),
    landing: draft.landing_url.trim() ? null : "落地頁要填",
  };
}

/** What the server needs to compute the numbers (everything but the landing page the UI requires). */
function canPreview(errors: ReturnType<typeof formErrors>): boolean {
  return !errors.name && !errors.comps && !errors.qty;
}

function isValid(errors: ReturnType<typeof formErrors>): boolean {
  return canPreview(errors) && !errors.landing;
}

function toInput(name: string, comps: Comp[], draft: MoneyDraft, free: boolean, showCloseRate: boolean): BundleInput {
  return {
    name: name.trim(),
    components: comps.map((c) => ({ sell_way_id: c.sell_way_id, qty: c.qty.trim() })),
    ...stepMoneyInput(draft, showCloseRate),
    free_shipping: free,
  };
}

/** The server's per-field sentences of a refusal (`ApiResponseError.fieldErrors`), else none. */
const fieldErrorsOf = (err: unknown): RowErrors => (err instanceof ApiResponseError ? err.fieldErrors : {});

/** A base the page knows: from the products page (picker) and, once the server has seen it, its own numbers. */
interface KnownBase {
  name: string;
  product: { id: string; name: string; thumbnail_url: string | null };
  price: number | null;
  /** undefined = only the products page knows it (no cost there). */
  cost: number | null | undefined;
}

export function BundlePage({ brandId, bundleId }: { brandId: string; bundleId: string | null }) {
  const navigate = useNavigate();
  const editing = bundleId !== null;
  /** The server's view: after the last save, or (a new bundle) the last preview; null before either. */
  const [server, setServer] = useState<Bundle | BundlePreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(!editing);
  const [products, setProducts] = useState<ProductCardData[] | null>(null);
  const [productsError, setProductsError] = useState<string | null>(null);
  /** Every base seen so far, by sell-way id; a component's numbers survive a refused preview. */
  const [known, setKnown] = useState<Map<string, KnownBase>>(new Map());
  const [name, setName] = useState("");
  const [comps, setComps] = useState<Comp[]>([]);
  const [draft, setDraft] = useState<MoneyDraft>(emptyDraft);
  const [free, setFree] = useState(false);
  const [picking, setPicking] = useState(!editing);
  const [focus, setFocus] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  /** Why the last preview failed (kept apart from `saveError`: a late preview must not hide a failed create). */
  const [previewError, setPreviewError] = useState<string | null>(null);
  /** The last refusal's sentences by field (`price`, `close_rate`, `components.0.qty`, …). */
  const [fieldErrors, setFieldErrors] = useState<RowErrors>({});
  const [busy, setBusy] = useState(false);
  const state = useRef({ name, comps, draft, free });
  state.current = { name, comps, draft, free };
  /** The last body the server confirmed: an unchanged form is not sent again. */
  const savedSig = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const alive = useRef(true);

  const show = server?.show_close_rate ?? false;

  /** The server's view becomes the page's: its components' own numbers join the known bases. */
  function adopt(view: Bundle | BundlePreview) {
    setServer(view);
    setKnown((prev) => {
      const next = new Map(prev);
      for (const c of view.components) {
        next.set(c.sell_way_id, {
          name: c.name,
          product: { id: c.product_id, name: c.product_name, thumbnail_url: c.thumbnail_url },
          price: c.unit_price,
          cost: c.unit_cost,
        });
      }
      return next;
    });
  }

  function loadProducts() {
    setProductsError(null);
    fetchProductsPage(brandId)
      .then((page) => {
        if (!alive.current) return;
        const ready = page.products.filter((p) => p.state === "ready");
        setProducts(ready);
        setKnown((prev) => {
          const next = new Map(prev);
          for (const p of ready) {
            for (const w of p.sell_ways) {
              if (w.shape !== "base" || next.has(w.id)) continue;
              next.set(w.id, { name: w.name, product: { id: p.id, name: p.name, thumbnail_url: p.thumbnail_url }, price: w.price, cost: undefined });
            }
          }
          return next;
        });
      })
      .catch((err: unknown) => alive.current && setProductsError(errorText(err, "讀取商品失敗。")));
  }

  useEffect(() => {
    alive.current = true;
    loadProducts();
    if (bundleId !== null) {
      fetchBundle(brandId, bundleId)
        .then((bundle) => {
          if (!alive.current) return;
          const comps = bundle.components.map((c) => ({ sell_way_id: c.sell_way_id, qty: String(c.qty) }));
          // The UI asks for a landing page: a bundle still on its default one shows that page as its value.
          const money = { ...draftFromMoney(bundle), landing_url: bundle.landing_url };
          adopt(bundle);
          setName(bundle.name);
          setComps(comps);
          setDraft(money);
          setFree(bundle.free_shipping);
          savedSig.current = JSON.stringify(toInput(bundle.name, comps, money, bundle.free_shipping, bundle.show_close_rate));
          setLoaded(true);
        })
        .catch((err: unknown) => alive.current && setLoadError(errorText(err, "讀取組合失敗，請稍後再試。")));
    }
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, bundleId]);

  useEffect(() => {
    if (!focus) return;
    document.getElementById(focus)?.focus();
    setFocus(null);
  }, [focus]);

  /** Edit only: saves the form when it is valid and changed; resolves true once the server holds it. */
  function persist(): Promise<boolean> {
    const run = queue.current.then(async () => {
      if (bundleId === null) return false;
      const { name: n, comps: c, draft: d, free: f } = state.current;
      if (!isValid(formErrors(n, c, d))) return false;
      const body = toInput(n, c, d, f, show);
      const signature = JSON.stringify(body);
      if (signature === savedSig.current) return true;
      try {
        const res = await saveBundle(brandId, bundleId, body);
        savedSig.current = signature;
        if (alive.current) {
          adopt(res);
          setDraft((prev) => adoptAssumedCost(prev, res));
          setSaveError(null);
          setFieldErrors({});
        }
        return true;
      } catch (err) {
        if (alive.current) {
          const keyed = fieldErrorsOf(err);
          setFieldErrors(keyed);
          setSaveError(Object.keys(keyed).length > 0 ? null : errorText(err, "儲存失敗，請稍後再試。"));
        }
        return false;
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  /** New only: asks the server for the numbers of the form as it is (nothing written); a no-op while unchanged or not
   * computable. A refusal (e.g. one product only, a taken name) clears the numbers and says why. */
  function preview(): Promise<void> {
    const run = queue.current.then(async () => {
      if (bundleId !== null) return;
      const { name: n, comps: c, draft: d, free: f } = state.current;
      if (!canPreview(formErrors(n, c, d))) return;
      const body = toInput(n, c, d, f, show);
      const signature = JSON.stringify(body);
      if (signature === savedSig.current) return;
      try {
        const res = await previewBundle(brandId, body);
        savedSig.current = signature;
        if (alive.current) {
          adopt(res);
          setPreviewError(null);
          setFieldErrors({});
        }
      } catch (err) {
        savedSig.current = null;
        if (alive.current) {
          const keyed = fieldErrorsOf(err);
          setServer(null);
          setFieldErrors(keyed);
          setPreviewError(Object.keys(keyed).length > 0 ? null : errorText(err, "算不出這個組合的數字，請稍後再試。"));
        }
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  /** Let the last keystroke settle, then save (edit) or preview (new). */
  function refresh() {
    window.setTimeout(() => void (editing ? persist() : preview()), 0);
  }

  /** Focus left a field: save an existing bundle / preview a new one (a no-op while unchanged or invalid). */
  function onFieldBlur(e: FocusEvent) {
    const target = e.target as HTMLInputElement;
    if (target.tagName !== "INPUT" || target.type === "checkbox") return;
    if (editing) setTouched(true);
    refresh();
  }

  async function submit() {
    setTouched(true);
    const { name: n, comps: c, draft: d, free: f } = state.current;
    if (!isValid(formErrors(n, c, d))) return;
    setBusy(true);
    try {
      if (bundleId === null) {
        await createBundle(brandId, toInput(n, c, d, f, show));
      } else if (!(await persist())) {
        return;
      }
      navigate(productsPath(brandId));
    } catch (err) {
      if (alive.current) {
        const keyed = fieldErrorsOf(err);
        setFieldErrors(keyed);
        setSaveError(Object.keys(keyed).length > 0 ? null : errorText(err, "建立組合失敗，請再試一次。"));
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const title = editing ? "編輯組合" : "新增組合";
  const head = (
    <header data-slot="flow-header">
      <nav aria-label="位置" className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <Link to={productsPath(brandId)} className="text-muted-foreground hover:text-primary">商品</Link>
        <span aria-hidden="true">›</span>
        <b className="font-semibold text-foreground">{title}</b>
      </nav>
      <div className="mt-3 mb-1">
        <h1 className="text-[26px] leading-tight font-[650] tracking-[-0.025em]">{title}</h1>
        <p className="mt-1 text-[15px] text-muted-foreground">把已建好的商品湊成一組賣；顧客、證據、說法直接沿用各商品，不用重填</p>
      </div>
    </header>
  );
  const bar = (
    <OnboardingBar back={{ label: "商品", onClick: () => navigate(productsPath(brandId)) }}>
      <BarNext label={editing ? "儲存組合" : "建立組合"} disabled={!loaded || busy} onClick={() => void submit()} />
    </OnboardingBar>
  );

  if (loadError) {
    return (
      <Page>
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        {bar}
      </Page>
    );
  }
  if (!loaded) {
    return (
      <Page>
        {head}
        <Skeleton className="h-72 rounded-xl" />
        {bar}
      </Page>
    );
  }

  const errors = formErrors(name, comps, draft);
  /** The server's sentences of the last save / preview (sent when focus left a field), under their fields. */
  const shown: RowErrors = fieldErrors;
  const nameError = (touched ? errors.name : null) ?? shown.name;
  const landingError = (touched ? errors.landing : null) ?? shown.landing_url;
  /** The picker: every finished product's bases, then the bases already in (they may belong to a product not listed). */
  const options: BaseOption[] = [
    ...(products ?? []).flatMap((p) => p.sell_ways.filter((w) => w.shape === "base").map((w) => w.id)),
    ...comps.map((c) => c.sell_way_id),
  ]
    .filter((id, i, all) => all.indexOf(id) === i && known.has(id))
    .map((id) => ({ key: id, ...known.get(id)! }));
  const partLabel = (id: string, fallback: string) => {
    const base = known.get(id);
    return base ? `${base.product.name}・${base.name}` : fallback;
  };
  /** The server's numbers, with a missing cost named by product too (「能量軟糖・單盒」, as the 推算 notes name parts). */
  const numbers: SellWayNumbers | null = server && {
    ...server,
    cost_missing: server.cost_missing.map((m) => ({ ...m, name: partLabel(m.sell_way_id, m.name) })),
  };
  let pending: string | null = null;
  if (comps.length === 0) pending = "先放進賣法";
  else if (errors.qty) pending = "先填數量";
  else if (!server) {
    pending = errors.name ? "先填組合名稱" : previewError || Object.keys(fieldErrors).length > 0 ? "先改好下面的紅字" : "填好名稱和內容就算";
  }

  return (
    <Page>
      {head}
      <section aria-label="組合內容" className="rounded-xl border border-border bg-card px-[22px] py-5" onBlur={onFieldBlur}>
        <Row label={<label htmlFor="bundle-name">組合名稱</label>}>
          <input id="bundle-name" className={INPUT} value={name} placeholder="例如：雙效組" onChange={(e) => setName(e.target.value)} />
          {nameError && <FieldError>{nameError}</FieldError>}
        </Row>

        <Row label="裡面有什麼">
          <SellWayContents
            idPrefix="bundle"
            cross
            items={comps.map((c) => ({ base: c.sell_way_id, qty: c.qty }))}
            bases={options}
            picking={picking}
            errors={shown}
            empty={<PickerEmpty brandId={brandId} products={products} error={productsError} onRetry={loadProducts} />}
            onQty={(i, qty) => setComps((prev) => prev.map((c, j) => (j === i ? { ...c, qty } : c)))}
            onRemove={(i) => {
              setComps((prev) => prev.filter((_, j) => j !== i));
              if (comps.length === 1) setPicking(true);
              refresh();
            }}
            onAdd={(id) => {
              setComps((prev) => [...prev, { sell_way_id: id, qty: "" }]);
              setPicking(false);
              setFocus(`bundle-q${comps.length}`);
            }}
            onPicking={setPicking}
          />
        </Row>

        <Row label="價格">
          <PriceBlock
            idPrefix="bundle"
            shape="composed"
            draft={draft}
            numbers={numbers}
            free={free}
            showCloseRate={show}
            errors={shown}
            pending={pending}
            onDraft={(patch) => setDraft((prev) => ({ ...prev, ...patch }))}
            onFree={(on) => {
              setFree(on);
              if (editing) setTouched(true);
              refresh();
            }}
            fillCostWhere={(part) => {
              const product = known.get(part.sell_way_id)?.product.name;
              return product ? `到「${product}」的賣法填` : "到那個商品的賣法填";
            }}
          />
        </Row>

        <Row label={<label htmlFor="bundle-landing">落地頁</label>}>
          <input
            id="bundle-landing"
            type="url"
            className={cn(INPUT, landingError && "border-danger")}
            aria-invalid={landingError ? true : undefined}
            value={draft.landing_url}
            placeholder="https://"
            onChange={(e) => setDraft((prev) => ({ ...prev, landing_url: e.target.value }))}
          />
          {landingError && <FieldError>{landingError}</FieldError>}
        </Row>
        {previewError && <p role="alert" className="mt-2 text-sm text-danger">{previewError}</p>}
        {saveError && saveError !== previewError && <p role="alert" className="mt-2 text-sm text-danger">{saveError}</p>}
      </section>

      {server && <ReusedCard bundle={server} />}
      {bar}
    </Page>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <div className="flex max-w-[1180px] flex-col gap-4">{children}</div>;
}

/** Prototype `.bundle .q`: label column and the field. */
function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2 border-t border-border py-3.5 first:border-t-0 first:pt-0 last:pb-0 max-[760px]:grid-cols-1">
      <b className="block pt-2 text-sm font-semibold max-[760px]:pt-0">{label}</b>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function FieldError({ children }: { children: ReactNode }) {
  return <p role="alert" className="mt-1 text-[11.5px] text-danger">{children}</p>;
}

/** The picker with nothing to offer: the products are loading / failed, none is finished, or every base is in. */
function PickerEmpty({ brandId, products, error, onRetry }: {
  brandId: string;
  products: ProductCardData[] | null;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <p role="alert" className="text-sm text-danger">{error}</p>
        <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={onRetry}>重新載入</Button>
      </div>
    );
  }
  if (products === null) return <Skeleton className="h-10 rounded-lg" />;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
      <span>{products.length === 0 ? "還沒有建好的商品" : "建好的商品的基本賣法都放進來了"}</span>
      <Button asChild variant="link" className="h-auto p-0 text-[13px]">
        <Link to={`/brands/${encodeURIComponent(brandId)}/products/new`}>＋新增商品</Link>
      </Button>
    </div>
  );
}

/** 「廣告會用到的」: the bases' products' customer groups and proof, reused (not copied). */
function ReusedCard({ bundle }: { bundle: Bundle | BundlePreview }) {
  const { groups, proof } = bundle.reused;
  const productCount = new Set(bundle.components.map((c) => c.product_id)).size;
  const who = groups.map((g) => (g.pain_labels.length > 0 ? `${g.who}（${g.pain_labels.join("、")}）` : g.who));
  const counts = new Map<string, number>();
  for (const p of proof) {
    const key = p.label || p.text;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const evidence = [...counts].map(([key, n]) => (n > 1 ? `${key} ${n} 則` : key));
  return (
    <EvidenceCard title="廣告會用到的" note={`沿用 ${productCount} 個商品，不用重填`} slot="reused">
      <div className="grid grid-cols-2 gap-4 max-[760px]:grid-cols-1">
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">顧客</p>
          <div className="text-[13px]">{who.length > 0 ? who.join("・") : "—"}</div>
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">證據</p>
          <div className="text-[13px]">{evidence.length > 0 ? evidence.join("・") : "—"}</div>
        </div>
      </div>
    </EvidenceCard>
  );
}
