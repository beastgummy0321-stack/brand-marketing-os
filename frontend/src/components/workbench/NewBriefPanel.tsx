import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { createBrief, LENGTH_HINTS, LENGTH_LABELS, type NewBrief } from "@/lib/workbenchApi";
import { BUTTON_LABELS, PART_LABELS } from "./copy";
import type { BriefPart } from "./BriefList";

const PART_ORDER: BriefPart[] = ["copy", "image_prompt", "video_script", "free"];
const LENGTH_ORDER: (keyof typeof LENGTH_LABELS)[] = ["short", "medium", "long"];

/** 新工單表單（票 04）：從側板搬進工作區，欄位收斂成 §1 講的那些——種類、七維座標、視覺調性
 * 全部拿掉（座標只從排程節點來，視覺欄位跟著上一輪座標一起沒了）；`parts` 換成多選，`kind`
 * 這個單選欄位不存在了。 */
export function NewBriefPanel({
  brandId,
  initialPart,
  onCreated,
}: {
  brandId: string;
  initialPart: BriefPart | null;
  onCreated: (briefId: string) => void;
}) {
  const [parts, setParts] = useState<BriefPart[]>(initialPart ? [initialPart] : []);
  const [copyLength, setCopyLength] = useState<keyof typeof LENGTH_LABELS>("medium");
  const [imagePromptCount, setImagePromptCount] = useState("");
  const [videoScriptCount, setVideoScriptCount] = useState("");
  const [productId, setProductId] = useState("");
  const [freeText, setFreeText] = useState("");
  const [useBrandKnowledge, setUseBrandKnowledge] = useState(true);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [products, setProducts] = useState<ProductListItem[]>([]);

  // 從左欄「開始生成」點進來的那個 part 每次都要重新預勾——使用者可能連續按了兩個不同
  // 入口，第二次點擊要蓋掉第一次的殘留，不是累加。
  useEffect(() => {
    setParts(initialPart ? [initialPart] : []);
  }, [initialPart]);

  useEffect(() => {
    fetchProductList(brandId)
      .then((list) => setProducts(list.filter((p) => p.status === "active")))
      .catch(() => {});
  }, [brandId]);

  function togglePart(part: BriefPart) {
    setParts((prev) => (prev.includes(part) ? prev.filter((p) => p !== part) : [...prev, part]));
  }

  const form = useFormSubmit(async () => {
    const trimmedFreeText = freeText.trim();
    const brief: NewBrief = {
      product_id: productId || null,
      style_key: "ugc",
      request: {
        use_brand_knowledge: useBrandKnowledge,
        free_text: trimmedFreeText || null,
        image_prompt_count:
          parts.includes("image_prompt") && imagePromptCount.trim() !== "" ? Number(imagePromptCount) : null,
        video_script_count:
          parts.includes("video_script") && videoScriptCount.trim() !== "" ? Number(videoScriptCount) : null,
        parts,
        copy_length: copyLength,
      },
    };
    const created = await createBrief(brandId, brief);
    onCreated(created.id);
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setFieldError(null);
    if (parts.length === 0) {
      setFieldError("至少勾一種要生成的內容。");
      return;
    }
    if (parts.includes("image_prompt") && imagePromptCount.trim() !== "") {
      const count = Number(imagePromptCount);
      if (!Number.isInteger(count) || count < 1 || count > 30) {
        setFieldError("要幾條提示詞須介於 1 到 30 之間。");
        return;
      }
    }
    if (parts.includes("video_script")) {
      const count = Number(videoScriptCount);
      if (videoScriptCount.trim() === "" || !Number.isInteger(count) || count < 1 || count > 5) {
        setFieldError("要幾支腳本須介於 1 到 5 之間。");
        return;
      }
    }
    void form.submit();
  }

  return (
    <form className="surface p-5 flex flex-col gap-4" onSubmit={handleSubmit}>
      <h2 className="font-display text-lg text-foreground">新工單</h2>

      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="font-medium text-foreground">要生成什麼</legend>
        {PART_ORDER.map((part) => (
          <label key={part} className="flex items-center gap-2">
            <input type="checkbox" checked={parts.includes(part)} onChange={() => togglePart(part)} />
            {PART_LABELS[part]}
          </label>
        ))}
      </fieldset>

      {parts.includes("copy") && (
        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="font-medium text-foreground">文案長度</legend>
          {LENGTH_ORDER.map((length) => (
            <label key={length} className="flex items-start gap-2">
              <input
                type="radio"
                name="copy_length"
                checked={copyLength === length}
                onChange={() => setCopyLength(length)}
              />
              <span className="flex flex-col">
                <span>{LENGTH_LABELS[length]}</span>
                <span className="text-xs text-muted-foreground">{LENGTH_HINTS[length]}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {parts.includes("image_prompt") && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">要幾條提示詞（選填）</span>
          <Input
            type="number"
            min={1}
            max={30}
            value={imagePromptCount}
            onChange={(e) => setImagePromptCount(e.target.value)}
            className="w-32 numeric"
          />
        </label>
      )}

      {parts.includes("video_script") && (
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
        <span className="font-medium text-foreground">需求說明（選填）</span>
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
  );
}
