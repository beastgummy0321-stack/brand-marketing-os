import { brandDraftKey, clearStepDraft, readStepDraft, useStepDraft } from "../shared/stepDraft";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { submitIntakeStart, uploadIntakePhoto } from "@/lib/intakeApi";
import type { AdvertisingHistory, BrandPhoto, BrandPhotoKind } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingBasics, saveOnboardingBasics } from "@/lib/intakeOnboardingApi";
import { MARKET_REGIONS, setAdvertisingHistory } from "@/lib/libraryApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { cn } from "@/lib/utils";
import { brandCrumb, OnboardingBar, OnboardingStepHead, type StepNav } from "../OnboardingStepHead";

const MAX_URLS = 5;
const PHOTO_ACCEPT = ".jpg,.jpeg,.png,.webp";
/** Prototype `#/b1` photo slots, in order (kinds of `app/intake/onboarding.py` BRAND_PHOTO_KINDS). */
const PHOTO_SLOTS: [BrandPhotoKind, string][] = [
  ["logo", "LOGO"],
  ["store", "門市／工作室"],
  ["team", "團隊／創辦人"],
  ["brand_image", "品牌形象"],
  ["other", "其他"],
];

/** Unsaved text and choices; photos and upload tokens are excluded. */
interface KeptText {
  brandName: string;
  clientName: string;
  description: string;
  urls: string[];
  pastAds: AdvertisingHistory | null;
  marketRegion: string;
  foodRegime: boolean;
}

function isKeptText(value: unknown): value is KeptText {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.marketRegion === "string" && typeof v.foodRegime === "boolean"
    && [v.brandName, v.clientName, v.description].every((x) => typeof x === "string")
    && Array.isArray(v.urls) && v.urls.every((u) => typeof u === "string")
    && (v.pastAds === null || v.pastAds === "has_history" || v.pastAds === "none");
}

function filledUrls(urls: string[]): string[] {
  return urls.map((u) => u.trim()).filter(Boolean);
}

/** At least one input; kept/saved URLs each get theirs (≤ 5). */
function urlInputs(urls: string[]): string[] {
  const filled = filledUrls(urls).slice(0, MAX_URLS);
  return filled.length ? filled : [""];
}

interface Upload {
  token: string;
  preview: string;
}

/** Brand onboarding `#/b1` 基本 (prototype `R.b1`). `brandId === null` creates the brand (the
 * multipart create of `intakeApi.ts`); a brand that exists edits the same fields through
 * `PUT …/onboarding/basics`. 「投過網路廣告嗎」 is required and keeps the existing history field. */
