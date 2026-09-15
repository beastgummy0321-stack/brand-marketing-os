import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { EmptyState } from "@/components/layout/EmptyState";
import { cn } from "@/lib/utils";
import type { ProductPart, SetDetail, SetProduct } from "@/lib/workbenchApi";
import { VersionBadge } from "./SetStudioPage";

/** 圖片 tab（F02-I13／F07-I12 拆出，`ARCHITECTURE.md` §5.7、§5.9、§5.11-§5.13）：卡片渲染
 * `version.badges`（主力／探索、建議選這張）與 `fingerprint_text`，都是後端原樣給的字串，這支
 * 不重打規則。從 `SetStudioPage.tsx` 移出只是為了那支檔案的 800 行上限，行為沒變。 */
export function ImagePart({
  set,
  product,
  onSelect,
  onSwitchPart,
  imageGeneration,
  locked,
  onSimilar,
  onEdit,
}: {
  set: SetDetail;
  product: SetProduct;
  onSelect: (versionId: string, selected: boolean) => void;
  onSwitchPart: (part: ProductPart) => void;
  imageGeneration: SetDetail["image_generation"];
  locked: boolean;
  onSimilar: () => void;
  onEdit?: () => void;
}) {
  const [showPrompt, setShowPrompt] = useState(!imageGeneration.connected);
  const [promptOpen, setPromptOpen] = useState(false);

  const latest = product.versions[0];
  const selectedOrLatest = product.versions.find((v) => v.selected_at) ?? latest;
  const promptCards = selectedOrLatest?.prompt_cards ?? [];

  const copyProduct = set.products.copy;
  const selectedCopy = copyProduct?.versions.find((v) => v.selected_at);
  const selectedCopyIndex = selectedCopy
    ? (copyProduct?.versions ?? [])
        .filter((v) => v.generation_round === selectedCopy.generation_round)
        .indexOf(selectedCopy) + 1
    : null;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <Button size="sm" variant="outline" onClick={() => setShowPrompt((v) => !v)}>
            顯示提示詞
          </Button>
        </div>

        {product.versions.length === 0 && (
          <EmptyState title="還沒有生成過" description="按上方「再生成」開始第一輪。" />
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {product.versions.map((version, i) => {
            const selected = Boolean(version.selected_at);
            return (
              <div
                key={version.id}
                className={cn(
                  "surface flex flex-col gap-2 p-3",
                  selected && "ring-2 ring-primary",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="flex size-6 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
                      {i + 1}
                    </span>
                    {(version.badges ?? []).map((badge) => (
                      <Badge
                        key={badge}
                        className={
                          badge === "建議選這張" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
                        }
                      >
                        {badge}
                      </Badge>
                    ))}
                  </div>
                  {selected && <Badge className="bg-primary/10 text-primary">已選定</Badge>}
                </div>
                {version.fingerprint_text && (
                  <p className="text-xs text-muted-foreground">{version.fingerprint_text}</p>
                )}
                {showPrompt || !imageGeneration.connected ? (
                  <div className="flex flex-col gap-2">
                    {(version.prompt_cards ?? []).map((card) => (
                      <div key={card.label} className="rounded-md border border-border p-2 text-xs">
                        <div className="mb-1 flex items-center justify-between gap-2">
                          <span className="font-medium text-foreground">{card.label}</span>
                          <CopyIconButton getText={() => card.text} ariaLabel={`複製${card.label}`} />
                        </div>
                        <p className="whitespace-pre-wrap text-muted-foreground">{card.text}</p>
                      </div>
                    ))}
                    {(version.prompt_cards ?? []).length === 0 && (
                      <p className="text-xs text-muted-foreground">{imageGeneration.reason}</p>
                    )}
                  </div>
                ) : (
                  <div className="flex h-40 items-center justify-center rounded-md bg-muted text-xs text-muted-foreground">
                    {imageGeneration.reason}
                  </div>
                )}
                <VersionBadge
                  version={version}
                  onSelect={() => onSelect(version.id, selected)}
                  onSimilar={onSimilar}
                  onEdit={onEdit}
                  disabled={locked}
                />
              </div>
            );
          })}
        </div>

        {Boolean(product.copy_all_text) && (
          <CopyIconButton
            getText={() => product.copy_all_text ?? ""}
            label="複製全部"
            ariaLabel="複製全部提示詞"
            className="w-fit"
          />
        )}
      </div>

      <div className="flex flex-col gap-4">
        <div className="surface">
          <div className="surface-header">
            <h2>生成設定</h2>
          </div>
          <div className="surface-body flex flex-col gap-2">
            {set.generation_settings.map((row) => (
              <div key={row.label} className="flex items-start justify-between gap-3 text-sm">
                <span className="shrink-0 text-muted-foreground">{row.label}</span>
                <span className="text-right text-foreground">{row.text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="surface">
          <button
            type="button"
            onClick={() => setPromptOpen((v) => !v)}
            className="surface-header flex w-full items-center justify-between text-left"
          >
            <h2>查看 Prompt</h2>
            <ChevronDown className={cn("size-4 transition-transform", promptOpen && "rotate-180")} />
          </button>
          {promptOpen && (
            <div className="surface-body flex flex-col gap-2">
              {promptCards.length === 0 && (
                <p className="text-sm text-muted-foreground">還沒有提示詞。</p>
              )}
              {promptCards.map((card) => (
                <div key={card.label} className="text-sm">
                  <p className="font-medium text-foreground">{card.label}</p>
                  <p className="whitespace-pre-wrap text-muted-foreground">{card.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {copyProduct && selectedCopy && (
          <div className="surface">
            <div className="surface-header">
              <h2>已選文案（第 {selectedCopyIndex} 版）</h2>
              <button
                type="button"
                onClick={() => onSwitchPart("copy")}
                className="text-xs text-primary hover:underline"
              >
                更換版本 ↗
              </button>
            </div>
            <div className="surface-body flex flex-col gap-1 text-sm">
              <p className="text-foreground">{String(selectedCopy.body?.headline ?? "")}</p>
              <p className="text-muted-foreground">{String(selectedCopy.body?.description ?? "")}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
