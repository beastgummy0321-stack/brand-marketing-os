import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import type { SourcedText } from "@/lib/intakeOnboardingApi";
import type { CreatedProduct, ProductPhoto, ProductWhat } from "@/lib/intakeProductApi";
import { createProduct, fetchProductWhat, proposeProductCustom, saveProductWhat } from "@/lib/intakeProductApi";
import { uploadAsset } from "@/lib/libraryApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { AiTag } from "../shared/AiTag";
import { CustomEscape, CustomMark } from "../shared/CustomEscape";

/** Prototype `R.p1` head of `.harness/scratch/prototype/f41-onboarding/index.html`. */
const TITLE = "這個商品是什麼";
const PURPOSE = "給商品頁網址，系統先讀；每個商品各建一次";
const PHOTO_ACCEPT = ".jpg,.jpeg,.png,.webp";
const IN = "h-auto w-full rounded-lg bg-card px-3 py-[9px] text-sm shadow-none";
const AREA =
  "w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none";

type TextKey = "intro" | "mechanism" | "difference";
const TEXT_KEYS: TextKey[] = ["intro", "mechanism", "difference"];
type Texts = Record<TextKey, string>;

const textsOf = (what: ProductWhat): Texts => ({ intro: what.intro.value, mechanism: what.mechanism.value, difference: what.difference.value });

/** `/brands/:b/products/new`: the name + 商品頁網址 rows of `#/p1`; 下一步 creates the product (with a URL the
 * product-page read starts on the server) and hands its id on. */
export function NewProductStep({ brandId, nav, back, onCreated }: {
  brandId: string;
  nav: StepNav;
  back: BarBack;
  onCreated: (created: CreatedProduct) => void;
}) {
  const [name, setName] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    const trimmed = pageUrl.trim();
    onCreated(await createProduct(brandId, trimmed ? { name: name.trim(), page_url: trimmed } : { name: name.trim() }));
  });
  const ready = !!name.trim() && !saving;

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) void submit();
      }}
    >
      <OnboardingStepHead {...nav} crumb={productCrumb(nav, name)} title={TITLE} purpose={PURPOSE} />
      <section className="rounded-xl border border-border bg-card px-[22px] py-5">
        <NameRow value={name} onChange={setName} />
        <UrlRow value={pageUrl} onChange={setPageUrl} />
      </section>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <OnboardingBar back={back}>
        <NextButton disabled={!ready} reason={saving ? null : nextBlocked(name, false)} />
      </OnboardingBar>
    </form>
  );
}

/** F47-I03 (drill-10 乙 #4): why 下一步 is off, naming what is missing; `null` = ready. */
function nextBlocked(name: string, uploading: boolean): string | null {
  if (!name.trim()) return "先填商品名稱";
  if (uploading) return "商品照上傳中，傳完才能下一步";
  return null;
}

/** The bar's primary button (`BarNext`) with F47-I03's disabled reason. */
function NextButton({ disabled, reason }: { disabled: boolean; reason: string | null }) {
  return (
    <Button type="submit" size="lg" className="font-semibold" disabled={disabled} disabledReason={reason ?? undefined}>
      下一步 →
    </Button>
  );
}

/** Product onboarding `#/p1` 這個商品是什麼 (prototype `R.p1`): name, product page (also the ads' default landing
 * page), product photos (the existing official-asset upload with `product_id`), intro, mechanism and difference —
 * each text pre-filled by the product-page read with its tag while the field still holds the loaded value; the
 * difference ends with 「自訂」 (product block `difference`), whose value fills the field marked 「你自訂」.
 * `what` comes from the shell; a newer `what` (the read finished) replaces only the fields the user has not
 * changed. 下一步 saves through `PUT …/onboarding/what` and moves on only after the server confirmed. */
