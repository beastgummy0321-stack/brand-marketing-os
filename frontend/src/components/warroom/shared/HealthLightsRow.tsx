import { StatusLight, type StatusLightValue } from "@/components/layout/StatusLight";
import type { HealthLights } from "@/lib/warroomApi";

const KEYS: (keyof HealthLights)[] = ["spend_rate", "cpa", "roas", "fatigue"];

/** S8R.20：成效區健康燈號——四顆大燈號全綠收合成一行「這期看起來一切正常」；任一顆非綠色，
 * 那顆燈維持展開＋一句白話說明。
 *
 * 跳過了什麼：S8R.21「點異常那顆燈，展開對應的既有趨勢圖／AI 建議完整卡」——本頁下方本來
 * 就完整顯示 KPI 表格與判讀結論卡（S8R.22 漸進揭露不變），這裡不重複做一次燈號→卡片的
 * 捲動連動，避免同一份資料兩套互動路徑。 */
export function HealthLightsRow({ lights }: { lights: HealthLights }) {
  const entries = KEYS.map((key) => ({ key, light: lights[key] }));
  const allGreen = entries.every((e) => e.light.status === "green");

  if (allGreen) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 text-sm font-medium text-success shadow-[var(--shadow-card)]">
        這期看起來一切正常
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)] sm:grid-cols-4">
      {entries.map(({ key, light }) => (
        <div key={key} className="flex flex-col gap-1">
          <StatusLight status={light.status as StatusLightValue} label={light.label} />
          {light.status !== "green" && <p className="text-xs text-muted-foreground">{light.note}</p>}
        </div>
      ))}
    </div>
  );
}
