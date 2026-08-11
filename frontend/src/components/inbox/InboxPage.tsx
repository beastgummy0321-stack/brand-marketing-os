import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { resolveAlert } from "@/lib/api";
import { fetchInbox, type InboxData } from "@/lib/inboxApi";
import { usePagination } from "@/lib/usePagination";
import { InboxItemCard } from "./InboxItemCard";
import { PrototypePhasePanel } from "./PrototypePhasePanel";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: InboxData };

/** 收件匣（S2，票 B1-inbox）：全站跨品牌待辦清單，合併舊 inbox.html／prototype_phase.html
 * （側板化）。「知道了」沿用既有全站打斷佇列 resolve 端點（見 `lib/api.ts` resolveAlert
 * 註解），成功後整頁重讀一次（同 AlertsPanel／CockpitPage 既有慣例）。待辦／已結兩段各自
 * 超過 12 筆分頁（互動鐵則⑥）。 */
export function InboxPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [panelOpen, setPanelOpen] = useState(false);
  const openItems = state.status === "ready" ? state.data.open : [];
  const doneItems = state.status === "ready" ? state.data.done : [];
  const openPage = usePagination(openItems);
  const donePage = usePagination(doneItems);

  function load() {
    setState({ status: "loading" });
    fetchInbox()
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, []);

  function handleResolve(id: string) {
    setErrors((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setResolvingId(id);
    resolveAlert(id)
      .then(() => {
        setResolvingId(null);
        load();
      })
      .catch((err: unknown) => {
        setResolvingId(null);
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof Error ? err.message : "「知道了」失敗，請稍後再試。",
        }));
      });
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-5 w-24" />
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={`open-${i}`} className="h-20" />
          ))}
        </div>
        <div className="flex flex-col gap-3">
          <Skeleton className="h-5 w-24" />
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={`done-${i}`} className="h-20" />
          ))}
        </div>
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        onAction={load}
        actionLabel="重新載入"
      />
    );
  } else {
    const { data } = state;
    content = (
      <div className="flex flex-col gap-6">
        <section ref={openPage.topRef} className="flex flex-col gap-3">
          <h2 className="font-display text-base text-foreground">待辦（{data.open.length}）</h2>
          {data.open.length === 0 ? (
            <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              目前沒有待處理的事項。系統會在需要你注意時把事情送進這裡。
            </p>
          ) : (
            <>
              <ul className="flex flex-col gap-2">
                {openPage.pageItems.map((item) => (
                  <InboxItemCard
                    key={item.id}
                    item={item}
                    variant="open"
                    resolving={resolvingId === item.id}
                    error={errors[item.id]}
                    onResolve={handleResolve}
                    onOpenPrototypePanel={() => setPanelOpen(true)}
                  />
                ))}
              </ul>
              <Pager
                page={openPage.page}
                pageCount={openPage.pageCount}
                totalCount={openPage.totalCount}
                onChange={openPage.goToPage}
              />
            </>
          )}
        </section>

        <details className="flex flex-col gap-3">
          <summary className="cursor-pointer font-display text-base text-foreground">
            已結（{data.done.length}）
          </summary>
          <div ref={donePage.topRef} className="mt-3 flex flex-col gap-3">
            {data.done.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                目前沒有已結案的項目。
              </p>
            ) : (
              <>
                <ul className="flex flex-col gap-2">
                  {donePage.pageItems.map((item) => (
                    <InboxItemCard
                      key={item.id}
                      item={item}
                      variant="done"
                      onOpenPrototypePanel={() => setPanelOpen(true)}
                    />
                  ))}
                </ul>
                <Pager
                  page={donePage.page}
                  pageCount={donePage.pageCount}
                  totalCount={donePage.totalCount}
                  onChange={donePage.goToPage}
                />
              </>
            )}
          </div>
        </details>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "收件匣" }]} />
      <h1 className="font-display text-2xl text-foreground">收件匣</h1>
      {content}
      {panelOpen && <PrototypePhasePanel onClose={() => setPanelOpen(false)} />}
    </div>
  );
}
