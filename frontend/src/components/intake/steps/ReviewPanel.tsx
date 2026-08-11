import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pager } from "@/components/layout/Pager";
import type { IntakeReviewItem, ReviewItemEdit } from "@/lib/intakeApi";
import { CATEGORY_OPTIONS, fetchReviewItem, fetchReviewList, resolveReviewItem, reviewPendingAll } from "@/lib/intakeApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";

/** AI 帶回的內容清單／逐條處理（契約 S4.58–S4.66），緊接貼回成功之後。全部處理完
 * （S4.65「導回品牌頁並顯示完成訊息」）直接導去真後端已經在服務的 `/brands/:id`
 * 駕駛艙頁，不在精靈殼裡另外做一個完成畫面。 */
export function ReviewPanel({
  brandId,
  knownProducts,
  onRefresh,
}: {
  brandId: string;
  knownProducts: string[];
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [openI, setOpenI] = useState<number | null>(null);

  function handleAllDone() {
    onRefresh();
    navigate(`/brands/${brandId}?intake_done=1`);
  }

  if (openI !== null) {
    return (
      <ReviewItemView
        brandId={brandId}
        i={openI}
        knownProducts={knownProducts}
        onBack={() => setOpenI(null)}
        onResolved={(nextI) => (nextI === null ? handleAllDone() : setOpenI(nextI))}
      />
    );
  }
  return <ReviewList brandId={brandId} onOpen={setOpenI} onAllDone={handleAllDone} />;
}

function ReviewList({ brandId, onOpen, onAllDone }: { brandId: string; onOpen: (i: number) => void; onAllDone: () => void }) {
  const [items, setItems] = useState<IntakeReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(items ?? []);

  function load() {
    fetchReviewList(brandId)
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }
  useEffect(load, [brandId]);

  async function handlePendingAll() {
    if (!window.confirm(`把剩餘 ${totalCount} 筆全部先存成待確認？之後可在品牌檔案頁慢慢逐筆確認。`)) return;
    setConfirmingAll(true);
    try {
      await reviewPendingAll(brandId);
      onAllDone();
    } finally {
      setConfirmingAll(false);
    }
  }

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!items) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;

  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border bg-card p-6 text-sm">
        <p className="font-medium text-foreground">還沒有貼回任何內容</p>
      </div>
    );
  }

  return (
    <div ref={topRef} className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">AI 帶回的內容（{totalCount} 筆，全部待確認）</h2>
      </div>

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">種類</th>
              <th className="px-3 py-2 font-medium">分類</th>
              <th className="px-3 py-2 font-medium">標題</th>
              <th className="px-3 py-2 font-medium">適用範圍</th>
              <th className="px-3 py-2 font-medium">狀態</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((item) => (
              <tr key={item.id} className="border-t border-border">
                <td className="px-3 py-2">
                  <button type="button" onClick={() => onOpen(item.i)} className="font-medium text-primary hover:underline">
                    {item.kind}
                  </button>
                </td>
                <td className="px-3 py-2 text-foreground">{item.category}</td>
                <td className="px-3 py-2 text-foreground">
                  {item.title}
                  {item.dup_hint && <span className="ml-1 text-warning">⚠ {item.dup_hint}</span>}
                </td>
                <td className="px-3 py-2 text-muted-foreground">{item.scope}</td>
                <td className="px-3 py-2">
                  <Badge tone="warning">待確認</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onOpen(items[0].i)}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          開始逐條確認
        </button>
        <button
          type="button"
          disabled={confirmingAll}
          onClick={() => void handlePendingAll()}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {confirmingAll ? "處理中…" : "剩餘全部先存成待確認"}
        </button>
      </div>
    </div>
  );
}

/** 適用範圍下拉的「建立新產品…」選項值（契約 S4.64；對照 `app/intake/routes.py:835` 的
 * `__new__` sentinel，同一個慣例，避免跟真的產品名稱撞名）。 */
const NEW_PRODUCT_SCOPE = "__new__";

