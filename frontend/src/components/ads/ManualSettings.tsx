import { useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { saveManualSettings, type ManualHandoff } from "@/lib/adsLaunchApi";
import { Disclosure } from "./patterns";

export function ManualSettings({ brandId, campaign, onSaved }: {
  brandId: string; campaign: Pick<CampaignDetail, "id" | "status" | "manual_handoff">; onSaved: (c: CampaignDetail) => void;
}) {
  const handoff = campaign.manual_handoff;
  if (!handoff?.groups.length) return null;
  return (
    <div className="surface">
      <div className="surface-body flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          人工上架：{handoff.pending_count ? `${handoff.pending_count} 組設定待補` : "設定已填齊，仍需到平台核對"}。
          再行銷需確認受眾池；這裡儲存設定，不會對外發布或更動預算。
        </p>
        <Disclosure label="人工上架設定與平台對應">
          <div className="flex flex-col gap-4">
            {handoff.groups.map((group) => (
              <Disclosure key={group.id} label={`${group.name} · ${group.status}`}>
                <GroupSettings key={`${group.id}:${group.saved_at ?? "new"}`} brandId={brandId}
                  campaignId={campaign.id} fields={handoff.fields} group={group}
                  locked={campaign.status === "closed"} onSaved={onSaved} />
              </Disclosure>
            ))}
          </div>
        </Disclosure>
      </div>
    </div>
  );
}

function GroupSettings({ brandId, campaignId, fields, group, locked, onSaved }: {
  brandId: string; campaignId: string; fields: ManualHandoff["fields"];
  group: ManualHandoff["groups"][number]; locked: boolean;
  onSaved: (c: CampaignDetail) => void;
}) {
  const [values, setValues] = useState(group.values);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [section, setSection] = useState("受眾");
  const dirty = JSON.stringify(values) !== JSON.stringify(group.values);
  async function save() {
    setBusy(true); setError(null); setSaved(false);
    try {
      await saveManualSettings(brandId, campaignId, group.id, values);
      onSaved(await getCampaign(brandId, campaignId));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "儲存失敗，已填內容保留在此。");
    } finally { setBusy(false); }
  }
  return (
    <div className="flex flex-col gap-3">
      {group.missing.length > 0 && <p className="text-sm text-warning">待補：{group.missing.join("、")}</p>}
      <div className="flex flex-wrap gap-2" aria-label="設定分類">
        {[...new Set(fields.map((f) => f.section))].map((name) => (
          <Button key={name} size="sm" variant={section === name ? "default" : "outline"}
            onClick={() => setSection(name)}>{name}</Button>
        ))}
      </div>
      {section === "上架紀錄" && (
        <div className="text-sm text-muted-foreground">
          <p>手動填入的 ID 尚未經平台配對驗證，不會改變同步狀態。</p>
          {group.ads.map((ad) => <p key={ad.id}>{ad.name}：<code>{ad.id}</code></p>)}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {fields.filter((f) => f.section === section).map((field) => (
          <label key={field.key} className="flex flex-col gap-1 text-sm">
            {field.label}{field.required ? " *" : ""}
            {field.key === "ad_platform_ids" || field.key === "execution_notes" ? (
              <Textarea value={values[field.key] ?? ""} maxLength={2000} disabled={busy || locked}
                onChange={(e) => { setSaved(false); setValues({ ...values, [field.key]: e.target.value }); }} />
            ) : (
              <Input value={values[field.key] ?? ""} maxLength={2000} disabled={busy || locked}
                onChange={(e) => { setSaved(false); setValues({ ...values, [field.key]: e.target.value }); }} />
            )}
          </label>
        ))}
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {(saved || group.saved_at) && <p role="status" className="text-sm text-muted-foreground">
        {dirty ? "有尚未儲存的變更" : "設定已儲存"}
      </p>}
      <Button className="w-fit" disabled={busy || locked || !dirty} onClick={() => void save()}>
        {busy ? "儲存中…" : "儲存這組設定"}
      </Button>
    </div>
  );
}
