import { useEffect, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { fetchArchivedBrands, type ArchivedBrand } from "@/lib/api";
import { restoreBrand } from "@/lib/libraryApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ArchivedBrand[] };

const messageOf = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/** F50-I17: the brand overview's folded 「已封存的品牌（N）」 section under the cards (hidden at 0). 「還原」 sets the
 * brand back to active and calls `onRestored` (the workspace brand list refreshes — the card comes back above). */
export function ArchivedBrands({ onRestored }: { onRestored: () => void }) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [restoring, setRestoring] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<{ id: string; message: string } | null>(null);

  function read() {
    fetchArchivedBrands()
      .then((items) => setLoad({ status: "ready", items }))
      .catch((err: unknown) => setLoad({ status: "error", message: messageOf(err, "讀取失敗。") }));
  }

  useEffect(read, []);

  function restore(brand: ArchivedBrand) {
    setRestoring(brand.brand_id);
    setRestoreError(null);
    restoreBrand(brand.brand_id)
      .then(
        () => {
          read();
          onRestored();
        },
        (err: unknown) => setRestoreError({ id: brand.brand_id, message: messageOf(err, "還原失敗，請再試一次。") }),
      )
      .finally(() => setRestoring(null));
  }

  if (load.status === "loading") return null;
  if (load.status === "error") {
    return <p role="alert" className="text-xs text-danger">讀不到已封存的品牌：{load.message}</p>;
  }
  if (load.items.length === 0) return null;
  return (
    <details data-slot="archived-brands" className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-muted-foreground [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="inline-block text-base leading-none transition-transform group-open:rotate-90">›</span>
        已封存的品牌（{load.items.length}）
      </summary>
      <div className="mt-3 grid grid-cols-2 gap-5 xl:grid-cols-3">
        {load.items.map((brand) => (
          <article key={brand.brand_id} data-slot="archived-brand" className="surface flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="min-w-0 text-base text-muted-foreground [overflow-wrap:anywhere]">{brand.name}</h2>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0 font-medium"
                busy={restoring !== null}
                onClick={() => restore(brand)}
              >
                還原
              </Button>
            </div>
            {restoreError?.id === brand.brand_id && (
              <p role="alert" className="text-xs text-danger">{restoreError.message}</p>
            )}
          </article>
        ))}
      </div>
    </details>
  );
}