function ReviewItemView({
  brandId,
  i,
  knownProducts,
  onBack,
  onResolved,
}: {
  brandId: string;
  i: number;
  knownProducts: string[];
  onBack: () => void;
  onResolved: (nextI: number | null) => void;
}) {
  const [item, setItem] = useState<IntakeReviewItem | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<{ kind: IntakeReviewItem["kind"]; category: string; title: string; content: string; scope: string; severity: "soft" | "hard" | null } | null>(null);
  const [newProductName, setNewProductName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const scopeOptions = ["整個品牌", ...knownProducts];

  useEffect(() => {
    setItem(null);
    setLoadError(null);
    setNewProductName("");
    fetchReviewItem(brandId, i)
      .then((it) => {
        setItem(it);
        // 貼回驗證（S4.51）已經把不認得的適用範圍解決掉，正常情況 it.scope 一定在
        // scopeOptions 裡；萬一不在（例如清單還沒同步），照舊頁邏輯歸類成「建立新產品…」
        // 並把原字串帶進補充欄，不憑空丟掉使用者資料。
        const inOptions = it.scope === "整個品牌" || knownProducts.includes(it.scope);
        setForm({ kind: it.kind, category: it.category, title: it.title, content: it.content, scope: inOptions ? it.scope : NEW_PRODUCT_SCOPE, severity: it.severity });
        if (!inOptions) setNewProductName(it.scope);
      })
      .catch((err: unknown) => setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, i]);

  async function resolve(outcome: ReviewItemEdit["outcome"]) {
    if (!form) return;
    if (outcome !== "discard" && form.scope === NEW_PRODUCT_SCOPE && !newProductName.trim()) {
      setError("請填新產品的名稱。");
      return;
    }
    const scope = form.scope === NEW_PRODUCT_SCOPE ? newProductName.trim() : form.scope;
    setSaving(outcome);
    setError(null);
    try {
      await resolveReviewItem(brandId, i, { outcome, ...form, scope });
      const remaining = await fetchReviewList(brandId);
      onResolved(remaining.length === 0 ? null : remaining[0].i);
    } catch (err) {
      setError(err instanceof Error ? err.message : "處理失敗，請稍後再試。");
    } finally {
      setSaving(null);
    }
  }

  if (loadError) return <p className="text-sm text-danger">{loadError}</p>;
  if (!item || !form) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">第 {item.i} 筆</h2>
        <button type="button" onClick={onBack} className="text-sm text-muted-foreground hover:underline">
          回清單
        </button>
      </div>

      <p className="text-sm text-muted-foreground">
        種類：<span className="text-foreground">{item.kind}</span>
      </p>
      <p className="text-sm text-muted-foreground">AI 依據：{item.evidence}</p>
      {item.dup_hint && <p className="text-sm text-warning">⚠ {item.dup_hint}</p>}

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">分類</span>
        <select
          value={form.category}
          onChange={(e) => setForm({ ...form, category: e.target.value })}
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        >
          {CATEGORY_OPTIONS[form.kind].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">標題</span>
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">內容</span>
        <textarea
          value={form.content}
          onChange={(e) => setForm({ ...form, content: e.target.value })}
          rows={3}
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">適用範圍</span>
        <select
          value={form.scope}
          onChange={(e) => setForm({ ...form, scope: e.target.value })}
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        >
          {scopeOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
          <option value={NEW_PRODUCT_SCOPE}>建立新產品…</option>
        </select>
        {form.scope === NEW_PRODUCT_SCOPE && (
          <input
            type="text"
            value={newProductName}
            onChange={(e) => setNewProductName(e.target.value)}
            placeholder="選「建立新產品…」時填產品名稱"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        )}
        {item.kind === "產品事實" && <p className="text-xs text-muted-foreground">產品事實需要掛在一個產品下，不能是「整個品牌」。</p>}
      </label>

      {form.kind === "限制規則" && (
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={form.severity === "soft"} onChange={() => setForm({ ...form, severity: "soft" })} />
            建議遵守
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={form.severity === "hard"} onChange={() => setForm({ ...form, severity: "hard" })} />
            必須遵守
          </label>
        </div>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={saving !== null}
          onClick={() => void resolve("confirm")}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving === "confirm" ? "處理中…" : "確認，變成這個品牌的資料"}
        </button>
        <button
          type="button"
          disabled={saving !== null}
          onClick={() => void resolve("pending")}
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving === "pending" ? "處理中…" : "先存成待確認"}
        </button>
        <button
          type="button"
          disabled={saving !== null}
          onClick={() => void resolve("discard")}
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-danger hover:border-danger disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving === "discard" ? "處理中…" : "這筆不要，捨棄"}
        </button>
      </div>
    </div>
  );
}
