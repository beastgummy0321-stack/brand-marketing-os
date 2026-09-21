import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageHeader } from "@/components/layout/PageHeader";
import { Chip } from "../patterns";
import { ConnectionCard, type ConnectionState } from "./ConnectionCard";

/** 資料連線頁（F21-I02，v7 原型 `connections()`）：投放中心倚賴的五個資料來源各一張卡
 * （Meta 帳戶／預算金額、商城訂單、商品售價成本、過去的廣告紀錄）＋一張灰色未支援平台
 * 佔位卡。原型自己的假資料先照抄一次（issue Done #2 靜態畫面），下一步才接上真的 API。 */
const SAMPLE_CARDS: { icon: string; title: string; state: ConnectionState }[] = [
  {
    icon: "∞",
    title: "Meta 廣告帳戶",
    state: {
      status: "ready",
      tone: "warn",
      badge: "1 個帳戶權限失效",
      fact: "2 個帳戶・最近讀取 09/19 22:40",
      impacts: ["中秋限定活動 無法判斷"],
      buttonLabel: "重新授權",
      buttonHref: "/settings?tab=meta",
    },
  },
  {
    icon: "💱",
    title: "Meta 預算金額",
    state: {
      status: "ready",
      tone: "warn",
      badge: "預算待核實",
      fact: "幣別與單位尚未核實",
      impacts: ["加預算提議", "約撐得起幾則"],
      buttonLabel: "去核實",
      buttonHref: "/settings?tab=meta",
    },
  },
  {
    icon: "🧾",
    title: "商城訂單報表",
    state: {
      status: "ready",
      tone: "warn",
      badge: "缺 9/13 之後",
      fact: "最新到 9/12",
      impacts: ["檢討頁的訂單對照"],
      buttonLabel: "補報表",
      buttonHref: "/settings?tab=meta",
    },
  },
  {
    icon: "🏷",
    title: "商品售價與成本",
    state: {
      status: "ready",
      tone: "ok",
      badge: "可算打平值",
      fact: "3 個商品，2 個有成本",
      impacts: ["目標購買成本"],
      buttonLabel: "補成本",
      buttonHref: "/settings?tab=meta",
    },
  },
  {
    icon: "🗂",
    title: "過去的廣告紀錄",
    state: {
      status: "ready",
      tone: "ok",
      badge: "完成",
      fact: "已帶入 37 個月",
      impacts: [],
      buttonLabel: "查看",
      buttonHref: "/settings?tab=meta",
    },
  },
];

export function DataConnectionsPage({ brandId }: { brandId: string }) {
  const homeHref = `/brands/${brandId}/ads`;
  const need = SAMPLE_CARDS.filter((c) => c.state.status === "ready" && c.state.tone === "warn").length;

  return (
    <div className="flex max-w-[1180px] flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料連線" }]} />
      <PageHeader
        title="資料連線"
        description={`${need} 項需要處理`}
        actions={<Chip tone="ok">🔒 只讀取，不會修改你的廣告</Chip>}
      />
      <div className="grid grid-cols-1 gap-4 min-[1101px]:grid-cols-2">
        {SAMPLE_CARDS.map((card) => (
          <ConnectionCard key={card.title} icon={card.icon} title={card.title} state={card.state} />
        ))}
        <div className="surface flex items-center gap-4 p-5 opacity-55" data-testid="connection-card-unsupported">
          <div
            className="grid size-[52px] shrink-0 place-items-center rounded-[14px] bg-muted text-2xl"
            aria-hidden="true"
          >
            G
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <b className="text-[15px]">Google Ads</b>
              <Chip>尚未支援</Chip>
            </div>
            <p className="mt-0.5 text-[13px] text-muted-foreground">接上後開放</p>
          </div>
        </div>
      </div>
    </div>
  );
}
