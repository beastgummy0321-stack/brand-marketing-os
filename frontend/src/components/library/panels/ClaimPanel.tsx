import { useState } from "react";
import { TriangleAlert, X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  createClaim,
  updateClaim,
  type ClaimType,
  type ClaimWordlistHit,
  type LibraryClaim,
  type LibraryProductOption,
} from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／編輯宣稱側板（契約 S5.22）。`claim` 傳 null＝新增。 */
export function ClaimPanel({
  brandId,
  claim,
  products,
  onClose,
  onSaved,
}: {
  brandId: string;
  claim: LibraryClaim | null;
  products: LibraryProductOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = claim !== null;
  const [claimText, setClaimText] = useState(claim?.claim_text ?? "");
  const [claimType, setClaimType] = useState<ClaimType>(claim?.claim_type ?? "high_risk");
  const [productId, setProductId] = useState(claim?.product_id ?? "");
  const [evidence, setEvidence] = useState(claim?.evidence_source_reference ?? "");
  // 票 03-claim-wordlist-todo（決議 2026-08-23）：存檔不擋，但命中內建法定詞庫要讓使用者
  // 看到才關閉——存了就有這個結果，關掉面板重新整理列表也看得到同一個紅字徽章
  // （ClaimsTab.tsx），這裡只是讓使用者當下就看到，不用多繞一次。
  const [savedHits, setSavedHits] = useState<ClaimWordlistHit[] | null>(null);

  const form = useFormSubmit(async () => {
    const fields = {
      claim_text: claimText,
      claim_type: claimType,
      product_id: productId,
      evidence_source_reference: evidence,
    };
    const saved = editing ? await updateClaim(brandId, claim.id, fields) : await createClaim(brandId, fields);
    if (saved.wordlist_hits.length > 0) setSavedHits(saved.wordlist_hits);
    else onSaved();
  });

  return (
    <SidePanel ariaLabel={editing ? "編輯宣稱" : "新增宣稱"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "編輯宣稱" : "新增宣稱"}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">宣稱內容</span>
          <textarea
            value={claimText}
            onChange={(e) => setClaimText(e.target.value)}
            required
            rows={3}
            placeholder="例如「每份含 500 毫克台灣產薑黃萃取物」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="font-medium text-foreground">這句話屬於哪一類？</legend>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="claim_type"
              checked={claimType === "approved"}
              onChange={() => setClaimType("approved")}
            />
            可用
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="claim_type"
              checked={claimType === "high_risk"}
              onChange={() => setClaimType("high_risk")}
            />
            高風險
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="claim_type"
              checked={claimType === "forbidden"}
              onChange={() => setClaimType("forbidden")}
            />
            禁用
          </label>
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">佐證來源（選填）</span>
          <input
            type="text"
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="例如「2025-03 第三方成分檢驗報告」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">適用範圍</span>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">整個品牌</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        {savedHits && (
          <p className="flex items-start gap-1.5 text-sm font-medium text-danger">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            已存檔，但含法規禁用詞{savedHits.map((hit) => `「${hit.term}」`).join("、")}，正式使用前請再確認。
          </p>
        )}
        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          {savedHits ? (
            <button
              type="button"
              onClick={onSaved}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              知道了，關閉
            </button>
          ) : (
            <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "新增這句宣稱"} />
          )}
        </div>
      </form>
    </SidePanel>
  );
}
