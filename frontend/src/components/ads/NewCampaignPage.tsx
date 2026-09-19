import { UserAssetsLibrary } from "./UserAssetsLibrary";
import { attachUpload, type AssetUpload } from "@/lib/adsUserAssetsApi";
import type { CampaignDraft } from "@/lib/adsApi";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Plus, Sparkles, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { createCampaign, getCampaign } from "@/lib/adsApi";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { readDraft, saveDraft, clearDraft } from "./campaignDraft";

const CONSTRAINT_FIELDS: { key: string; label: string; placeholder: string; isDate?: boolean }[] = [
  { key: "budget", label: "預算上限", placeholder: "例如 NT$ 30,000" },
  { key: "platform", label: "指定平台", placeholder: "例如 Facebook" },
  { key: "product", label: "指定商品", placeholder: "選擇商品" },
  { key: "dates", label: "日期", placeholder: "", isDate: true },
  { key: "other", label: "其他限制", placeholder: "例如受眾、地區等" },
];

const BRAND_SUGGESTION_REQUEST = "請依這個品牌已保存的商品、成效目標與資料，建議第一份投放計畫。沿用已知資訊，缺少或未確認的條件請標示待確認，不要假設已有投放成效。";

/** 建立 Campaign 步驟一（F04-I12，圖 3）：一句話＋選填限制條件 → `POST /campaigns`。
 * 日期不是必填欄位（F04-I11 後端會從句子判斷，判斷不出來就今天～+30 天並標「系統帶入」）；
 * 這裡只在「只填一邊」時擋下來。送出成功後導去步驟二（`ConfirmBriefPage`）確認理解，
 * 不再直接進策略頁——那一步才是第二次、也是最後一次模型呼叫。 */
export function NewCampaignPage({ brandId }: { brandId: string }) {
  const { scope } = useWorkspace();
  const draftKey = `campaign-draft:${scope}:${brandId}`;
  return <CampaignForm key={draftKey} brandId={brandId} draftKey={draftKey} />;
}

