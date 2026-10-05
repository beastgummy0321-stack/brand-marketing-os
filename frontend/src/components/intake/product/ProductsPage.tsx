import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import {
  createProduct,
  dismissProductSuggestion,
  fetchArchivedProducts,
  fetchProductsPage,
  restoreProduct,
  type ArchivedProduct,
  type ProductSuggestion,
  type ProductsPage as PageData,
} from "@/lib/intakeProductApi";
import {
  ArchivedProductCard,
  ProductCard,
  SuggestionCard,
  newBundlePath,
  newProductPath,
  productOnboardingPath,
} from "./ProductCard";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; page: PageData };

type ArchivedState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ArchivedProduct[] };

const GRID = "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3";

const messageOf = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/** Both lists (the page and the 「已封存」 fold), no skeleton: `reload` sets that first, a restore does not. */
function readLists(brandId: string, setLoad: (s: LoadState) => void, setArchived: (s: ArchivedState) => void) {
  fetchProductsPage(brandId)
    .then((page) => setLoad({ status: "ready", page }))
    .catch((err: unknown) => setLoad({ status: "error", message: messageOf(err, "讀取商品失敗。") }));
  fetchArchivedProducts(brandId)
    .then((items) => setArchived({ status: "ready", items }))
    .catch((err: unknown) => setArchived({ status: "error", message: messageOf(err, "讀取失敗。") }));
}

/** F50-I17: the folded 「已封存（N）」 group under the list (hidden at 0); 「還原」 is the page's call. */
function ArchivedGroup({ archived, restoring, restoreError, onRestore }: {
  archived: ArchivedState;
  restoring: string | null;
  restoreError: { id: string; message: string } | null;
  onRestore: (product: ArchivedProduct) => void;
}) {
  if (archived.status === "loading") return null;
  if (archived.status === "error") {
    return <p role="alert" className="text-xs text-danger">讀不到已封存的商品：{archived.message}</p>;
  }
  if (archived.items.length === 0) return null;
  return (
    <details data-slot="archived-products" className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-semibold text-muted-foreground [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block text-base leading-none transition-transform group-open:rotate-90">›</span>
        已封存（{archived.items.length}）
      </summary>
      <div className={`mt-2 ${GRID}`}>
        {archived.items.map((product) => (
          <ArchivedProductCard
            key={product.id}
            name={product.name}
            busy={restoring !== null}
            error={restoreError?.id === product.id ? restoreError.message : null}
            onRestore={() => onRestore(product)}
          />
        ))}
      </div>
    </details>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title}>
      <h2 className="mb-2 text-xs font-semibold text-muted-foreground">{title}</h2>
      <div className={GRID}>{children}</div>
    </section>
  );
}

function NewProductButton({ brandId }: { brandId: string }) {
  return (
    <Button asChild size="lg" className="px-[22px] font-semibold">
      <Link to={newProductPath(brandId)}>＋新增商品</Link>
    </Button>
  );
}

/** The products page `/brands/:b/products`, prototype `#/plist` of `.harness/scratch/prototype/f41-onboarding/index.html`:
 * title + purpose, 「＋新增組合」 and 「＋新增商品」; section 商品 (knowledge products, then the brand scan's products not
 * created yet — 「繼續建檔 →」 creates one and opens its step 1); section 組合. A brand with nothing yet gets one empty
 * state; a failed read keeps the head and its actions and puts the retry where the cards go. F50-I17: under the list,
 * the folded 「已封存（N）」 group (hidden at 0) restores a product with 「還原」. */
