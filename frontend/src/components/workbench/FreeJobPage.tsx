import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Image as ImageIcon, Loader2, Paperclip, Sparkles, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Button } from "@/components/layout/ui/button";
import { Textarea } from "@/components/layout/ui/textarea";
import { Badge } from "@/components/layout/ui/badge";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { cn } from "@/lib/utils";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import {
  createFreePack,
  fetchStyles,
  parseFreeText,
  type FreeParseOutput,
  type FreeParseSpec,
  type ImageStyle,
  type NewFreePackRequest,
  type PackCard,
  type ProductPart,
} from "@/lib/workbenchApi";
import { PackCardTile } from "./WorkbenchHomePage";

const MAX_LEN = 1000;
const NOT_SPECIFIED = "不指定";
const PLATFORM_OPTIONS = [NOT_SPECIFIED, "Meta", "TikTok", "LINE", "Google"];
const SIZE_OPTIONS = [NOT_SPECIFIED, "1:1（方形）", "4:5（直式）", "9:16（全螢幕）", "16:9（橫式）"];
const EXAMPLES = ["冬季保健主題廣告", "產品開箱短影音", "會員招募貼文", "節慶促銷 Banner"];
const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_FILE_BYTES = 10 * 1024 * 1024;

const PART_OPTIONS: { value: ProductPart; label: string; icon: typeof ImageIcon }[] = [
  { value: "image_prompt", label: "圖片", icon: ImageIcon },
  { value: "copy", label: "文案", icon: Sparkles },
  { value: "video_script", label: "腳本", icon: Sparkles },
];

export const PART_LABEL: Record<ProductPart, string> = {
  copy: "文案",
  image_prompt: "圖片",
  video_script: "腳本",
};

/** 精準控制表單——解析完成前用來組 `defaults` 送去 `/parse`；解析完成後直接編輯
 * `spec` 本身（人物欄位對應 `spec.audience`、主要訴求對應 `spec.key_message`，§F02-I10
 * 「the mapping is the one piece of logic on this page」之外的欄位只影響這支表單本身，
 * 見票面「人物／場景 have no spec field」）。`scene`（場景）不在 `spec` 七個鍵裡，純本頁
 * 欄位，不送出——跟圖片生成港口一樣是保留的港口，下方欄位自己的提示文字說明這件事。 */
interface PreciseControl {
  part: ProductPart;
  count: number;
  styleKey: string;
  platform: string;
  size: string;
  person: string;
  scene: string;
  appeal: string;
}

function defaultControl(part: ProductPart): PreciseControl {
  return {
    part,
    count: 1,
    styleKey: "",
    platform: NOT_SPECIFIED,
    size: NOT_SPECIFIED,
    person: "",
    scene: "",
    appeal: "",
  };
}

function orNull(value: string): string | null {
  return value && value !== NOT_SPECIFIED ? value : null;
}

function controlToDefaults(text: string, control: PreciseControl): FreeParseSpec {
  return {
    topic: text || null,
    outputs: [{ part: control.part, count: control.count }],
    style_hint: control.styleKey || null,
    platform: orNull(control.platform),
    size: orNull(control.size),
    audience: control.person || null,
    key_message: control.appeal || null,
  };
}

/** 反向：AI 解析結果只填會影響 `spec` 的四個 `PreciseControl` 欄位（`part`／`count` 取
 * `outputs[0]`，其餘 outputs 只在表格與送出時保留，不逐一對應到單選的「素材類型」）。 */
function specToControl(spec: FreeParseSpec, fallback: PreciseControl): PreciseControl {
  const first = spec.outputs[0];
  return {
    ...fallback,
    part: first?.part ?? fallback.part,
    count: first?.count ?? fallback.count,
    styleKey: spec.style_hint ?? fallback.styleKey,
    platform: spec.platform ?? fallback.platform,
    size: spec.size ?? fallback.size,
    person: spec.audience ?? fallback.person,
    appeal: spec.key_message ?? fallback.appeal,
  };
}

