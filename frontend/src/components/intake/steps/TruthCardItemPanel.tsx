import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import type { IntakeReviewItem, ReviewItemEdit } from "@/lib/intakeApi";
import { CATEGORY_OPTIONS, fetchReviewItem, resolveReviewItem } from "@/lib/intakeApi";
import { moveTruthCardItem, type TruthCardBucket, type TruthCardItem } from "@/lib/intakeT2Api";

const NEW_PRODUCT_SCOPE = "__new__";

/** 真相卡單條側板：欄位沿用舊 ReviewItemView，格位由 T2 專用搬格端點處理。 */
export function TruthCardItemPanel({
  brandId,
  item: summary,
  initialBucket,
  defaultTarget,
  knownProducts,
  onClose,
  onSaved,
}: {
  brandId: string;
  item: TruthCardItem;
  initialBucket: TruthCardBucket;
  defaultTarget?: TruthCardBucket;
  knownProducts: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [item, setItem] = useState<IntakeReviewItem | null>(null);
  const [form, setForm] = useState<Omit<ReviewItemEdit, "outcome"> | null>(null);
  const [newProductName, setNewProductName] = useState("");
  const [target, setTarget] = useState<TruthCardBucket | "discard">(defaultTarget ?? initialBucket);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchReviewItem(brandId, summary.i)
      .then((loaded) => {
        setItem(loaded);
        const inOptions = loaded.scope === "整個品牌" || knownProducts.includes(loaded.scope);
        setForm({
          kind: loaded.kind,
          category: loaded.category,
          title: loaded.title,
          content: loaded.content,
          scope: inOptions ? loaded.scope : NEW_PRODUCT_SCOPE,
          severity: loaded.severity,
        });
        if (!inOptions) setNewProductName(loaded.scope);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "這條內容暫時讀不到。"));
  }, [brandId, knownProducts, summary.i]);

  useEffect(() => {
    setTarget(defaultTarget ?? initialBucket);
  }, [defaultTarget, initialBucket, summary.i]);

  async function save() {
    if (!item || !form) return;
    if (target === "accepted" && summary.answer_kind) {
      setError("這條要先回卡面作答，不能直接搬到已採用。");
      return;
    }
    if (target !== "discard" && form.scope === NEW_PRODUCT_SCOPE && !newProductName.trim()) {
      setError("請填新產品的名稱。");
      return;
    }
    const scope = form.scope === NEW_PRODUCT_SCOPE ? newProductName.trim() : form.scope;
    const edit: ReviewItemEdit = { ...form, scope, outcome: target === "discard" ? "discard" : "confirm" };
    setSaving(true);
    setError(null);
    try {
      if (target === "discard") {
        if (initialBucket !== "needs_confirmation") await moveTruthCardItem(brandId, item.i, "needs_confirmation");
        await resolveReviewItem(brandId, item.i, edit);
      } else {
        await resolveReviewItem(brandId, item.i, edit);
        if (target === "needs_confirmation") await moveTruthCardItem(brandId, item.i, target);
        if (target === "forbidden" && initialBucket !== "forbidden") await moveTruthCardItem(brandId, item.i, target);
        if (target === "accepted" && initialBucket === "forbidden") await moveTruthCardItem(brandId, item.i, target);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "這條內容暫時存不進去，請再試一次。");
    } finally {
      setSaving(false);
    }
  }

  const scopes = ["整個品牌", ...knownProducts];
  return (
    <SidePanel ariaLabel="調整這條內容" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div>
          <h2 className="font-display text-lg text-foreground">調整這條內容</h2>
          {item && <p className="mt-1 text-sm text-muted-foreground">{item.kind}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {!item || !form ? <p className="text-sm text-muted-foreground">讀取中…</p> : (
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">分類</span>
            <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} className="rounded-md border border-border px-3 py-2 text-sm text-foreground">
              {CATEGORY_OPTIONS[form.kind].map((category) => <option key={category} value={category}>{displayCategory(category)}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">標題</span>
            <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">內容</span>
            <textarea value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} rows={3} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">適用範圍</span>
            <select value={form.scope} onChange={(event) => setForm({ ...form, scope: event.target.value })} className="rounded-md border border-border px-3 py-2 text-sm text-foreground">
              {scopes.map((scope) => <option key={scope} value={scope}>{scope}</option>)}
              <option value={NEW_PRODUCT_SCOPE}>建立新產品…</option>
            </select>
            {form.scope === NEW_PRODUCT_SCOPE && <input value={newProductName} onChange={(event) => setNewProductName(event.target.value)} placeholder="新產品名稱" className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />}
            {item.kind === "產品事實" && <span className="text-xs text-muted-foreground">產品事實要選一個產品，不能掛在整個品牌。</span>}
          </label>
          {form.kind === "限制規則" && (
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-1.5"><input type="radio" checked={form.severity === "soft"} onChange={() => setForm({ ...form, severity: "soft" })} />建議遵守</label>
              <label className="flex items-center gap-1.5"><input type="radio" checked={form.severity === "hard"} onChange={() => setForm({ ...form, severity: "hard" })} />必須遵守</label>
            </div>
          )}
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">放在哪裡</span>
            <select value={target} onChange={(event) => setTarget(event.target.value as TruthCardBucket | "discard")} className="rounded-md border border-border px-3 py-2 text-sm text-foreground">
              <option value="accepted">已採用</option>
              <option value="needs_confirmation">等你確認</option>
              <option value="forbidden">禁止使用</option>
              <option value="discard">捨棄這條</option>
            </select>
          </label>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div>
            <button type="button" disabled={saving} onClick={() => void save()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">
              {saving ? "存檔中…" : target === "discard" ? "捨棄這條" : "儲存調整"}
            </button>
          </div>
        </div>
      )}
    </SidePanel>
  );
}

function displayCategory(category: string) {
  return category === "受眾" ? "要傳給誰" : category;
}
