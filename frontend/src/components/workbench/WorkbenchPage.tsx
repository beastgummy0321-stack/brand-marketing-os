import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import {
  fetchBrief, fetchBriefs, type BriefDetail as BriefDetailData, type BriefSummary,
} from "@/lib/workbenchApi";
import { BriefList, type BriefPart } from "./BriefList";
import { BriefDetail } from "./BriefDetail";
import { NewBriefPanel } from "./NewBriefPanel";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; briefs: BriefSummary[] };

type DetailState =
  | { status: "none" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brief: BriefDetailData };

// SchedulePage.tsx:186 用 2000ms 刷整包排程狀態；工單清單的輪詢沒那麼急，票面 §2 給 10s，
// 選中工單的細節沿用排程同一個 2s。
const POLL_LIST_MS = 10_000;
const POLL_DETAIL_MS = 2_000;

/** 素材工作檯（票 workbench/04，ADR 0068）：`.workspace-split` 左清單右詳情，跟
 * `LibraryPage.tsx` 同一個殼形狀。清單與詳情各自獨立輪詢（票面 §2）：任何一張列出的工單還
 * `queued`／`running`，就每 10 秒刷清單、每 2 秒刷選中的那張詳情；全部跑完就停。 */
export function WorkbenchPage({ brandId }: { brandId: string }) {
  const { brands } = useWorkspace();
  const brand = brands.find((b) => b.brand_id === brandId);
  const [params, setParams] = useSearchParams();
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [detailState, setDetailState] = useState<DetailState>({ status: "none" });
  const [newBriefPart, setNewBriefPart] = useState<BriefPart | null>(null);
  const listRequestId = useRef(0);
  const detailRequestId = useRef(0);

  const selectedId = params.get("brief");

  function selectBrief(id: string | null) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (id) next.set("brief", id);
      else next.delete("brief");
      return next;
    });
  }

  function startPart(part: BriefPart) {
    setNewBriefPart(part);
    selectBrief(null);
  }

  // 左欄「派工任務／工單」清單全部走 `status=all`，開／關的分界在元件內用 `closed_at`
  // 判斷（票面 §1：「全部」要含已關閉，分界不再交給後端的 status 篩選）。
  function loadList() {
    const id = ++listRequestId.current;
    setListState({ status: "loading" });
    fetchBriefs(brandId, "all")
      .then((briefs) => {
        if (id === listRequestId.current) setListState({ status: "ready", briefs });
      })
      .catch((err: unknown) => {
        if (id === listRequestId.current) {
          setListState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
  }

  // `background=true`（poll、動作後刷新）不先翻回 "loading"：SchedulePage.tsx:126 同一個
  // 慣例（`if (initial) setState({status:"loading"})`）——先翻 loading 會把 `<BriefDetail>`
  // 換成 `<Skeleton>`，那是整個元件連同它自己的 local state（例如 `deleteOpen`）一起卸載重
  // 建。walk 04 步驟 5「刪除」的根因：只要清單裡還有別的 brief 在 queued/running，
  // `anyRunning` 就恆真，2 秒一次的偵測輪詢會在使用者確認對話框開著的當下把它整個卸載。
  function loadDetail(id: string, background = false) {
    const requestId = ++detailRequestId.current;
    if (!background) setDetailState({ status: "loading" });
    fetchBrief(brandId, id)
      .then((brief) => {
        if (requestId === detailRequestId.current) setDetailState({ status: "ready", brief });
      })
      .catch((err: unknown) => {
        if (requestId === detailRequestId.current) {
          setDetailState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
  }

  useEffect(() => {
    loadList();
    // brandId 變動要重打；loadList 本身穩定（只讀閉包裡的 brandId）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  useEffect(() => {
    detailRequestId.current += 1; // 品牌或選取換了，作廢還沒回來的舊請求
    if (selectedId) loadDetail(selectedId);
    else setDetailState({ status: "none" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, selectedId]);

  function refreshAfterAction() {
    loadList();
    if (selectedId) loadDetail(selectedId, true);
  }

  const anyRunning =
    listState.status === "ready" &&
    listState.briefs.some((b) => b.status === "queued" || b.status === "running");

  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => loadList(), POLL_LIST_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyRunning, brandId]);

  useEffect(() => {
    if (!anyRunning || !selectedId) return;
    const timer = setInterval(() => loadDetail(selectedId, true), POLL_DETAIL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyRunning, selectedId, brandId]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="素材工作檯"
        description={
          (brand ? `${brand.brand_name} · ` : "") +
          "文案、圖片提示詞與腳本在這裡生成；投放時到檔期規劃複製"
        }
      />
      <div className="workspace-split">
        <BriefList
          status={listState.status}
          briefs={listState.status === "ready" ? listState.briefs : []}
          errorMessage={listState.status === "error" ? listState.message : undefined}
          selectedId={selectedId}
          onSelectBrief={selectBrief}
          onStartPart={startPart}
          activePart={newBriefPart}
          onReload={loadList}
        />
        <div className="workspace-content flex flex-col gap-4">
          {detailState.status === "none" && (
            <NewBriefPanel
              brandId={brandId}
              initialPart={newBriefPart}
              onCreated={(id) => {
                setNewBriefPart(null);
                selectBrief(id);
                loadList();
              }}
            />
          )}
          {detailState.status === "loading" && <Skeleton className="h-96" />}
          {detailState.status === "error" && (
            <EmptyState
              title="讀取失敗"
              description={detailState.message}
              onAction={() => selectedId && loadDetail(selectedId)}
              actionLabel="重新載入"
            />
          )}
          {detailState.status === "ready" && (
            <BriefDetail
              brandId={brandId}
              brief={detailState.brief}
              onChanged={refreshAfterAction}
              onDeleted={() => {
                selectBrief(null);
                loadList();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
