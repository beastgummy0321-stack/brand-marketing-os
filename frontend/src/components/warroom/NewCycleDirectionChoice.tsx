import { useEffect, useState, type ReactNode } from "react";
import { fetchNewCycleDirection, type NewCycleDirection } from "@/lib/warroomApi";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; data: NewCycleDirection };

/** 開檔前的二選一；沒有可沿用的方向或讀取失敗時，不增加一道關卡，直接交回原表單。 */
export function NewCycleDirectionChoice({
  brandId,
  children,
}: {
  brandId: string;
  children: (initialBackground: string) => ReactNode;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);
  const [custom, setCustom] = useState("");

  useEffect(() => {
    fetchNewCycleDirection(brandId)
      .then((data) => setState({ status: "ready", data }))
      .catch(() => setState({ status: "ready", data: { status: "unavailable" } }));
  }, [brandId]);

  if (chosen !== null) return <>{children(chosen)}</>;
  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">載入上輪成效中…</div>;
  }
  if (state.data.status !== "ready") return <>{children("")}</>;

  // 票 F10：畫面一律顯示後端已經套過誠實門檻、組好的 label（不再自己拼 direction 字串），
  // 沒有誠實贏家時 label 是「沿用上期設定」，不會帶內部代號。
  const { direction, label } = state.data;
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">這次檔期想怎麼打？</h2>
        <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      </div>
      <button type="button" onClick={() => setChosen(`沿用有效方向：${direction ?? ""}`)} className="rounded-md border border-primary p-4 text-left hover:bg-primary/5">
        <p className="font-medium text-foreground">沿用有效方向</p>
        <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      </button>
      <button type="button" onClick={() => setChosen("")} className="rounded-md border border-border p-4 text-left hover:border-primary">
        <p className="font-medium text-foreground">推新品／換方向</p>
        <p className="mt-1 text-sm text-muted-foreground">從頭規劃，使用一般推薦值。</p>
      </button>
      <label className="flex flex-col gap-2 rounded-md border border-border p-4 text-sm">
        <span className="font-medium text-foreground">都不是，我自己說</span>
        <textarea value={custom} onChange={(event) => setCustom(event.target.value)} rows={3} className="rounded-md border border-border px-3 py-2 text-foreground" />
        <button type="button" disabled={!custom.trim()} onClick={() => setChosen(custom.trim())} className="self-start rounded-md border border-primary px-3 py-1.5 font-medium text-primary disabled:cursor-not-allowed disabled:opacity-50">
          用這個方向開檔
        </button>
      </label>
    </section>
  );
}