export function StartStep({
  brandId,
  nav,
  onSaved,
}: {
  brandId: string | null;
  nav: StepNav;
  onSaved: (result: { brand_id: string }) => void | Promise<void>;
}) {
  const isNew = brandId === null;
  const { scope } = useWorkspace();
  const keptKey = brandDraftKey(scope, brandId ?? "new", "start");
  const [kept] = useState(() => readStepDraft(keptKey, isKeptText));

  const [loaded, setLoaded] = useState(isNew);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saved, setSaved] = useState<KeptText | null>(null);

  const [brandName, setBrandName] = useState(kept?.brandName ?? "");
  const [clientName, setClientName] = useState(kept?.clientName ?? "");
  const [description, setDescription] = useState(kept?.description ?? "");
  const [urls, setUrls] = useState<string[]>(urlInputs(kept?.urls ?? []));
  const [pastAds, setPastAds] = useState<AdvertisingHistory | null>(kept?.pastAds ?? null);
  const [marketRegion, setMarketRegion] = useState(kept?.marketRegion ?? MARKET_REGIONS[0][0]);
  const [foodRegime, setFoodRegime] = useState(kept?.foodRegime ?? false);

  const [existing, setExisting] = useState<BrandPhoto[]>([]);
  const [uploads, setUploads] = useState<Partial<Record<BrandPhotoKind, Upload>>>({});
  const [uploadingKind, setUploadingKind] = useState<BrandPhotoKind | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  /** The brand this form already created, when a later call of the same submit failed. */
  const createdId = useRef<string | null>(null);

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    fetchOnboardingBasics(brandId)
      .then((b) => {
        if (cancelled) return;
        const server: KeptText = { brandName: b.name, clientName: b.client_name, description: b.description, urls: b.urls, pastAds: b.advertising_history, marketRegion: b.market_region ?? MARKET_REGIONS[0][0], foodRegime: b.regulatory_regime === "food_tw" };
        const text = kept ?? server;
        setSaved(server);
        setBrandName(text.brandName);
        setClientName(text.clientName);
        setDescription(text.description);
        setUrls(urlInputs(text.urls));
        setPastAds(text.pastAds);
        setMarketRegion(text.marketRegion);
        setFoodRegime(text.foodRegime);
        setExisting(b.photos);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      });
    return () => {
      cancelled = true;
    };
  }, [isNew, brandId, kept]);

  useStepDraft(keptKey, loaded, { brandName, clientName, description, urls, pastAds, marketRegion, foodRegime },
    saved ?? { brandName: "", clientName: "", description: "", urls: [""], pastAds: null, marketRegion: MARKET_REGIONS[0][0], foodRegime: false });

  const uploadsRef = useRef(uploads);
  uploadsRef.current = uploads;
  useEffect(() => () => Object.values(uploadsRef.current).forEach((u) => u && URL.revokeObjectURL(u.preview)), []);

  /** The existing photo a slot shows (the first of its kind); a new upload replaces it. */
  const shownExisting = (kind: BrandPhotoKind) => existing.find((p) => p.kind === kind) ?? null;

  async function handlePhoto(kind: BrandPhotoKind, file: File | undefined) {
    if (!file) return;
    setPhotoError(null);
    setUploadingKind(kind);
    try {
      const uploaded = await uploadIntakePhoto(file);
      const preview = URL.createObjectURL(file);
      setUploads((prev) => {
        const old = prev[kind];
        if (old) URL.revokeObjectURL(old.preview);
        return { ...prev, [kind]: { token: uploaded.token, preview } };
      });
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : "上傳失敗，請稍後再試。");
    } finally {
      setUploadingKind(null);
    }
  }

  const newKinds = PHOTO_SLOTS.map(([kind]) => kind).filter((kind) => uploads[kind]);
  const hasScanInput = filledUrls(urls).length > 0 || existing.length > 0 || newKinds.length > 0;
  const ready = !!brandName.trim() && !!pastAds && loaded && uploadingKind === null;
  const blocked = blockedReason({ loaded, uploading: uploadingKind !== null, brandName, pastAds });

  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    if (!brandName.trim()) throw new Error("請填寫品牌名稱。");
    if (!pastAds) throw new Error("請選擇是否曾經投放過網路廣告。");
    const photo_tokens = newKinds.map((kind) => uploads[kind]!.token);
    const photo_kinds = newKinds;
    const regulatory_regime = foodRegime ? "food_tw" : null;
    if (isNew) {
      if (createdId.current === null) {
        const res = await submitIntakeStart({
          brand_name: brandName.trim(),
          client_name: clientName.trim(),
          description: description.trim(),
          urls: filledUrls(urls),
          photo_tokens,
          photo_kinds,
          market_region: marketRegion,
          regulatory_regime: regulatory_regime ?? "",
        });
        createdId.current = res.brand_id;
      }
      await setAdvertisingHistory(createdId.current, pastAds);
      clearStepDraft(keptKey);
      await onSaved({ brand_id: createdId.current });
      return;
    }
    const replaced = new Set(newKinds.map((kind) => shownExisting(kind)?.id).filter(Boolean));
    await saveOnboardingBasics(brandId, {
      name: brandName.trim(),
      urls: filledUrls(urls),
      market_region: marketRegion,
      regulatory_regime,
      advertising_history: pastAds,
      client_name: clientName.trim(),
      description: description.trim(),
      photo_ids: existing.filter((p) => !replaced.has(p.id)).map((p) => p.id),
      photo_tokens,
      photo_kinds,
    });
    clearStepDraft(keptKey);
    await onSaved({ brand_id: brandId });
  });

  const head = <OnboardingStepHead {...nav} crumb={isNew ? brandCrumb(brandName) : nav.crumb} title="建立品牌" purpose="先給網站和產品照，後面每一步系統會先幫你填好" />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
      </div>
    );
  }

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !saving) void submit();
      }}
    >
      {head}
      <section className="rounded-xl border border-border bg-card px-[22px] py-5">
        <Row label={<label htmlFor="b1-name">品牌名稱</label>}>
          <Input id="b1-name" className={IN} value={brandName} onChange={(e) => setBrandName(e.target.value)} required disabled={!loaded} />
        </Row>
        <Row label="品牌網站" note="官網、購物頁都可以，最多 5 個">
          <div className="flex flex-col gap-2">
            {urls.map((u, i) => (
              <Input
                key={i}
                type="text"
                inputMode="url"
                aria-label={`品牌網站 ${i + 1}`}
                className={IN}
                value={u}
                onChange={(e) => setUrls((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))}
                placeholder="https://"
                disabled={!loaded}
              />
            ))}
            {urls.length < MAX_URLS && (
              <Button type="button" variant="link" className="h-auto self-start p-0 text-[13px]" onClick={() => setUrls((prev) => [...prev, ""])}>
                ＋再加一個
              </Button>
            )}
          </div>
        </Row>
        <Row label="品牌照片" note="LOGO、門市、團隊、品牌形象；商品照在商品建檔再給">
          <div className="flex flex-wrap items-start gap-3.5">
            {PHOTO_SLOTS.map(([kind, label]) => (
              <PhotoSlot
                key={kind}
                label={label}
                preview={uploads[kind]?.preview ?? null}
                photoUrl={shownExisting(kind)?.url ?? null}
                uploading={uploadingKind === kind}
                busy={!loaded || uploadingKind !== null}
                onFile={(file) => void handlePhoto(kind, file)}
              />
            ))}
          </div>
          {photoError && <p role="alert" className="mt-2 text-xs text-danger">{photoError}</p>}
        </Row>
        <Row label={<label htmlFor="b1-region">投放地區</label>}>
          <select id="b1-region" className={cn(IN, "max-w-[220px]")} value={marketRegion} onChange={(e) => setMarketRegion(e.target.value)} disabled={!loaded}>
            {MARKET_REGIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </Row>
        <Row label="適用法規" note="勾了，文案會提醒哪些話不能講">
          <label className="flex w-fit cursor-pointer items-center gap-2">
            <input type="checkbox" checked={foodRegime} onChange={(e) => setFoodRegime(e.target.checked)} disabled={!loaded} />
            台灣食品（食安法）
          </label>
        </Row>
        <Row label="投過網路廣告嗎">
          <div data-slot="segmented" role="radiogroup" aria-label="投過網路廣告嗎" className="inline-flex w-fit overflow-hidden rounded-lg border border-border">
            {([["has_history", "投過"], ["none", "完全沒投過"]] as const).map(([value, label]) => (
              <Button
                key={value}
                type="button"
                role="radio"
                aria-checked={pastAds === value}
                busy={!loaded}
                onClick={() => setPastAds(value)}
                className={cn(
                  "border-l border-border px-3 py-[5px] text-[12.5px] font-medium first:border-l-0 focus-visible:relative focus-visible:z-10",
                  pastAds === value ? "bg-primary text-primary-foreground" : "bg-card hover:bg-muted",
                )}
              >
                {label}
              </Button>
            ))}
          </div>
        </Row>
      </section>

      <details className="group rounded-[10px] border border-border bg-card">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-[11px] font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="inline-block text-base leading-none transition-transform group-open:rotate-90">›</span>
          進階：所屬客戶、品牌描述
        </summary>
        <div className="grid grid-cols-2 gap-4 px-4 pb-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">所屬客戶</span>
            <Input className={IN} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="空白＝自營" disabled={!loaded} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">品牌描述</span>
            <Input className={IN} value={description} onChange={(e) => setDescription(e.target.value)} disabled={!loaded} />
          </label>
        </div>
      </details>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <OnboardingBar hint={hasScanInput ? "下一步系統讀網站，約 1 分鐘" : undefined}>
        {/* The bar's primary button (`BarNext`) plus F47-I03's disabled reason (drill-10 甲 建檔 #9). */}
        <Button type="submit" size="lg" className="font-semibold" busy={saving} disabledReason={blocked}>
          {saving ? "處理中…" : hasScanInput ? "讓系統讀網站" : "下一步"} →
        </Button>
      </OnboardingBar>
    </form>
  );
}

