"""app/schedule/onboarding_slice.py — 票 S2「開帳讀歷史」提示詞 segment [4] 的組裝：
把一個活動的結構、素材、期間總計、逐日成效轉成要送進提示詞的文字。

**從 app/schedule/onboarding.py 機械式搬出來的（票 S2b 步驟 0，2026-08-31）**：
`onboarding.py` 當時 768 行、`FILE_LINE_CAP` 是 800（app/tests/test_architecture_boundaries.py），
只剩 32 行餘裕，而 S2b 的 A1～A4 與 B1 全部改的就是這一族函式。先拆再加，不是拆完順手改——
這一份跟搬出來之前逐行相同，只有函式名去掉開頭底線（它們現在是跨檔的接口，底線原本的意思
是「這一檔私有」，那件事已經不成立了）。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/onboarding.py import 這裡。

裡面六支是純函式（拿資料回文字，不碰連線、不打網路）；`entity_totals()` 是唯一的例外，
它拿 `conn` 去重用 `app.meta.repository.spend_summary()`，因為 `totals_text()` 要的數字就是
那支算的（D7：不寫第二套聚合）。它跟其他六支放在一起，是因為它們合起來才是「這個活動的
segment [4]」，拆開會讓 S2b 之後每一次改動都要同時開兩個檔。
"""

import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal

from app.meta import repository as meta_repo


def structure_text(
    campaign: dict, adsets: list, ads: list, creatives_by_ad: dict,
) -> tuple[str, list]:
    """D8 segment [4]-1：這個活動的結構與素材。欄位一律用 Meta 自己的名字（D5：不重新
    命名成「主文案／標題」），`targeting` 原始形狀直接往下傳，不拆欄位。

    回不出素材的廣告列在同一段文字裡的「Meta 現在回不出這一則的素材」，同時回傳
    `unreadable`（供呼叫端存進 context_scope_json 給 GET 用）——絕不整筆消失（票 S2 §1）。
    """
    body = {
        "campaign": {
            "id": campaign["id"], "name": campaign["name"],
            "effective_status": campaign["effective_status"],
        },
        "adsets": [
            {
                "id": adset["id"], "name": adset.get("name", ""),
                "effective_status": adset.get("effective_status", ""),
                "targeting": adset.get("targeting"),
                "optimization_goal": adset.get("optimization_goal"),
                "billing_event": adset.get("billing_event"),
            }
            for adset in adsets
        ],
        "ads": [],
    }
    unreadable = []
    for ad in ads:
        creatives = creatives_by_ad.get(ad["id"], [])
        if not creatives:
            unreadable.append({"ad_id": ad["id"], "name": ad.get("name", "")})
        body["ads"].append({
            "id": ad["id"], "name": ad.get("name", ""),
            "effective_status": ad.get("effective_status", ""),
            "creatives": creatives,
        })
    text = "## 這個活動的結構與素材\n" + json.dumps(body, ensure_ascii=False, indent=2)
    if unreadable:
        names = "、".join(f"{u['name']}（{u['ad_id']}）" for u in unreadable)
        text += f"\n\nMeta 現在回不出這一則的素材：{names}"
    return text, unreadable


def entity_totals(
    conn, org_id: str, account_ids: list, since: date, until: date, conversion_goal: str | None,
    campaign_id: str, adset_ids: list, ad_ids: list,
) -> dict:
    """D7：重用既有 `spend_summary()` 算 CTR／CPC／CPM／ROAS／CPA，不寫第二套聚合。
    `spend_summary()` 一次回的是整個帳號那一層全部實體，這裡只在 Python 這層篩成這個活動
    自己的那幾個 entity_id——代價是查詢範圍比真正要的寬，帳號規模小（設計裡點名的量級）
    這個代價可忽略。`until_exclusive`：`spend_summary()` 是半開區間，跟 D6 讀進來的
    頭尾都含窗口要在這裡轉一次。"""
    until_exclusive = until + timedelta(days=1)
    campaign_summary = meta_repo.spend_summary(
        conn, org_id, account_ids, since, until_exclusive,
        level="campaign", conversion_goal=conversion_goal,
    )
    adset_summary = meta_repo.spend_summary(
        conn, org_id, account_ids, since, until_exclusive,
        level="adset", conversion_goal=conversion_goal,
    )
    ad_summary = meta_repo.spend_summary(
        conn, org_id, account_ids, since, until_exclusive,
        level="ad", conversion_goal=conversion_goal,
    )
    adset_id_set, ad_id_set = set(adset_ids), set(ad_ids)
    return {
        "campaign": [e for e in campaign_summary["entities"] if e["entity_id"] == campaign_id],
        "adset": [e for e in adset_summary["entities"] if e["entity_id"] in adset_id_set],
        "ad": [e for e in ad_summary["entities"] if e["entity_id"] in ad_id_set],
    }


