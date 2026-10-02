import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import {
  createProduct,
  dismissProductSuggestion,
  fetchProductsPage,
  type ProductSuggestion,
  type ProductsPage as PageData,
} from "@/lib/intakeProductApi";
import { ProductCard, SuggestionCard, newBundlePath, newProductPath, productOnboardingPath } from "./ProductCard";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; page: PageData };

const GRID = "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3";

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
 * state; a failed read keeps the head and its actions and puts the retry where the cards go. */
export function ProductsPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [creating, setCreating] = useState<string | null>(null);
  const [createError, setCreateError] = useState<{ name: string; message: string } | null>(null);

  function reload() {
    setLoad({ status: "loading" });
    fetchProductsPage(brandId)
      .then((page) => setLoad({ status: "ready", page }))
      .catch((err: unknown) => setLoad({ status: "error", message: err instanceof Error ? err.message : "讀取商品失敗。" }));
  }

  useEffect(reload, [brandId]);

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
              // 「不用了」 sits in the card's bottom-right corner, inside its padding (the card still fills the grid row).
              <div key={suggestion.name} data-slot="suggestion" className="relative grid">
                <SuggestionCard
                  suggestion={suggestion}
                  busy={creating !== null}
                  error={createError?.name === suggestion.name ? createError.message : null}
                  onContinue={() => continueSuggestion(suggestion)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-3.5 bottom-3.5 font-medium text-muted-foreground"
                  disabled={creating !== null}
                  onClick={() => dismissSuggestion(suggestion)}
                >
                  不用了
                </Button>
              </div>
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
    </div>
  );
}