/** 這支頁面唯一的分支邏輯（票面「real falsifier」）：`spec.outputs` 的每一項
 * `required_outputs[part]` = 解析出來的張數（沒給就是 1），同一個數字也是這一輪的生成數量
 * ——一輪就能滿足這個任務包（2026-09-12 使用者裁決）。素材組層的 `coordinates`／`request`
 * 帶入 `spec` 其餘欄位，落在 `jobs.py` 既有讀得到的鍵上：`audience`／`format`／
 * `free_text`／`promotion_note`；`platform` 走 pack 層的 `context.platform`
 * （F02-I18，`ARCHITECTURE.md` §5.4 handoff contract，`PackDetail.meta.platform` 讀回）。 */
export function specToCreateBody(
  spec: FreeParseSpec,
  form: { text: string; productId: string | null },
): NewFreePackRequest {
  const requiredOutputs: Partial<Record<ProductPart, number>> = {};
  const request: Record<string, unknown> = { free_text: form.text };
  const outputs: FreeParseOutput[] = spec.outputs.length > 0
    ? spec.outputs
    : [{ part: "image_prompt", count: 1 }];
  for (const output of outputs) {
    const count = output.count ?? 1;
    requiredOutputs[output.part] = count;
    request[`${output.part}_count`] = count;
  }
  if (spec.key_message) request.promotion_note = spec.key_message;
  const coordinates: Record<string, unknown> = {};
  if (spec.audience) coordinates.audience = spec.audience;
  if (spec.size) coordinates.format = spec.size;
  const context: Record<string, unknown> = {};
  if (spec.platform) context.platform = spec.platform;

  return {
    free_text: form.text,
    product_id: form.productId,
    style_key: spec.style_hint ?? null,
    sets: [{ required_outputs: requiredOutputs, request, coordinates }],
    summary: {
      "情境": spec.topic || form.text,
      "目標受眾": spec.audience ?? "",
      "重點訊息": spec.key_message ?? "",
    },
    context,
  };
}