export function WhatStep({ brandId, productId, nav, back, what, prefillDone, above, onSaved }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  what: ProductWhat;
  /** The product-page read finished: a field it found nothing for reads 「網站上沒找到」. */
  prefillDone: boolean;
  /** The product-page read's running / failed row, between the head and the form. */
  above?: ReactNode;
  onSaved: (saved: ProductWhat) => void | Promise<void>;
}) {
  const [name, setName] = useState(what.name);
  const [pageUrl, setPageUrl] = useState(what.page_url);
  const [texts, setTexts] = useState<Texts>(() => textsOf(what));
  const [photos, setPhotos] = useState<ProductPhoto[]>(what.photos);
  const [uploading, setUploading] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  /** The value 「自訂」 filled 跟別人不一樣的地方 with: marked 你自訂 while the field still holds it. */
  const [customDifference, setCustomDifference] = useState<string | null>(null);
  /** The `what` the fields were last filled from. */
  const base = useRef(what);

  useEffect(() => {
    const prev = base.current;
    if (prev === what) return;
    base.current = what;
    setName((v) => (v === prev.name ? what.name : v));
    setPageUrl((v) => (v === prev.page_url ? what.page_url : v));
    setTexts((cur) => {
      const next = { ...cur };
      for (const key of TEXT_KEYS) if (cur[key] === prev[key].value) next[key] = what[key].value;
      return next;
    });
    setPhotos(what.photos);
  }, [what]);

  async function upload(file: File | undefined) {
    if (!file) return;
    setPhotoError(null);
    setUploading(true);
    try {
      await uploadAsset(brandId, { asset_kind: "product_photo", product_id: productId, title: file.name, file });
      setPhotos((await fetchProductWhat(brandId, productId)).photos);
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : "上傳失敗，請稍後再試。");
    } finally {
      setUploading(false);
    }
  }

  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    const saved = await saveProductWhat(brandId, productId, {
      name: name.trim(),
      page_url: pageUrl.trim(),
      intro: texts.intro.trim(),
      mechanism: texts.mechanism.trim(),
      difference: texts.difference.trim(),
    });
    await onSaved(saved);
  });
  const ready = !!name.trim() && !saving && !uploading;

  const tag = (key: TextKey) => {
    const field: SourcedText = base.current[key];
    if (key === "difference" && customDifference !== null && texts.difference === customDifference) return <div className="mt-1"><CustomMark /></div>;
    if (texts[key] !== field.value || (field.source === "none" && !prefillDone)) return null;
    return field.source === "saved" ? null : <div className="mt-1"><AiTag source={field.source} note={field.note} /></div>;
  };
  const setText = (key: TextKey) => (value: string) => setTexts((cur) => ({ ...cur, [key]: value }));

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) void submit();
      }}
    >
      <OnboardingStepHead {...nav} title={TITLE} purpose={PURPOSE} />
      {above}
      <section className="rounded-xl border border-border bg-card px-[22px] py-5">
        <NameRow value={name} onChange={setName} />
        <UrlRow value={pageUrl} onChange={setPageUrl} />
        <Row label="商品照" note="做廣告直接用">
          <div className="flex flex-wrap items-center gap-2">
            {photos.map((p) => (
              <Thumb key={p.id} url={p.url} />
            ))}
            <Button type="button" variant="outline" size="sm" disabled={uploading} onClick={() => fileInput.current?.click()}>
              {uploading ? "上傳中…" : "＋上傳"}
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept={PHOTO_ACCEPT}
              aria-label="上傳商品照"
              className="sr-only"
              tabIndex={-1}
              disabled={uploading}
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </div>
          {photoError && <p role="alert" className="mt-2 text-xs text-danger">{photoError}</p>}
        </Row>
        <Row label={<label htmlFor="p1-intro">一句話介紹</label>}>
          <Input id="p1-intro" className={IN} value={texts.intro} onChange={(e) => setText("intro")(e.target.value)} maxLength={200} />
          {tag("intro")}
        </Row>
        <Row label={<label htmlFor="p1-mechanism">裡面有什麼、怎麼作用</label>}>
          <textarea id="p1-mechanism" rows={2} className={AREA} value={texts.mechanism} onChange={(e) => setText("mechanism")(e.target.value)} maxLength={500} />
          {tag("mechanism")}
        </Row>
        <Row label={<label htmlFor="p1-difference">跟別人不一樣的地方</label>}>
          <Input id="p1-difference" className={IN} value={texts.difference} onChange={(e) => setText("difference")(e.target.value)} maxLength={200} />
          {tag("difference")}
          <CustomEscape
            brandId={brandId}
            block="difference"
            placeholder="例如：我們是台灣自己的工廠做的，一批一批驗"
            propose={(text) => proposeProductCustom(brandId, productId, "difference", text)}
            onValue={(value) => {
              setText("difference")(value);
              setCustomDifference(value);
            }}
          />
        </Row>
      </section>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <OnboardingBar back={back}>
        <NextButton disabled={!ready} reason={saving ? null : nextBlocked(name, uploading)} />
      </OnboardingBar>
    </form>
  );
}

/** The crumb of a product not created yet: its typed name, if any, after 「商品建檔」. */
function productCrumb(nav: StepNav, name: string) {
  const trimmed = name.trim();
  return trimmed ? [...nav.crumb, { label: trimmed }] : nav.crumb;
}

function NameRow({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Row label={<label htmlFor="p1-name">商品名稱</label>}>
      <Input id="p1-name" className={IN} value={value} onChange={(e) => onChange(e.target.value)} required />
    </Row>
  );
}

function UrlRow({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Row label={<label htmlFor="p1-url">商品頁網址</label>} note="也是廣告預設的落地頁">
      <Input id="p1-url" type="text" inputMode="url" className={IN} value={value} onChange={(e) => onChange(e.target.value)} placeholder="https://" />
    </Row>
  );
}

/** Prototype `.q`: label column (bold + one small note) and the field. */
function Row({ label, note, children }: { label: ReactNode; note?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 border-t border-border py-3.5 first:border-t-0 first:pt-0 last:pb-0 max-[760px]:grid-cols-1">
      <div>
        <b className="block text-sm font-semibold">{label}</b>
        {note && <span className="mt-0.5 block text-xs text-muted-foreground">{note}</span>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Prototype `th(…, 64)`: a product photo thumbnail. */
function Thumb({ url }: { url: string }) {
  const { src } = useAuthedImage(url);
  return src
    ? <img src={src} alt="" className="size-16 rounded-lg object-cover" />
    : <span className="size-16 rounded-lg bg-muted" aria-hidden="true" />;
}