function CampaignForm({ brandId, draftKey }: { brandId: string; draftKey: string }) {
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const existingId = search.get("created");
  const [restoring, setRestoring] = useState(!!existingId);
  const life = useRef(new AbortController());
  useEffect(() => { life.current = new AbortController(); return () => life.current.abort(); }, []);
  const [initial] = useState(() => readDraft(draftKey));
  const [goalText, setGoalText] = useState(initial.goalText);
  const [startDate, setStartDate] = useState(initial.startDate);
  const [endDate, setEndDate] = useState(initial.endDate);
  const [openConstraints, setOpenConstraints] = useState<Record<string, boolean>>(initial.openConstraints);
  const [constraintValues, setConstraintValues] = useState<Record<string, string>>(initial.constraintValues);
  const [uploads, setUploads] = useState<AssetUpload[]>([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [created, setCreated] = useState<CampaignDraft | null>(null);
  const [attached, setAttached] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!existingId || created?.id === existingId) { setRestoring(false); return; }
    let cancelled = false; setRestoring(true);
    getCampaign(brandId, existingId).then(value => { if (!cancelled) { setCreated({ ...value, parsed: true }); setGoalText(value.goal_text); } }).catch(e => { if (!cancelled) setError(`找回已建立活動失敗，請重開此頁或至活動清單查看：${String(e)}`); }).finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; };
  }, [brandId, existingId, created?.id]);
  useEffect(() => {
    saveDraft(draftKey, { goalText, startDate, endDate, openConstraints, constraintValues });
  }, [draftKey, goalText, startDate, endDate, openConstraints, constraintValues]);

  function toggleConstraint(key: string) {
    setOpenConstraints((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSubmit(request = goalText) {
    if (!request.trim() || submitting || uploadBusy || restoring || (existingId && !created)) return;
    if (uploads.some(u => u.status !== "complete")) { setError("選取的原檔尚未保存，請重試上傳，或取消該檔選取後繼續。"); return; }
    if ((startDate && !endDate) || (!startDate && endDate)) {
      setError("開始與結束日期請一起填，或兩個都留空。");
      return;
    }
    const signal = life.current.signal;
    setSubmitting(true);
    setError(null);
    setGoalText(request);
    const constraints: Record<string, unknown> = {};
    for (const field of CONSTRAINT_FIELDS) {
      if (field.isDate) continue;
      const value = constraintValues[field.key]?.trim();
      if (openConstraints[field.key] && value) constraints[field.key] = value;
    }
    try {
      const draft = created ?? await createCampaign(brandId, {
        goal_text: request,
        ...(startDate && endDate ? { start_date: startDate, end_date: endDate } : {}),
        ...(Object.keys(constraints).length > 0 ? { constraints } : {}),
      });
      if (signal.aborted) return;
      setCreated(draft);
      setSearch(prev => { const next = new URLSearchParams(prev); next.set("created", draft.id); return next; }, { replace: true });
      const completed = new Set(attached);
      const errors: string[] = [];
      for (const upload of uploads) {
        if (signal.aborted) return;
        if (completed.has(upload.id)) continue;
        try { await attachUpload(brandId, draft.id, upload.id); completed.add(upload.id); }
        catch (e) { errors.push(`${upload.filename}：${e instanceof Error ? e.message : String(e)}`); }
      }
      if (signal.aborted) return;
      setAttached(completed);
      if (errors.length) { setError(`活動已建立，未完成素材仍可重試，不會重建活動。${errors.join("；")}`); setSubmitting(false); return; }
      clearDraft(draftKey);
      navigate(`/brands/${brandId}/ads/new/${draft.id}`, {
        state: draft.parsed
          ? undefined
          : { parseWarning: "這句話沒有完全被理解，請確認下面的欄位。" },
      });
    } catch (err) {
      if (signal.aborted) return;
      setError(err instanceof Error ? err.message : "建立 Campaign 失敗，請稍後再試。");
      setSubmitting(false);
    }
  }


  return (
    <div className="flex flex-col gap-4">
      <Link
        to={`/brands/${brandId}/ads`}
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft size={14} /> 投放中心
      </Link>
      <PageHeader
        title="建立投放計畫"
        description="只要告訴我們你的目標，行銷駕駛艙會幫你整理投放策略、預算、素材與排程。"
      />
      <p className="text-xs text-muted-foreground">未送出的內容會保留在這個分頁，離開後返回可繼續填寫。</p>
      <p className="text-sm text-muted-foreground">商品資料會沿用品牌已保存的內容。有完成的圖片或影片可直接加入，下方不必重新製作素材。</p>
      <UserAssetsLibrary brandId={brandId} readOnly={submitting} onSelection={setUploads} onBusy={setUploadBusy} />
      {created && <p className="text-sm">活動已建立。<Link to={`/brands/${brandId}/ads/campaigns/${created.id}?tab=assets`}>前往此活動核對素材</Link></p>}
      {submitting && <p role="status">讀取品牌／商品／投放紀錄…正在建立活動或加入所選素材。</p>}
      <div className="max-w-3xl">
        <div className="surface">
          <div className="surface-body flex flex-col gap-4">
            <div>
              <label className="mb-2 block text-sm font-medium" htmlFor="goal-textarea">
                你這次想做到什麼？
              </label>
              <p className="mb-2 text-sm text-muted-foreground">
                寫一句話即可，或讓 AI 依已知品牌資料起草，再由你確認。
              </p>
              <Textarea
                id="goal-textarea"
                disabled={submitting || !!created}
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
                placeholder="例如：下個月想推主力商品，希望增加購買。"
                className="min-h-28"
                maxLength={500}
              />
              <p className="mt-1 text-right text-xs text-muted-foreground">
                {goalText.length} / 500
              </p>
            </div>
            <div>
              <label className="mb-2 block text-sm text-muted-foreground">限制條件（選填）</label>
              <div className="flex flex-wrap gap-2">
                {CONSTRAINT_FIELDS.map((field) =>
                  openConstraints[field.key] ? (
                    <span
                      key={field.key}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border py-1 pl-3 pr-1.5 text-sm"
                    >
                      {field.label}
                      {field.isDate ? (
                        <span className="flex items-center gap-1">
                          <Input
                            disabled={submitting || !!created}
                            aria-label="開始日期"
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="h-7 w-32 px-2 text-xs"
                          />
                          <span className="text-muted-foreground">~</span>
                          <Input
                            disabled={submitting || !!created}
                            aria-label="結束日期"
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="h-7 w-32 px-2 text-xs"
                          />
                        </span>
                      ) : (
                        <Input
                          disabled={submitting || !!created}
                          aria-label={field.label}
                          value={constraintValues[field.key] ?? ""}
                          onChange={(e) =>
                            setConstraintValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                          }
                          placeholder={field.placeholder}
                          className="h-7 w-36 px-2 text-xs"
                        />
                      )}
                      <button
                        type="button"
                        disabled={submitting || !!created}
                        aria-label={`移除${field.label}`}
                        onClick={() => {
                          toggleConstraint(field.key);
                          if (field.isDate) {
                            setStartDate("");
                            setEndDate("");
                          }
                        }}
                        className="rounded-full p-0.5 hover:bg-muted"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ) : (
                    <button
                      key={field.key}
                      type="button"
                      disabled={submitting || !!created}
                      onClick={() => toggleConstraint(field.key)}
                      className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1 text-sm text-muted-foreground hover:bg-muted"
                    >
                      <Plus size={13} />
                      {field.label}
                    </button>
                  ),
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">這裡的預算上限只適用於本次活動。品牌月額度沿用<Link className="text-primary underline" to={`/brands/${encodeURIComponent(brandId)}/ads`}>投放中心</Link>的設定，兩者會分別核對。</p>
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex flex-wrap justify-end gap-3">
              {!goalText.trim() && !created && <Button variant="outline" onClick={() => void handleSubmit(BRAND_SUGGESTION_REQUEST)} disabled={submitting || uploadBusy || restoring || !!existingId}>請 AI 依品牌資料建議</Button>}
              <Button onClick={() => void handleSubmit()} disabled={!goalText.trim() || submitting || uploadBusy || restoring || (!!existingId && !created)}>
                <Sparkles size={15} />
                {created ? "重試加入未完成素材並繼續" : "產生建議"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
