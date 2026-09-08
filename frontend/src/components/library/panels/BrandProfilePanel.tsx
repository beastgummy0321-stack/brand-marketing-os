import { useState } from "react";
import { X } from "lucide-react";
import { Link } from "react-router-dom";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  CONVERSION_GOALS,
  deleteBrand,
  MARKET_REGIONS,
  PERSONA_TYPES,
  saveBrandProfile,
  setAdvertisingHistory,
  type LibraryBrandProfile,
} from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 品牌資料側板（契約 S5.43–S5.50）：正常內容是編輯表單＋危險區；點危險區按鈕整個換成
 * 二次確認畫面（S5.49），不是彈跳視窗。`view` 就是這個「整個側板內容換掉」的開關。 */
export function BrandProfilePanel({
  brandId,
  profile,
  onClose,
  onSaved,
  onDeleted,
}: {
  brandId: string;
  profile: LibraryBrandProfile;
  onClose: () => void;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const [view, setView] = useState<"profile" | "confirm-delete">("profile");

  return (
    <SidePanel ariaLabel="品牌資料" onClose={onClose}>
      {view === "profile" ? (
        <ProfileView
          brandId={brandId}
          profile={profile}
          onClose={onClose}
          onSaved={onSaved}
          onRequestDelete={() => setView("confirm-delete")}
        />
      ) : (
        <ConfirmDeleteView
          brandId={brandId}
          profile={profile}
          onBack={() => setView("profile")}
          onDeleted={onDeleted}
        />
      )}
    </SidePanel>
  );
}

function ProfileView({
  brandId,
  profile,
  onClose,
  onSaved,
  onRequestDelete,
}: {
  brandId: string;
  profile: LibraryBrandProfile;
  onClose: () => void;
  onSaved: () => void;
  onRequestDelete: () => void;
}) {
  const [name, setName] = useState(profile.name);
  const [clientName, setClientName] = useState(profile.client_name ?? "");
  const [status, setStatus] = useState<"active" | "archived">(profile.status);
  const [persona, setPersona] = useState(""); // 只是填表捷徑，不入庫（S5.46），不必回填
  const [marketRegion, setMarketRegion] = useState(profile.market_region ?? "");
  const [conversionGoal, setConversionGoal] = useState(profile.conversion_goal ?? "");
  const [historyValue, setHistoryValue] = useState<"" | "has_history" | "none">(
    profile.advertising_history ?? "",
  );

  const form = useFormSubmit(async () => {
    await saveBrandProfile(brandId, {
      name,
      client_name: clientName,
      status,
      persona,
      market_region: marketRegion,
      conversion_goal: conversionGoal,
    });
    if (historyValue !== "" && historyValue !== profile.advertising_history) {
      await setAdvertisingHistory(brandId, historyValue);
    }
    onSaved();
  });

  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">品牌資料</h2>
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
          <span className="font-medium text-foreground">品牌名稱</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">所屬客戶（選填）</span>
          <input
            type="text"
            value={clientName}
            onChange={(e) => setClientName(e.target.value)}
            placeholder="例如「自營」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="font-medium text-foreground">這個品牌目前狀態？</legend>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="brand_status"
              className="mt-0.5"
              checked={status === "active"}
              onChange={() => setStatus("active")}
            />
            <span>
              <span className="block">使用中</span>
              <span className="text-xs text-muted-foreground">正常顯示在品牌總覽與切換器。</span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="brand_status"
              className="mt-0.5"
              checked={status === "archived"}
              onChange={() => setStatus("archived")}
            />
            <span>
              <span className="block">已封存</span>
              <span className="text-xs text-muted-foreground">
                不出現在切換器，只留在品牌總覽的「已封存品牌」清單。
              </span>
            </span>
          </label>
        </fieldset>

        <hr className="border-border" />
        <p className="text-xs text-muted-foreground">
          下面三項決定 AI 產文案時套用哪一套方法論。「你是哪一種」只是幫你快速帶出下面兩欄的建議值，本身不會存檔；
          市場地區與廣告目標才是實際存檔、影響方法論的欄位。
        </p>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">你是哪一種？（選填）</span>
          <select
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">不套用，我自己選下面兩欄</option>
            {PERSONA_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">市場地區</span>
          <select
            value={marketRegion}
            onChange={(e) => setMarketRegion(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">未設定</option>
            {MARKET_REGIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted-foreground">這一版只有台灣市場有對應的方法論內容。</span>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">廣告要讓人做什麼？</span>
          <select
            value={conversionGoal}
            onChange={(e) => setConversionGoal(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">未設定</option>
            {CONVERSION_GOALS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">以前投放過廣告嗎？</span>
          <select
            value={historyValue}
            onChange={(e) => setHistoryValue(e.target.value as "" | "has_history" | "none")}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">尚未回答</option>
            <option value="has_history">投放過廣告</option>
            <option value="none">完全沒投放過</option>
          </select>
        </label>
        {profile.advertising_history === "has_history" && (
          <Link
            to={`/brands/${encodeURIComponent(brandId)}/intake/history`}
            className="self-start text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            把過去的廣告帶進來 →
          </Link>
        )}

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="儲存品牌基本資料" />
        </div>
      </form>

      <div className="flex flex-col gap-2 rounded-md border border-danger/40 bg-danger/5 p-4">
        <h3 className="font-display text-base text-foreground">永久刪除品牌</h3>
        {profile.status === "archived" ? (
          <>
            <p className="text-sm text-muted-foreground">
              把這個品牌與底下所有資料從系統徹底移除，不能復原。下一步會列出會消失的資料，並要求你輸入品牌名稱確認。
            </p>
            <div>
              <button
                type="button"
                onClick={onRequestDelete}
                className="rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger hover:bg-danger/10"
              >
                永久刪除這個品牌…
              </button>
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            只有已封存的品牌可以永久刪除。要刪除的話，請先把上面的狀態改成「已封存」並儲存。
          </p>
        )}
      </div>
    </>
  );
}

function ConfirmDeleteView({
  brandId,
  profile,
  onBack,
  onDeleted,
}: {
  brandId: string;
  profile: LibraryBrandProfile;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const [confirmName, setConfirmName] = useState("");
  const form = useFormSubmit(async () => {
    const message = await deleteBrand(brandId, confirmName);
    window.alert(message);
    onDeleted();
  });

  return (
    <>
      <div className="border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">永久刪除品牌「{profile.name}」</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          這個動作不能復原。刪掉之後，這個品牌與底下所有資料都會從系統消失，只在稽核紀錄留下一筆「誰在什麼時候刪了什麼」。
        </p>
      </div>

      <div className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
        <p className="font-medium text-foreground">會一起消失的資料：</p>
        {profile.delete_impact.length === 0 ? (
          <p className="mt-1 text-muted-foreground">這個品牌底下目前沒有任何資料。</p>
        ) : (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
            {profile.delete_impact.map((row) => (
              <li key={row.label}>
                {row.label} {row.count} 筆
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          系統會在刪除前自動把整個資料庫備份一份到 backups 資料夾，萬一刪錯還救得回來。
        </p>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">請輸入品牌名稱以確認</span>
          <input
            type="text"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            autoComplete="off"
            placeholder={profile.name}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            要刪除的品牌是「{profile.name}」，請一字不差地打一次。
          </span>
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={form.saving}
            className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {form.saving ? "刪除中…" : "永久刪除這個品牌"}
          </button>
          <button
            type="button"
            onClick={onBack}
            disabled={form.saving}
            className="text-sm text-muted-foreground hover:underline"
          >
            取消
          </button>
        </div>
      </form>
    </>
  );
}