def totals_text(totals: dict, action_totals: list) -> str:
    """D8 segment [4]-2：期間總計，外殼算好的——票 S2 存在的理由之一就是手跑那次的唯一
    錯誤是這種加總（八天 view_content 手動加成 344，正確是 342），交給外殼算，不要模型
    口算。"""
    actions_by_entity: dict[tuple, list] = {}
    for row in action_totals:
        actions_by_entity.setdefault((row["level"], row["entity_id"]), []).append(row)

    lines = ["## 期間總計（外殼算好的）"]
    for level in meta_repo.LEVELS:
        for entity in totals.get(level, []):
            lines.append(f"- [{level}] {entity['entity_name']}（{entity['entity_id']}）")
            lines.append(
                f"  花費 {entity['spend']}／曝光 {entity['impressions']}／點擊 {entity['clicks']}／"
                f"CTR {entity['ctr']}／CPC {entity['cpc']}／CPM {entity['cpm']}／"
                f"ROAS {entity['roas']}／CPA {entity['cpa']}"
            )
            entity_actions = actions_by_entity.get((level, entity["entity_id"]), [])
            if entity_actions:
                action_text = "、".join(f"{a['action_type']}={a['total']}" for a in entity_actions)
                lines.append(f"  actions 加總：{action_text}")
    return "\n".join(lines)


def csv_cell(value):
    """CSV 是純文字格式：Decimal／date／dict／list 都要先轉字串——json.dumps 處理
    `actions`／`action_values`（D8：CSV 化只改形狀，不摘要、不改內容）。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def action_columns(rows: list[dict]) -> tuple[list[str], list[str]]:
    """這一片實際出現過的 `actions`／`action_values` 種類（各自排序、去重）。

    只收這一片真的有的種類，不是整個帳號的全部：2026-08-31 對真帳號實測，整個帳號有 77 種
    action_type，但單一活動用得到的遠少於此——欄位表照全帳號展開會讓每一列多背幾十個永遠
    空著的欄位。"""
    action_types: set[str] = set()
    value_types: set[str] = set()
    for row in rows:
        for entry in row.get("actions") or ():
            if isinstance(entry, dict) and entry.get("action_type"):
                action_types.add(entry["action_type"])
        for entry in row.get("action_values") or ():
            if isinstance(entry, dict) and entry.get("action_type"):
                value_types.add(entry["action_type"])
    return sorted(action_types), sorted(value_types)


def action_cells(entries, prefix: str, types: list[str]) -> dict:
    """一列的 `actions`（或 `action_values`）→ `{prefix}{action_type}` 欄位。

    **沒回報的種類留空白，不是 0。** 這是 `meta_entity_spend` 那條 null≠0 規矩在 CSV 這一層
    的樣子：Meta 那天沒有回報這個事件，跟那天這個事件真的是 0 次，是兩件不同的事，而
    分辨這兩件事正是這份判讀最需要的能力（GRILL 決定1(d)）。"""
    by_type = {
        entry["action_type"]: entry.get("value")
        for entry in (entries or ())
        if isinstance(entry, dict) and entry.get("action_type")
    }
    return {f"{prefix}{t}": by_type.get(t, "") for t in types}


def daily_csv(rows: list[dict]) -> str:
    """D8 segment [4]-3：逐日成效，CSV 一次全部給，絕不摘要（票 S2 §2「summarising nodes
    away is forbidden」）。空清單（這個活動這段窗口一列資料都沒有）回空字串，不硬造一份
    只有表頭的 CSV。

    `actions`／`action_values` **攤平成欄位**，不是每一列塞一段原始 JSON。2026-08-31 實機
    驗收量到的：一個 722 列的活動，原本的寫法組出 2,735,699 字元（平均一列 3,790 字元），
    整份提示詞 2.1 MB，超過本機 codex CLI 的 1,048,576 字元輸入上限而整批失敗——那個活動
    因此一個字都讀不到。撐爆它的不是素材（97 KB）也不是總計（35 KB），是每一列都重複一次
    `{"action_type": ..., "value": ...}` 這組鍵名。

    攤平**只改形狀、不改內容**，正是 SPEC §4 允許（並且要求）的那種改動：一天不刪、一個
    節點不省、一個數字不變，只是把重複的鍵名收到表頭去講一次。同一段規則當初把中文散文
    換成 CSV 用的也是這個理由。

    `ponytail:` 攤平之後同一個活動大約落在 200 KB 上下，離上限還很遠，但這是這個帳號的
    量級不是普世保證。真的又撞到上限時，會是 provider 大聲拋出錯誤（訊息裡帶實際字元數，
    見上面那次的紀錄），不是安靜截斷；那天的下一步是把工作項從「一個活動」再切細成
    「一個廣告組」（GRILL 決定 5 的原句：篇幅上限之所以拿得掉，就是因為工作被切小了），
    不是在這裡開始丟資料。"""
    if not rows:
        return ""
    action_types, value_types = action_columns(rows)
    base_fields = [key for key in rows[0] if key not in ("actions", "action_values")]
    fieldnames = (
        base_fields
        + [f"action_{t}" for t in action_types]
        + [f"action_value_{t}" for t in value_types]
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        cells = {key: csv_cell(row[key]) for key in base_fields}
        cells.update(action_cells(row.get("actions"), "action_", action_types))
        cells.update(action_cells(row.get("action_values"), "action_value_", value_types))
        writer.writerow(cells)
    return buffer.getvalue()
