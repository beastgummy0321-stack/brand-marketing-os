import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Boxes,
  Calendar,
  Database,
  Megaphone,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { FieldCard, StepIndicator } from "./patterns";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import {
  generateStrategy,
  getCampaign,
  patchCampaign,
  type CampaignDetail,
  type CampaignFieldSources,
} from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";

const OBJECTIVE_OPTIONS = ["購買", "加購物車", "名單", "流量", "知名度"];

interface CampaignContext {
  product_ids?: string[];
  audience_hint?: string | null;
  field_sources?: CampaignFieldSources;
}

interface CampaignConstraints {
  platform?: string | null;
  budget?: number | null;
}

const DEFAULT_SOURCES: CampaignFieldSources = {
  product: "system",
  objective: "system",
  platform: "system",
  budget: "system",
  dates: "system",
  audience: "system",
};

type FieldKey = keyof CampaignFieldSources;

/** 建立 Campaign 步驟二（F04-I12，圖 4「理解如下」）：六張可改的欄位卡，改一格就 `PATCH`
 * 一格，不重新解析——第二次、也是最後一次模型呼叫在「產生策略建議」按下去那一刻，寫在
 * `handleGenerate` 旁邊，別在這一頁加第三個「幫我想想看」按鈕（ARCHITECTURE.md §6.1 第 11 條）。 */