export function FreeJobPage({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { brands } = useWorkspace();
  const brand = brands.find((b) => b.brand_id === brandId);

  const initialPart = (searchParams.get("type") as ProductPart | null) ?? "image_prompt";
  const [text, setText] = useState("");
  const [useBrand, setUseBrand] = useState(true);
  const [productId, setProductId] = useState<string | null>(null);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [styles, setStyles] = useState<ImageStyle[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [precise, setPrecise] = useState(false);
  const [control, setControl] = useState<PreciseControl>(defaultControl(
    PART_OPTIONS.some((p) => p.value === initialPart) ? initialPart : "image_prompt",
  ));

  const [spec, setSpec] = useState<FreeParseSpec | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProductList(brandId).then(setProducts).catch(() => setProducts([]));
    fetchStyles().then(setStyles).catch(() => setStyles([]));
  }, [brandId]);

  function updateControl(patch: Partial<PreciseControl>) {
    setControl((prev) => {
      const next = { ...prev, ...patch };
      // 解析完成後再調整精準控制：跟著改 spec，讓第二次點擊「一律送出表格上顯示的東西」。
      if (spec) {
        setSpec({
          ...spec,
          outputs: [{ part: next.part, count: next.count }],
          style_hint: next.styleKey || null,
          platform: orNull(next.platform),
          size: orNull(next.size),
          audience: next.person || null,
          key_message: next.appeal || null,
        });
      }
      return next;
    });
  }

  function handleFile(selected: File | null) {
    setFileError(null);
    if (!selected) {
      setFile(null);
      return;
    }
    if (!ACCEPTED_IMAGE_TYPES.includes(selected.type)) {
      setFileError("只支援 JPG、PNG、WEBP 格式。");
      return;
    }
    if (selected.size > MAX_FILE_BYTES) {
      setFileError("單檔上限 10MB，請換一張較小的圖片。");
      return;
    }
    setFile(selected);
  }

  async function handlePrimaryAction() {
    setError(null);
    if (!spec) {
      setParsing(true);
      try {
        const defaults = controlToDefaults(text, control);
        const result = await parseFreeText(brandId, text, defaults);
        setSpec(result.spec);
        setNote(result.note);
        setControl((prev) => specToControl(result.spec, prev));
      } catch (err) {
        setError(err instanceof Error ? err.message : "AI 解析失敗，請稍後再試。");
      } finally {
        setParsing(false);
      }
      return;
    }
    setSubmitting(true);
    try {
      const pack = await createFreePack(brandId, specToCreateBody(spec, {
        text,
        productId: useBrand ? productId : null,
      }));
      navigate(`/brands/${brandId}/workbench/packs/${pack.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立自由工作失敗，請稍後再試。");
    } finally {
      setSubmitting(false);
    }
  }

  const trimmedLen = text.length;
  const canSubmit = trimmedLen > 0 && trimmedLen <= MAX_LEN && !parsing && !submitting;

  const previewOutputs: FreeParseOutput[] = spec?.outputs.length
    ? spec.outputs
    : [{ part: control.part, count: control.count }];
  const previewPack: PackCard = {
    id: "preview",
    name: "自由工作 #（建立後產生）",
    subtitle: spec?.topic || text,
    source_kind: "free_job",
    source_label: "自由創作",
    status: "pending",
    sets_total: 1,
    sets_done: 0,
    progress_pct: 0,
    next_step: null,
    counts: previewOutputs.map((o) => ({
      part: o.part, label: PART_LABEL[o.part], selected: 0, required: o.count ?? 1,
    })),
    updated_at: new Date().toISOString(),
  };

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: "素材工作檯", href: `/brands/${brandId}/workbench` },
          { label: "自由創作" },
        ]}
      />
      <PageHeader
        title="自由創作"
        description="用自然語言開始，AI 會幫你整理成可執行素材任務。"
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_360px]">
        <div className="surface flex flex-col gap-4 p-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground" htmlFor="free-job-text">
              告訴 AI 你想創作什麼
            </label>
            <div className="relative">
              <Textarea
                id="free-job-text"
                value={text}
                maxLength={MAX_LEN}
                onChange={(e) => {
                  setText(e.target.value);
                  setSpec(null);
                  setNote(null);
                }}
                placeholder="幫 Beast Gummy 做五張夜跑廣告，風格真實、有競技感，適合 Meta 4:5"
                className="min-h-24"
              />
              <span className="absolute bottom-2 right-3 text-xs text-muted-foreground">
                {trimmedLen}／1,000
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <span className="text-xs text-muted-foreground">試試看：</span>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => { setText(example); setSpec(null); setNote(null); }}
                  className="rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-foreground">品牌</span>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => setUseBrand(true)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium",
                    useBrand ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card",
                  )}
                >
                  {brand ? brand.brand_name : "目前品牌"}
                </button>
                <button
                  type="button"
                  onClick={() => setUseBrand(false)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium",
                    !useBrand ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card",
                  )}
                >
                  {NOT_SPECIFIED}
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-foreground">商品</span>
              <select
                value={productId ?? ""}
                disabled={!useBrand}
                onChange={(e) => setProductId(e.target.value || null)}
                className="h-9 rounded-md border border-border bg-card px-2 text-sm disabled:opacity-50"
              >
                <option value="">{NOT_SPECIFIED}</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-foreground">參考圖（選填）</span>
            {file ? (
              <div className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm">
                <span className="truncate">{file.name}</span>
                <button type="button" onClick={() => handleFile(null)} aria-label="移除參考圖">
                  <X className="size-4 text-muted-foreground" />
                </button>
              </div>
            ) : (
              <label
                className="flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed border-border bg-card px-3 py-4 text-center text-xs text-muted-foreground hover:bg-accent"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleFile(e.dataTransfer.files?.[0] ?? null);
                }}
              >
                <Paperclip className="size-4" />
                點擊上傳、拖曳檔案到此
                <span>支援 JPG、PNG、WEBP，單檔上限 10MB</span>
                <input
                  type="file"
                  accept={ACCEPTED_IMAGE_TYPES.join(",")}
                  className="hidden"
                  onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                />
              </label>
            )}
            {fileError && <p className="text-xs text-destructive">{fileError}</p>}
            <p className="text-xs text-muted-foreground">
              參考圖還沒接上生成流程，這裡先保留席位；接上後同一張圖直接派上用場。
            </p>
          </div>

          <div className="flex flex-col gap-3 rounded-md border border-border p-3">
            <div className="flex items-center gap-1.5 rounded-md bg-muted p-1 text-sm">
              <button
                type="button"
                onClick={() => setPrecise(false)}
                className={cn("flex-1 rounded-md px-3 py-1.5", !precise ? "bg-card font-medium shadow-sm" : "text-muted-foreground")}
              >
                快速生成
              </button>
              <button
                type="button"
                onClick={() => setPrecise(true)}
                className={cn("flex-1 rounded-md px-3 py-1.5", precise ? "bg-card font-medium shadow-sm" : "text-muted-foreground")}
              >
                精準控制
              </button>
            </div>
            {precise && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Field label="素材類型">
                  <select
                    value={control.part}
                    onChange={(e) => updateControl({ part: e.target.value as ProductPart })}
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  >
                    {PART_OPTIONS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="平台">
                  <select
                    value={control.platform}
                    onChange={(e) => updateControl({ platform: e.target.value })}
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  >
                    {PLATFORM_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </Field>
                <Field label="尺寸">
                  <select
                    value={control.size}
                    onChange={(e) => updateControl({ size: e.target.value })}
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  >
                    {SIZE_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </Field>
                <Field label="風格">
                  <select
                    value={control.styleKey}
                    onChange={(e) => updateControl({ styleKey: e.target.value })}
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  >
                    <option value="">{NOT_SPECIFIED}</option>
                    {styles.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </Field>
                <Field label="人物">
                  <input
                    value={control.person}
                    onChange={(e) => updateControl({ person: e.target.value })}
                    placeholder="例：運動族群"
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  />
                </Field>
                <Field label="場景">
                  <input
                    value={control.scene}
                    onChange={(e) => updateControl({ scene: e.target.value })}
                    placeholder="例：夜跑／城市"
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  />
                  <span className="text-[11px] text-muted-foreground">
                    場景還沒接上生成流程，這裡先保留席位；接上後同一個欄位直接生效。
                  </span>
                </Field>
                <Field label="主要訴求">
                  <input
                    value={control.appeal}
                    onChange={(e) => updateControl({ appeal: e.target.value })}
                    placeholder="例：提升表現／補充能量"
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  />
                </Field>
                <Field label="產出數量">
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={control.count}
                    onChange={(e) => updateControl({ count: Math.max(1, Number(e.target.value) || 1) })}
                    className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
                  />
                </Field>
              </div>
            )}
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <div className="flex justify-end">
            <Button size="lg" disabled={!canSubmit} onClick={() => void handlePrimaryAction()}>
              {parsing && <Loader2 className="size-4 animate-spin" />}
              {spec ? "確認並生成" : "建立自由工作 →"}
            </Button>
          </div>
        </div>

        <div className="surface flex flex-col gap-3 p-4">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" />
              AI 解析結果
            </h2>
            {spec && <Badge variant="outline">即時預覽</Badge>}
          </div>
          {!spec ? (
            <p className="text-sm text-muted-foreground">
              按下「建立自由工作」後，這裡會顯示 AI 幫你整理出的創作規格。
            </p>
          ) : (
            <>
              {note && <p className="text-xs text-muted-foreground">{note}</p>}
              <dl className="flex flex-col gap-2 text-sm">
                <Row label="專案主題">{spec.topic || "—"}</Row>
                <Row label="需要產出">
                  <div className="flex flex-wrap gap-1">
                    {spec.outputs.map((o, i) => (
                      <Badge key={i} variant="outline">{PART_LABEL[o.part]} {o.count} 份</Badge>
                    ))}
                  </div>
                </Row>
                <Row label="風格設定">
                  {styles.find((s) => s.key === spec.style_hint)?.label || spec.style_hint || "—"}
                </Row>
                <Row label="投放平台">{spec.platform || "—"}</Row>
                <Row label="尺寸">{spec.size || "—"}</Row>
                <Row label="目標受眾">{spec.audience || "—"}</Row>
                <Row label="主要訴求">{spec.key_message || "—"}</Row>
              </dl>
              <p className="text-xs text-muted-foreground">
                AI 可能會調整細節以達到更好的生成效果，你也可以在建立後繼續編輯。
              </p>
            </>
          )}
        </div>
      </div>

      <div className="surface flex flex-col gap-2 p-4">
        <h2 className="text-sm font-semibold text-foreground">預覽將建立的工作項目</h2>
        <p className="text-xs text-muted-foreground">
          送出後，系統會建立一個自由工作，你可以在素材工作檯中追蹤進度。
        </p>
        <div className="pointer-events-none max-w-sm opacity-90">
          <PackCardTile pack={previewPack} brandId={brandId} onClose={() => {}} />
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/60 pb-2 last:border-0 last:pb-0">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium text-foreground">{children}</dd>
    </div>
  );
}