export function ProductsPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [creating, setCreating] = useState<string | null>(null);
  const [createError, setCreateError] = useState<{ name: string; message: string } | null>(null);
  const [archived, setArchived] = useState<ArchivedState>({ status: "loading" });
  const [restoring, setRestoring] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<{ id: string; message: string } | null>(null);

  const readBoth = () => readLists(brandId, setLoad, setArchived);

  function reload() {
    setLoad({ status: "loading" });
    setArchived({ status: "loading" });
    readLists(brandId, setLoad, setArchived);
  }

  useEffect(reload, [brandId]);

  /** F50-I17: 「還原」 — the archive toggle; on success both lists are read again (the product is back in 商品). */
  function restore(product: ArchivedProduct) {
    setRestoring(product.id);
    setRestoreError(null);
    restoreProduct(brandId, product.id)
      .then(
        readBoth,
        (err: unknown) => setRestoreError({ id: product.id, message: messageOf(err, "還原失敗，請再試一次。") }),
      )
      .finally(() => setRestoring(null));
  }

  function continueSuggestion(suggestion: ProductSuggestion) {
    setCreating(suggestion.name);
    setCreateError(null);
    createProduct(brandId, suggestion.url ? { name: suggestion.name, page_url: suggestion.url } : { name: suggestion.name })
      .then(({ product_id, created }) => navigate(productOnboardingPath(brandId, product_id, created ? 1 : null)))
      .catch((err: unknown) => {
        setCreating(null);
        setCreateError({ name: suggestion.name, message: err instanceof Error ? err.message : "建立商品失敗，請再試一次。" });
      });
  }

  /** F47 Q8: 「不用了」 — the name is kept as dismissed on the server and the page comes back without it. */
  function dismissSuggestion(suggestion: ProductSuggestion) {
    setCreating(suggestion.name);
    setCreateError(null);
    dismissProductSuggestion(brandId, suggestion.name)
      .then((page) => setLoad({ status: "ready", page }))
      .catch((err: unknown) =>
        setCreateError({ name: suggestion.name, message: err instanceof Error ? err.message : "沒有略過，請再試一次。" }),
      )
      .finally(() => setCreating(null));
  }

  const empty = load.status === "ready"
    && load.page.products.length + load.page.suggestions.length + load.page.bundles.length === 0;

  let body: ReactNode;
  if (load.status === "loading") {
    body = (
      <div className={GRID}>
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-32 rounded-xl" />
      </div>
    );
  } else if (load.status === "error") {
    body = (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-danger">{load.message}</p>
        <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={reload}>重新載入</Button>
      </div>
    );
  } else if (empty) {
    body = (
      <div data-slot="empty-state" className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-input bg-card px-6 py-10">
        <h2 className="text-[15px] font-semibold">還沒有商品</h2>
        <NewProductButton brandId={brandId} />
      </div>
    );
  } else {
    const { products, suggestions, bundles } = load.page;
    body = (
      <>
        {products.length + suggestions.length > 0 && (
          <Section title="商品">
            {products.map((product) => <ProductCard key={product.id} brandId={brandId} product={product} />)}
            {suggestions.map((suggestion) => (
              <SuggestionCard
                key={suggestion.name}
                suggestion={suggestion}
                busy={creating !== null}
                error={createError?.name === suggestion.name ? createError.message : null}
                onContinue={() => continueSuggestion(suggestion)}
                onDismiss={() => dismissSuggestion(suggestion)}
              />
            ))}
          </Section>
        )}
        {bundles.length > 0 && (
          <Section title="組合">
            {bundles.map((bundle) => <ProductCard key={bundle.id} brandId={brandId} bundle={bundle} />)}
          </Section>
        )}
      </>
    );
  }

  return (
    <div className="flex max-w-[1180px] flex-col gap-4">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] leading-tight font-[650] tracking-[-0.025em]">商品</h1>
          <p className="mt-1 text-[15px] text-muted-foreground">每個商品建一次；跨商品一起賣的放「組合」</p>
        </div>
        {!empty && (
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="lg" className="font-semibold">
              <Link to={newBundlePath(brandId)}>＋新增組合</Link>
            </Button>
            <NewProductButton brandId={brandId} />
          </div>
        )}
      </div>
      {body}
      {load.status === "ready" && (
        <ArchivedGroup archived={archived} restoring={restoring} restoreError={restoreError} onRestore={restore} />
      )}
    </div>
  );
}