export function ConfirmBriefPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const navigate = useNavigate();
  const location = useLocation() as { state?: { parseWarning?: string } };
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<FieldKey | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getCampaign(brandId, campaignId), fetchProductList(brandId)])
      .then(([c, p]) => {
        if (cancelled) return;
        setCampaign(c);
        setProducts(p);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "讀取資料失敗，請稍後再試。");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    // 通路清單讀失敗只讓「平台」欄位沒有下拉可選、顯示現值——不拖垮整頁（Done 5）。
    fetchChannels(brandId)
      .then((rows) => {
        if (!cancelled) setChannels(rows);
      })
      .catch(() => {
        /* 靜默：channels 維持空陣列，平台欄位不給編輯 */
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, campaignId]);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (loadError || !campaign) {
    return <p className="text-sm text-destructive">{loadError ?? "找不到這個 Campaign。"}</p>;
  }

  const context = (campaign.context_json ?? {}) as CampaignContext;
  const constraints = (campaign.constraints_json ?? {}) as CampaignConstraints;
  const sources = context.field_sources ?? DEFAULT_SOURCES;
  const productIds = context.product_ids ?? [];
  const audienceHint = context.audience_hint ?? "";

  async function save(patch: Parameters<typeof patchCampaign>[2]) {
    setSaveError(null);
    try {
      const updated = await patchCampaign(brandId, campaignId, patch);
      setCampaign(updated);
      setEditing(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await generateStrategy(brandId, campaignId);
      navigate(`/brands/${brandId}/ads/campaigns/${campaignId}?tab=strategy`);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "產生策略失敗，請稍後再試。");
      setGenerating(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Link
          to={`/brands/${brandId}/ads`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={14} /> 投放中心
        </Link>
        <StepIndicator steps={["確認需求", "產生策略", "查看結果"]} current={0} />
      </div>
      <PageHeader
        title="行銷駕駛艙理解如下"
        description="這是我們根據你的需求整理的重點內容。如果理解有誤，可直接修改。"
      />
      {location.state?.parseWarning && (
        <p className="text-sm text-warning">{location.state.parseWarning}</p>
      )}
      <div className="surface">
        <div className="surface-header">
          <div>
            <h2 className="flex items-center gap-1.5">
              <Sparkles size={15} className="text-primary" /> 你的行銷需求
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">我們已根據你的輸入，整理出以下重點。</p>
          </div>
        </div>
        <div className="surface-body grid grid-cols-1 gap-3 md:grid-cols-2">
          <FieldCard
            icon={Boxes}
            label="商品"
            value={productIds
              .map((id) => products.find((p) => p.id === id)?.name)
              .filter((name): name is string => Boolean(name))
              .join("、")}
            emptyText="不指定"
            source={sources.product}
            editing={editing === "product"}
            onEdit={() => setEditing("product")}
          >
            <ProductPicker
              products={products}
              initial={productIds}
              onCancel={() => setEditing(null)}
              onSave={(ids) => save({ product_ids: ids })}
            />
          </FieldCard>
          <FieldCard
            icon={Target}
            label="目標"
            value={campaign.objective}
            emptyText="未設定"
            source={sources.objective}
            editing={editing === "objective"}
            onEdit={() => setEditing("objective")}
          >
            <SelectField
              options={OBJECTIVE_OPTIONS.map((o) => ({ key: o, label: o }))}
              initial={campaign.objective}
              onCancel={() => setEditing(null)}
              onSave={(value) => save({ objective: value })}
            />
          </FieldCard>
          <FieldCard
            icon={Megaphone}
            label="平台"
            value={channels.find((c) => c.key === constraints.platform)?.label ?? constraints.platform ?? ""}
            emptyText="尚未指定"
            source={sources.platform}
            editing={editing === "platform"}
            onEdit={channels.length > 0 ? () => setEditing("platform") : undefined}
          >
            <SelectField
              options={channels.map((c) => ({ key: c.key, label: c.label }))}
              initial={constraints.platform ?? channels[0]?.key ?? ""}
              onCancel={() => setEditing(null)}
              onSave={(value) => save({ constraints_json: { ...constraints, platform: value } })}
            />
          </FieldCard>
          <FieldCard
            icon={Database}
            label="預算"
            value={constraints.budget ? `約 NT$${Math.round(constraints.budget).toLocaleString("zh-TW")}` : ""}
            emptyText="由行銷駕駛艙建議"
            source={sources.budget}
            editing={editing === "budget"}
            onEdit={() => setEditing("budget")}
          >
            <NumberField
              initial={constraints.budget ?? null}
              onCancel={() => setEditing(null)}
              onSave={(value) => save({ constraints_json: { ...constraints, budget: value } })}
            />
          </FieldCard>
          <FieldCard
            icon={Calendar}
            label="時間"
            value={campaign.start_date && campaign.end_date ? `${campaign.start_date} ~ ${campaign.end_date}` : ""}
            emptyText="未設定"
            source={sources.dates}
            editing={editing === "dates"}
            onEdit={() => setEditing("dates")}
          >
            <DateRangeField
              initialStart={campaign.start_date ?? ""}
              initialEnd={campaign.end_date ?? ""}
              onCancel={() => setEditing(null)}
              onSave={(start, end) => save({ start_date: start, end_date: end })}
            />
          </FieldCard>
          <FieldCard
            icon={Users}
            label="受眾方向"
            value={audienceHint}
            emptyText="未設定"
            source={sources.audience}
          />
        </div>
        {saveError && <p className="px-4 pb-3 text-sm text-destructive">{saveError}</p>}
      </div>
      <p className="text-center text-sm text-muted-foreground">
        確認後會依這六項需求整理策略、預算配置與素材需求；之後仍由你核准採用與上架。
      </p>
      {generateError && <p className="text-sm text-destructive">{generateError}</p>}
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild variant="outline" disabled={generating}>
          <Link to={`/brands/${brandId}/ads/campaigns/${campaignId}?tab=assets`}>先處理自帶素材與手動交接</Link>
        </Button>
        <Button onClick={handleGenerate} disabled={generating}>
          <Sparkles size={15} />
          {generating ? "產生中…" : "產生策略建議 →"}
        </Button>
        <Button variant="outline" onClick={() => navigate(`/brands/${brandId}/ads/new`)}>
          返回修改
        </Button>
      </div>
    </div>
  );
}

function SelectField({
  options,
  initial,
  onCancel,
  onSave,
}: {
  options: { key: string; label: string }[];
  initial: string;
  onCancel: () => void;
  onSave: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <div className="flex items-center gap-2">
      <select
        className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
      <Button size="sm" onClick={() => onSave(value)}>
        儲存
      </Button>
      <Button size="sm" variant="outline" onClick={onCancel}>
        取消
      </Button>
    </div>
  );
}

function NumberField({
  initial,
  onCancel,
  onSave,
}: {
  initial: number | null;
  onCancel: () => void;
  onSave: (value: number | null) => void;
}) {
  const [value, setValue] = useState(initial === null ? "" : String(initial));
  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        step={100}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="h-9 w-32"
      />
      <Button size="sm" onClick={() => onSave(value.trim() ? Number(value) : null)}>
        儲存
      </Button>
      <Button size="sm" variant="outline" onClick={onCancel}>
        取消
      </Button>
    </div>
  );
}

function DateRangeField({
  initialStart,
  initialEnd,
  onCancel,
  onSave,
}: {
  initialStart: string;
  initialEnd: string;
  onCancel: () => void;
  onSave: (start: string, end: string) => void;
}) {
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-2">
        <Input
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          className="h-9 w-full"
        />
        <Input
          type="date"
          value={end}
          onChange={(e) => setEnd(e.target.value)}
          className="h-9 w-full"
        />
      </div>
      <div className="flex w-full items-center gap-2">
        <Button size="sm" onClick={() => onSave(start, end)} disabled={!start || !end}>
          儲存
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}

function ProductPicker({
  products,
  initial,
  onCancel,
  onSave,
}: {
  products: ProductListItem[];
  initial: string[];
  onCancel: () => void;
  onSave: (ids: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  function toggle(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex max-h-32 flex-col gap-1 overflow-y-auto">
        {products.map((p) => (
          <label key={p.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} />
            {p.name}
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => onSave(selected)}>
          儲存
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}
