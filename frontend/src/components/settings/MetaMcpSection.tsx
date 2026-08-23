import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { MetaMcpSettingsData } from "@/lib/settingsApi";
import { fetchMetaMcpStatus, saveMetaMcpPage } from "@/lib/settingsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: MetaMcpSettingsData };

/** 「連接 Meta 廣告帳戶」卡（票 M1-01，ADR 0023）：一鍵建廣告用的官方 Ads MCP 連線狀態＋
 * 粉絲專頁選擇。跟上面既有唯讀 `MetaSection`（成效回讀用的唯讀金鑰）是完全獨立的一組憑證，
 * 各自一張卡。金鑰（`META_MCP_TOKEN`／`META_AD_ACCOUNT_ID`）本身寫在 `.env`，本卡不接受
 * 貼金鑰——OAuth／貼權杖流程本票不做（見 `app/ads/meta_mcp.py` 檔頭），單機單人手動改
 * `.env` 即可。 */
export function MetaMcpSection() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [pageId, setPageId] = useState("");

  function load() {
    setState({ status: "loading" });
    fetchMetaMcpStatus()
      .then((data) => {
        setState({ status: "ready", data });
        setPageId(data.selected_page_id ?? "");
      })
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, []);

  const { saving, error, submit } = useFormSubmit(async () => {
    await saveMetaMcpPage(pageId);
    load();
  });

  return (
    <SectionCard
      title="連接 Meta 廣告帳戶"
      description="金鑰放在 .env 的 META_MCP_TOKEN 與 META_AD_ACCOUNT_ID，這裡看不到也改不了，只能看連線狀態、選粉絲專頁。"
    >
      {state.status === "loading" && <Skeleton className="h-24" />}
      {state.status === "error" && (
        <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
      )}
      {state.status === "ready" && (
        <>
          {state.data.ok ? (
            <p className="text-sm text-foreground">
              已連接：<span className="font-mono">{state.data.account_id}</span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">{state.data.reason}</p>
          )}
          {state.data.ok && (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-foreground">用哪個粉絲專頁發廣告</span>
                {state.data.pages_error ? (
                  <p className="text-sm text-danger">{state.data.pages_error}</p>
                ) : (
                  <select
                    value={pageId}
                    onChange={(e) => setPageId(e.target.value)}
                    disabled={saving}
                    className="w-full max-w-sm rounded-md border border-border px-3 py-2 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <option value="">請選擇粉絲專頁</option>
                    {(state.data.pages ?? []).map((p) => (
                      <option key={p.page_id} value={p.page_id}>
                        {p.page_name}
                      </option>
                    ))}
                  </select>
                )}
              </label>
              {error && <p className="text-sm text-danger">{error}</p>}
              <div>
                <SaveButton saving={saving} label="儲存粉絲專頁" />
              </div>
            </form>
          )}
          <div className="border-t border-border pt-3">
            <button
              type="button"
              onClick={load}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
            >
              重新檢查
            </button>
          </div>
        </>
      )}
    </SectionCard>
  );
}