const IN = "h-auto w-full rounded-lg bg-card px-3 py-[9px] text-sm shadow-none";

/** F47-I03 (drill-10 甲 建檔 #9): why the main button is off, naming what is missing; `null` = ready. */
function blockedReason({ loaded, uploading, brandName, pastAds }: {
  loaded: boolean;
  uploading: boolean;
  brandName: string;
  pastAds: AdvertisingHistory | null;
}): string | null {
  if (!loaded) return "讀取中…";
  if (uploading) return "照片上傳中，傳完才能下一步";
  const missing = [!brandName.trim() && "填品牌名稱", !pastAds && "選「投過網路廣告嗎」"].filter(Boolean);
  return missing.length ? `先${missing.join("、")}` : null;
}

/** Prototype `.q`: label column (bold + one small note) and the field. */
function Row({ label, note, children }: { label: ReactNode; note?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 border-t border-border py-3.5 first:border-t-0 first:pt-0 last:pb-0">
      <div>
        <b className="block text-sm font-semibold">{label}</b>
        {note && <span className="mt-0.5 block text-xs text-muted-foreground">{note}</span>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Prototype `.phslot`: a 72px tile (the photo, or a dashed ＋) over its kind; the tile picks a file. */
function PhotoSlot({ label, preview, photoUrl, uploading, busy, onFile }: {
  label: string;
  preview: string | null;
  photoUrl: string | null;
  uploading: boolean;
  busy: boolean;
  onFile: (file: File | undefined) => void;
}) {
  return (
    <label className={cn("flex flex-col items-center gap-1 text-[11.5px] text-muted-foreground", busy ? "cursor-not-allowed" : "cursor-pointer")}>
      {preview ? (
        <img src={preview} alt={label} className="size-[72px] rounded-[10px] object-cover" />
      ) : photoUrl ? (
        <SavedPhoto url={photoUrl} label={label} />
      ) : (
        <span className="grid size-[72px] place-items-center rounded-[10px] border-[1.5px] border-dashed border-grade-thin bg-background text-xl text-muted-foreground/60">
          {uploading ? "…" : "＋"}
        </span>
      )}
      {label}
      <input
        type="file"
        accept={PHOTO_ACCEPT}
        aria-label={`上傳${label}照片`}
        className="sr-only"
        disabled={busy}
        onChange={(e) => {
          onFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
    </label>
  );
}

function SavedPhoto({ url, label }: { url: string; label: string }) {
  const { src } = useAuthedImage(url);
  return src
    ? <img src={src} alt={label} className="size-[72px] rounded-[10px] object-cover" />
    : <span className="size-[72px] rounded-[10px] bg-muted" aria-hidden="true" />;
}
