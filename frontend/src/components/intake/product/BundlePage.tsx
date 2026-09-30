import { useEffect, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatCount } from "@/lib/format";
import type { Bundle, BundleInput, ProductCardData } from "@/lib/intakeProductApi";
import { createBundle, fetchBundle, fetchProductsPage, saveBundle } from "@/lib/intakeProductApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar } from "../OnboardingStepHead";
import { Chip, EvidenceCard, INPUT, Item, RemoveButton } from "../steps/PolicyCard";
import { draftFromMoney, emptyDraft, moneyErrors, moneyInput, SellWayTable, type MoneyDraft } from "./SellWayTable";

/** 新增組合 / edit a bundle, prototype `#/bundle` of `.harness/scratch/prototype/f41-onboarding/index.html`: 組合名稱, 裡面有什麼
 * (finished products × qty, 「＋加一個商品」), 價格 (the shared `SellWayTable` in single-row mode + the server's offers and
 * notes), 落地頁 (required here, optional server-side), and 「廣告會用到的」 (customer groups and proof reused from the
 * component products, as `GET …/bundles/{id}` lists them).
 *
 * Nothing is computed on the page: 原價 / 成本 (the components' sums), 打平線, the default 每筆上限, the offers and each
 * component's 單件 price / cost are the server's view after the last save. A new bundle has no server view until
 * 「建立組合」 posts it (there is no preview route), so its derived cells stay empty; an existing bundle saves (PUT, raw
 * inputs only) whenever focus leaves a field and the form is valid, and the table then shows the recomputed numbers. */

interface Comp {
  product_id: string;
  name: string;
  thumbnail_url: string | null;
  /** As typed. */
  qty: string;
}

const productsPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}/products`;
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);
const qtyOf = (raw: string): number | null => (/^\d+$/.test(raw.trim()) && Number(raw) > 0 ? Number(raw) : null);
const amount = (value: number) => formatCount(Math.round(value));

/** Why the form cannot be saved (the server refuses the same, plus the landing page the UI requires). */
function formErrors(name: string, comps: Comp[], draft: MoneyDraft, showCloseRate: boolean) {
  return {
    name: name.trim() ? null : "請填組合名稱",
    comps: comps.length < 2 ? "至少放兩個不同的商品" : null,
    qty: comps.some((c) => qtyOf(c.qty) === null),
    money: Object.keys(moneyErrors(draft, showCloseRate)).length > 0,
    landing: draft.landing_url.trim() ? null : "落地頁要填",
  };
}

function isValid(errors: ReturnType<typeof formErrors>): boolean {
  return !errors.name && !errors.comps && !errors.qty && !errors.money && !errors.landing;
}

function toInput(name: string, comps: Comp[], draft: MoneyDraft, showCloseRate: boolean): BundleInput {
  return {
    name: name.trim(),
    components: comps.map((c) => ({ product_id: c.product_id, qty: qtyOf(c.qty) ?? 1 })),
    ...moneyInput(draft, showCloseRate),
  };
}

export function BundlePage({ brandId, bundleId }: { brandId: string; bundleId: string | null }) {
  const navigate = useNavigate();
  const editing = bundleId !== null;
  /** The server's view after the last save; null for a bundle not created yet. */
  const [server, setServer] = useState<Bundle | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(!editing);
  const [products, setProducts] = useState<ProductCardData[] | null>(null);
  const [productsError, setProductsError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [comps, setComps] = useState<Comp[]>([]);
  const [draft, setDraft] = useState<MoneyDraft>(emptyDraft);
  const [picking, setPicking] = useState(!editing);
  const [touched, setTouched] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const state = useRef({ name, comps, draft });
  state.current = { name, comps, draft };
  /** The last body the server confirmed: an unchanged form is not sent again. */
  const savedSig = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const alive = useRef(true);

  const show = server?.show_close_rate ?? false;

  function loadProducts() {
    setProductsError(null);
    fetchProductsPage(brandId)
      .then((page) => alive.current && setProducts(page.products.filter((p) => p.state === "ready")))
      .catch((err: unknown) => alive.current && setProductsError(errorText(err, "讀取商品失敗。")));
  }

  useEffect(() => {
    alive.current = true;
    loadProducts();
    if (bundleId !== null) {
      fetchBundle(brandId, bundleId)
        .then((bundle) => {
          if (!alive.current) return;
          const comps = bundle.components.map((c) => ({ product_id: c.product_id, name: c.name, thumbnail_url: c.thumbnail_url, qty: String(c.qty) }));
          // The UI asks for a landing page: a bundle still on its default one shows that page as its value.
          const money = { ...draftFromMoney(bundle), landing_url: bundle.landing_url };
          setServer(bundle);
          setName(bundle.name);
          setComps(comps);
          setDraft(money);
          savedSig.current = JSON.stringify(toInput(bundle.name, comps, money, bundle.show_close_rate));
          setLoaded(true);
        })
        .catch((err: unknown) => alive.current && setLoadError(errorText(err, "讀取組合失敗，請稍後再試。")));
    }
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, bundleId]);

  /** Edit only: saves the form when it is valid and changed; resolves true once the server holds it. */
  function persist(): Promise<boolean> {
    const run = queue.current.then(async () => {
      if (bundleId === null) return false;
      const { name: n, comps: c, draft: d } = state.current;
      if (!isValid(formErrors(n, c, d, show))) return false;
      const body = toInput(n, c, d, show);
      const signature = JSON.stringify(body);
      if (signature === savedSig.current) return true;
      try {
        const res = await saveBundle(brandId, bundleId, body);
        savedSig.current = signature;
        if (alive.current) {
          setServer(res);
          setSaveError(null);
        }
        return true;
      } catch (err) {
        if (alive.current) setSaveError(errorText(err, "儲存失敗，請稍後再試。"));
        return false;
      }
    });
    queue.current = run.catch(() => undefined);
    return run;
  }

  /** Focus left a field of an existing bundle: save it (a no-op while unchanged or invalid). */
  function onFieldBlur(e: FocusEvent) {
    if (!editing || (e.target as HTMLElement).tagName !== "INPUT") return;
    setTouched(true);
    // Let the last keystroke settle before reading the form.
    window.setTimeout(() => void persist(), 0);
  }

  async function submit() {
    setTouched(true);
    const { name: n, comps: c, draft: d } = state.current;
    if (!isValid(formErrors(n, c, d, show))) return;
    setBusy(true);
    try {
      if (bundleId === null) {
        await createBundle(brandId, toInput(n, c, d, show));
      } else if (!(await persist())) {
        return;
      }
      navigate(productsPath(brandId));
    } catch (err) {
      if (alive.current) setSaveError(errorText(err, "建立組合失敗，請再試一次。"));
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  function addComp(product: ProductCardData) {
    setComps((prev) => [...prev, { product_id: product.id, name: product.name, thumbnail_url: product.thumbnail_url, qty: "1" }]);
    setPicking(false);
    if (editing) window.setTimeout(() => void persist(), 0);
  }

  function removeComp(productId: string) {
    setComps((prev) => prev.filter((c) => c.product_id !== productId));
    if (editing) window.setTimeout(() => void persist(), 0);
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

  const errors = formErrors(name, comps, draft, show);
  const unit = new Map((server?.components ?? []).map((c) => [c.product_id, c]));
  const remaining = (products ?? []).filter((p) => !comps.some((c) => c.product_id === p.id));
  const label = name.trim() || "這個組合";

  return (
    <Page>
      {head}
      <section aria-label="組合內容" className="rounded-xl border border-border bg-card px-[22px] py-5" onBlur={onFieldBlur}>
        <Row label={<label htmlFor="bundle-name">組合名稱</label>}>
          <input id="bundle-name" className={INPUT} value={name} placeholder="例如：雙效組" onChange={(e) => setName(e.target.value)} />
          {touched && errors.name && <FieldError>{errors.name}</FieldError>}
        </Row>

        <Row label="裡面有什麼">
          <ul aria-label="組合裡的商品" className="flex flex-col">
            {comps.map((c) => {
              const u = unit.get(c.product_id);
              const bad = touched && qtyOf(c.qty) === null;
              return (
                <li key={c.product_id}>
                  <Item className="first:mt-0">
                    <Thumb url={c.thumbnail_url} size={32} />
                    <div className="min-w-0 flex-1">
                      <b className="block font-semibold [overflow-wrap:anywhere]">{c.name}</b>
                      {u && <div className="text-xs text-muted-foreground">{unitLine(u.unit_price, u.unit_cost)}</div>}
                    </div>
                    <span className={cn("inline-flex w-[100px] items-center rounded-lg border bg-card px-3 focus-within:border-primary focus-within:ring-[3px] focus-within:ring-accent", bad ? "border-danger" : "border-input")}>
                      <span aria-hidden="true" className="text-muted-foreground">×</span>
                      <input
                        aria-label={`${c.name}的數量`}
                        aria-invalid={bad ? true : undefined}
                        inputMode="numeric"
                        className="w-full bg-transparent px-2 py-[9px] text-base font-semibold tabular-nums outline-none"
                        value={c.qty}
                        onChange={(e) => setComps((prev) => prev.map((p) => (p.product_id === c.product_id ? { ...p, qty: e.target.value } : p)))}
                      />
                    </span>
                    <RemoveButton label={c.name} onClick={() => removeComp(c.product_id)} />
                  </Item>
                  {bad && <FieldError>數量要是正整數</FieldError>}
                </li>
              );
            })}
          </ul>
          {touched && errors.comps && <FieldError>{errors.comps}</FieldError>}
          {picking ? (
            <Picker
              brandId={brandId}
              products={products}
              remaining={remaining}
              error={productsError}
              onRetry={loadProducts}
              onPick={addComp}
              onClose={comps.length > 0 ? () => setPicking(false) : undefined}
            />
          ) : (
            <Button type="button" variant="link" className="mt-2 h-auto p-0 text-[13px]" onClick={() => setPicking(true)}>
              ＋加一個商品
            </Button>
          )}
        </Row>

        <Row label="價格">
          <SellWayTable
            rows={[{ key: "bundle", draft, money: server, name: label, showErrors: touched }]}
            showCloseRate={show}
            nameColumns={false}
            footer={false}
            onDraft={(_key, patch) => setDraft((prev) => ({ ...prev, ...patch }))}
          />
          {server && (server.offer_labels.length > 0 || server.offer_notes.length > 0) && (
            <div data-slot="offers" className="mt-2 flex flex-wrap items-center gap-1.5">
              {server.offer_labels.map((o) => <Chip key={o} tone="ok">{o}</Chip>)}
              {server.offer_notes.map((n) => <span key={n} className="text-xs text-muted-foreground">{n}</span>)}
            </div>
          )}
        </Row>

        <Row label={<label htmlFor="bundle-landing">落地頁</label>}>
          <input
            id="bundle-landing"
            type="url"
            className={cn(INPUT, touched && errors.landing && "border-danger")}
            aria-invalid={touched && errors.landing ? true : undefined}
            value={draft.landing_url}
            placeholder="https://"
            onChange={(e) => setDraft((prev) => ({ ...prev, landing_url: e.target.value }))}
          />
          {touched && errors.landing && <FieldError>{errors.landing}</FieldError>}
        </Row>
        {saveError && <p role="alert" className="mt-2 text-sm text-danger">{saveError}</p>}
      </section>

      {server && <ReusedCard bundle={server} />}
      {bar}
    </Page>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <div className="flex max-w-[1180px] flex-col gap-4">{children}</div>;
}

/** Prototype `.q`: label column and the field. */
function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 border-t border-border py-3.5 first:border-t-0 first:pt-0 last:pb-0 max-[760px]:grid-cols-1">
      <b className="block text-sm font-semibold">{label}</b>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function FieldError({ children }: { children: ReactNode }) {
  return <p role="alert" className="mt-1 text-[11.5px] text-danger">{children}</p>;
}

/** 「單件 399・成本 90」 from the component product's one-unit sell-way (as the server reads it). */
function unitLine(price: number | null, cost: number | null): string {
  return `單件 ${price === null ? "未定價" : amount(price)}・成本 ${cost === null ? "未知" : amount(cost)}`;
}

/** Prototype `.th`: a product photo, or an empty tile. */
function Thumb({ url, size }: { url: string | null; size: number }) {
  const { src } = useAuthedImage(url ?? undefined);
  const box = { width: size, height: size };
  return src
    ? <img src={src} alt="" style={box} className="shrink-0 rounded-lg object-cover" />
    : <span aria-hidden="true" style={box} className="inline-block shrink-0 rounded-lg bg-muted" />;
}

/** 「＋加一個商品」: the brand's finished products not in the bundle yet. */
function Picker({ brandId, products, remaining, error, onRetry, onPick, onClose }: {
  brandId: string;
  products: ProductCardData[] | null;
  remaining: ProductCardData[];
  error: string | null;
  onRetry: () => void;
  onPick: (product: ProductCardData) => void;
  onClose?: () => void;
}) {
  let body: ReactNode;
  if (error) {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <p role="alert" className="text-sm text-danger">{error}</p>
        <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={onRetry}>重新載入</Button>
      </div>
    );
  } else if (products === null) {
    body = <Skeleton className="h-10 rounded-lg" />;
  } else if (remaining.length === 0) {
    body = (
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <span>{products.length === 0 ? "還沒有建好的商品" : "建好的商品都放進來了"}</span>
        <Button asChild variant="link" className="h-auto p-0 text-[13px]">
          <Link to={`/brands/${encodeURIComponent(brandId)}/products/new`}>＋新增商品</Link>
        </Button>
      </div>
    );
  } else {
    body = (
      <ul className="flex flex-wrap gap-2">
        {remaining.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              aria-label={`放進「${p.name}」`}
              className="flex max-w-[320px] items-center gap-2 rounded-[10px] border border-dashed border-input bg-card px-3 py-2 text-left text-[13px] hover:border-primary"
              onClick={() => onPick(p)}
            >
              <Thumb url={p.thumbnail_url} size={24} />
              <span className="[overflow-wrap:anywhere]">{p.name}</span>
            </button>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div data-slot="product-picker" className="mt-2 rounded-[10px] bg-muted/50 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-muted-foreground">選一個建好的商品</span>
        {onClose && <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={onClose}>收起</Button>}
      </div>
      {body}
    </div>
  );
}

/** 「廣告會用到的」: the components' customer groups and proof, reused (not copied). */
function ReusedCard({ bundle }: { bundle: Bundle }) {
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
