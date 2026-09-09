import { useEffect, useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { fetchCoordinates, type Coordinate } from "@/lib/coordinatesApi";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import {
  createBrief, fetchStyles, type ImageStyle, type NewBrief,
} from "@/lib/workbenchApi";
import { BUTTON_LABELS } from "./copy";

type BriefKind = "copy" | "image_prompt" | "video_script" | "free";

const KIND_OPTIONS: [BriefKind, string][] = [
  ["copy", "文案"],
  ["image_prompt", "圖片提示詞"],
  ["video_script", "影片腳本"],
  ["free", "自由生成"],
];

const VISUAL_TONE_OPTIONS: [string, string][] = [
  ["", "不指定"],
  ["暗調強對比", "暗調強對比"],
  ["暖調生活", "暖調生活"],
];

// app/workbench/routes.py:64 逐字——先在前端擋掉，跟後端 409/400 用同一句話，畫面不用等
// 一趟網路來回才知道漏填。
const ON_IMAGE_TEXTS_REQUIRED_MESSAGE = "請填圖上文字（1 到 5 則，每則不超過 27 字）。";
const ON_IMAGE_TEXT_MAX = 27;
const ON_IMAGE_TEXT_LIMIT = 5;

export function NewBriefPanel({
  brandId,
  onClose,
  onCreated,
}: {
  brandId: string;
  onClose: () => void;
  onCreated: (briefId: string) => void;
}) {
  const [kind, setKind] = useState<BriefKind>("copy");
  const [productId, setProductId] = useState("");
  const [styleKey, setStyleKey] = useState("ugc");
  const [visualTone, setVisualTone] = useState("");
  const [angleLabel, setAngleLabel] = useState("");
  const [visualConcept, setVisualConcept] = useState("");
  const [freeText, setFreeText] = useState("");
  const [useBrandKnowledge, setUseBrandKnowledge] = useState(true);
  const [onImageTexts, setOnImageTexts] = useState<string[]>([""]);
  const [imagePromptCount, setImagePromptCount] = useState("");
  const [videoScriptCount, setVideoScriptCount] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);

  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [styles, setStyles] = useState<ImageStyle[]>([]);
  const [angleCoordinates, setAngleCoordinates] = useState<Coordinate[]>([]);

  useEffect(() => {
    fetchProductList(brandId)
      .then((list) => setProducts(list.filter((p) => p.status === "active")))
      .catch(() => {});
    fetchStyles()
      .then(setStyles)
      .catch(() => {});
    fetchCoordinates(brandId)
      .then((list) =>
        setAngleCoordinates(list.filter((c) => c.dimension === "angle" && c.disabled_at === null)),
      )
      .catch(() => {});
  }, [brandId]);

  const form = useFormSubmit(async () => {
    const trimmedFreeText = freeText.trim();
    const brief: NewBrief = {
      kind,
      product_id: productId || null,
      coordinates: angleLabel ? { angle: angleLabel } : null,
      visual_tone: visualTone === "暗調強對比" || visualTone === "暖調生活" ? visualTone : null,
      visual_concept: visualConcept.trim() || null,
      style_key: styleKey,
      request: {
        use_brand_knowledge: useBrandKnowledge,
        free_text: trimmedFreeText || null,
        // 票面只把「圖上文字」標 required；「要幾條提示詞」沒有這個字——後端
        // `_parts_for()` 也只在有給張數時才排 image_prompt 這個 part（ADR 0068 §7：
        // 張數沒有預設值），沒填就是「先建工單，之後在詳情頁按產提示詞再給張數」。
        image_prompt_count:
          kind === "image_prompt" && imagePromptCount.trim() !== "" ? Number(imagePromptCount) : null,
        // 「要幾支腳本」票面標 required（跟圖上文字同一句話），送出前 handleSubmit 已經擋掉
        // 空值，這裡直接轉數字。
        video_script_count:
          kind === "video_script" && videoScriptCount.trim() !== "" ? Number(videoScriptCount) : null,
        on_image_texts:
          kind === "image_prompt" ? onImageTexts.map((t) => t.trim()).filter(Boolean) : null,
      },
    };
    const created = await createBrief(brandId, brief);
    onCreated(created.id);
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFieldError(null);
    if (kind === "image_prompt") {
      const validTexts = onImageTexts.map((t) => t.trim()).filter(Boolean);
      if (validTexts.length === 0 || validTexts.length > ON_IMAGE_TEXT_LIMIT) {
        setFieldError(ON_IMAGE_TEXTS_REQUIRED_MESSAGE);
        return;
      }
      // 要幾條提示詞不是必填（票面只把「required」寫在圖上文字那句），有填才驗範圍。
      if (imagePromptCount.trim() !== "") {
        const count = Number(imagePromptCount);
        if (!Number.isInteger(count) || count < 1 || count > 30) {
          setFieldError("要幾條提示詞須介於 1 到 30 之間。");
          return;
        }
      }
    }
    if (kind === "video_script") {
      // 「要幾支腳本」是必填（票面 §3，跟圖片提示詞的「要幾條提示詞」不是同一條規則）：
      // 空著就擋在這裡，連 API 都不打。
      const count = Number(videoScriptCount);
      if (videoScriptCount.trim() === "" || !Number.isInteger(count) || count < 1 || count > 5) {
        setFieldError("要幾支腳本須介於 1 到 5 之間。");
        return;
      }
    }
    void form.submit();
  }

  function updateImageText(index: number, value: string) {
    setOnImageTexts((prev) => prev.map((t, i) => (i === index ? value.slice(0, ON_IMAGE_TEXT_MAX) : t)));
  }

  return (
    <SidePanel ariaLabel="新工單" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">新工單</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <form className="form-section flex flex-col gap-4 pt-4" onSubmit={handleSubmit}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">種類</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as BriefKind)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {KIND_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">產品（選填）</span>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">不指定</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">風格</span>
          <select
            value={styleKey}
            onChange={(e) => setStyleKey(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {styles.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">視覺調性</span>
          <select
            value={visualTone}
            onChange={(e) => setVisualTone(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {VISUAL_TONE_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">切角（選填）</span>
          <select
            value={angleLabel}
            onChange={(e) => setAngleLabel(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">不指定</option>
            {angleCoordinates.map((c) => (
              <option key={c.id} value={c.label}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">畫面概念（選填）</span>
          <Textarea value={visualConcept} onChange={(e) => setVisualConcept(e.target.value)} rows={2} />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">需求說明</span>
          <Textarea value={freeText} onChange={(e) => setFreeText(e.target.value)} rows={3} />
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useBrandKnowledge}
            onChange={(e) => setUseBrandKnowledge(e.target.checked)}
          />
          帶品牌資料
        </label>

        {kind === "video_script" && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">要幾支腳本</span>
            <Input
              type="number"
              min={1}
              max={5}
              value={videoScriptCount}
              onChange={(e) => setVideoScriptCount(e.target.value)}
              className="w-32 numeric"
            />
          </label>
        )}

        {kind === "image_prompt" && (
          <>
            <div className="flex flex-col gap-2 text-sm">
              <span className="font-medium text-foreground">圖上文字</span>
              {onImageTexts.map((text, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    type="text"
                    value={text}
                    maxLength={ON_IMAGE_TEXT_MAX}
                    onChange={(e) => updateImageText(i, e.target.value)}
                  />
                  {onImageTexts.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`移除第 ${i + 1} 則圖上文字`}
                      onClick={() => setOnImageTexts((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden="true" />
                    </Button>
                  )}
                </div>
              ))}
              {onImageTexts.length < ON_IMAGE_TEXT_LIMIT && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => setOnImageTexts((prev) => [...prev, ""])}
                >
                  新增一則
                </Button>
              )}
              <span className="text-xs text-muted-foreground">圖上出現的字必須是你寫的，不讓模型自己編</span>
            </div>

            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-foreground">要幾條提示詞</span>
              <Input
                type="number"
                min={1}
                max={30}
                value={imagePromptCount}
                onChange={(e) => setImagePromptCount(e.target.value)}
                className="w-32 numeric"
              />
            </label>
          </>
        )}

        {fieldError && (
          <p role="alert" className="text-sm text-danger">
            {fieldError}
          </p>
        )}
        {form.error && (
          <p role="alert" className="text-sm text-danger">
            {form.error}
          </p>
        )}
        <div>
          <Button type="submit" disabled={form.saving}>
            {form.saving ? "建立中…" : BUTTON_LABELS.createBrief}
          </Button>
        </div>
      </form>
    </SidePanel>
  );
}
