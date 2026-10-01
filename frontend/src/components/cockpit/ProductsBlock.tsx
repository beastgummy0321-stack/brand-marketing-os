import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { ProductCard, newBundlePath, newProductPath } from "@/components/intake";
import { fetchProductsPage } from "@/lib/intakeProductApi";

const GRID = "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3";

/** The 「你的商品」 block on top of 經營概況 (F43-I14), prototype `.hero2` of `#/home` in
 * `.harness/scratch/prototype/f41-onboarding/index.html`: title + purpose, 「＋新增組合」 and 「＋建新商品」
 * (primary), then one compact card per knowledge product and per bundle from
 * `GET /api/intake/brands/{b}/products`. No products → the head and its actions only. A failed read
 * puts the retry inside this block; the rest of the page does not depend on it. */
export function ProductsBlock({ brandId, scope }: { brandId: string; scope: string }) {
  const products = useQuery({
    queryKey: [scope, brandId, "intake-products"],
    queryFn: () => fetchProductsPage(brandId),
  });
  const page = products.data;
  const count = page ? page.products.length + page.bundles.length : 0;
  return (
    <section
      aria-labelledby="products-block-title"
      className="rounded-[14px] border border-primary/20 bg-linear-to-br from-accent to-card px-[22px] py-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="products-block-title" className="text-[17px] font-semibold">你的商品</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">新品、新組合都從這裡建；建好就能拿去投放</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline">
            <Link to={newBundlePath(brandId)}>＋新增組合</Link>
          </Button>
          <Button asChild>
            <Link to={newProductPath(brandId)}>＋建新商品</Link>
          </Button>
        </div>
      </div>
      {products.isPending && (
        <div className={`mt-3.5 ${GRID}`}>
          <Skeleton className="h-16 rounded-xl" />
          <Skeleton className="h-16 rounded-xl" />
        </div>
      )}
      {products.isError && (
        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          <p role="alert" className="text-sm text-danger">
            商品讀取失敗：{products.error.message}
          </p>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-[13px]"
            disabled={products.isFetching}
            onClick={() => void products.refetch()}
          >
            重新載入
          </Button>
        </div>
      )}
      {page && count > 0 && (
        <div className={`mt-3.5 ${GRID}`}>
          {page.products.map((product) => (
            <ProductCard key={product.id} brandId={brandId} product={product} compact />
          ))}
          {page.bundles.map((bundle) => (
            <ProductCard key={bundle.id} brandId={brandId} bundle={bundle} compact />
          ))}
        </div>
      )}
    </section>
  );
}
