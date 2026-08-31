"""app/schedule/onboarding_slice_totals.py — 票 S2「開帳讀歷史」提示詞 segment [4]-2 的組裝：
一個活動的期間總計（外殼算好，不給模型口算）與涵蓋範圍（A2，票 S2b：每個實體窗口天數／
有資料天數／最長缺口，全部 Python 算好）。

**從 `app/schedule/onboarding_slice.py` 拆出來（票 S2b，二次拆檔，2026-08-31）**：那個檔案
原本裝了 S2 segment [4] 全部七支函式，A1～A4 陸續加完長到 765 行、頂到
`FILE_LINE_CAP = 800`，這次按三個各自獨立的家族拆開，這一份收「期間總計與涵蓋範圍」這族。
拆檔那次是純粹搬檔，函式本體一行沒改；A4 完整性審查第二輪（2026-08-31）在 `totals_text()`
補了 `_blank_or()`，這行往後才不成立——見那次改動自己的理由註解。

`entity_totals()` 是這一份**唯一拿 `conn` 的函式**：它重用 `app.meta.repository.spend_summary()`
去查資料庫（D7：`totals_text()` 要的數字不重算第二套聚合），其餘都是純函式。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/onboarding.py import 這裡。

`totals_text()` 借用 `app.schedule.onboarding_slice_csv` 的 `_round_money()`／
`_round_sig_figs()`，跟 `app.schedule.onboarding_slice` 的 `_blank_or()`——期間總計跟
逐日 CSV／事實卡要的是同一套「四捨五入到 Ads Manager 顯示的精度」規則（A3，票 S2b）跟
同一條「null 印成（無），不印成 Python 的 None」規則，寫第二套就是三邊各自印出不一樣的
東西。特意保留底線：這幾支不是給這裡以外任何人用的公開介面，只是這一族跟另外兩族共用同一份
邏輯，比照 Python 慣例，明確 import 底線名字仍然合法、也保留了「外面不該用 import *」的
訊號。
"""

from datetime import date, timedelta

from app.meta import repository as meta_repo
from app.schedule import onboarding_slice_csv
from app.schedule.onboarding_slice import _blank_or
from app.schedule.onboarding_slice_csv import _round_money, _round_sig_figs


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


def totals_text(
    totals: dict, action_totals: list,
    kept_columns: list[str] | None = None, omitted_columns: list[str] | None = None,
) -> str:
    """D8 segment [4]-2：期間總計，外殼算好的——票 S2 存在的理由之一就是手跑那次的唯一
    錯誤是這種加總（八天 view_content 手動加成 344，正確是 342），交給外殼算，不要模型
    口算。

    `kept_columns`／`omitted_columns`：A1（票 S2b）省掉的欄位清單，從 `bucketed_csv()` 那條路
    算好之後原封傳進來——**不在這裡重算一次**（票 S2b：「the omitted column list is
    computed in the CSV path — thread it cleanly, do not compute it twice」）。這裡只負責
    把「省了什麼」這件事講出來：省位元組不能連「這裡本來有資料，只是整個窗口加總是 0」
    這件事一起省掉，不然沉默就是謊言。

    花費／CPA 四捨五入到分、CTR／CPC／CPM／ROAS 四捨五入到 2～3 位有效數字——理由跟
    `bucketed_csv()` 那邊一樣（A3，票 S2b，見 `_round_money`／`_round_sig_figs`），這裡不
    重貼一次：Meta Ads Manager 自己就顯示這個精度，再往下的位數對這種樣本數是雜訊。"""
    actions_by_entity: dict[tuple, list] = {}
    for row in action_totals:
        actions_by_entity.setdefault((row["level"], row["entity_id"]), []).append(row)

    lines = ["## 期間總計（外殼算好的）"]
    for level in meta_repo.LEVELS:
        for entity in totals.get(level, []):
            lines.append(f"- [{level}] {entity['entity_name']}（{entity['entity_id']}）")
            lines.append(
                f"  花費 {_round_money(entity['spend'])}／曝光 {entity['impressions']}／"
                f"點擊 {entity['clicks']}／"
                # ROAS／CPA／CTR／CPC／CPM 這五個算出來可能是 None（一個活動沒有轉換
                # 事件，ROAS／CPA 就沒有東西可算）——`_round_money`／`_round_sig_figs`
                # 對 None 照樣回傳 None，直接塞進 f-string 印出來的是 Python 的
                # `None` 字面值，這一族的 `_ad_fact_card()` 用 `_blank_or()` 擋過
                # 這件事，這裡的期間總計原本沒套（審查回應：gate 審查點名，真帳號 24
                # 個活動 194 行指標全部印出裸的 `None`）。
                f"CTR {_blank_or(_round_sig_figs(entity['ctr']))}／"
                f"CPC {_blank_or(_round_money(entity['cpc']))}／"
                f"CPM {_blank_or(_round_money(entity['cpm']))}／"
                f"ROAS {_blank_or(_round_sig_figs(entity['roas']))}／"
                f"CPA {_blank_or(_round_money(entity['cpa']))}"
            )
            entity_actions = actions_by_entity.get((level, entity["entity_id"]), [])
            if entity_actions:
                action_text = "、".join(f"{a['action_type']}={a['total']}" for a in entity_actions)
                lines.append(f"  actions 加總：{action_text}")

    kept_columns = kept_columns or []
    omitted_columns = omitted_columns or []
    if kept_columns or omitted_columns:
        total = len(kept_columns) + len(omitted_columns)
        # 兩句都只講「Meta 為這個活動這段窗口回報過的種類」，不講完整性（票 S2b 完整性
        # 審查，2026-08-31）：原本的 else 分支寫「沒有省略任何一種」，讀起來像一句
        # 帳號層級的完整性保證，其實它只涵蓋 Meta 真的回報過的那幾種——從沒被回報過的
        # 種類根本不會走到這個函式，這一行沒有資格替它們背書。最便宜的誠實版是拿掉那句
        # 宣稱，不是多查一次全帳號有哪 77 種（那是為了一句話多打一次 Graph）。
        if omitted_columns:
            lines.append(
                f"- 逐日 CSV 欄位：Meta 為這個活動這段窗口回報過 {total} 種 actions／"
                f"action_values 欄位，{len(kept_columns)} 種有活動照常送出；以下 "
                f"{len(omitted_columns)} 種整個窗口加總是 0、已省略不送："
                + "、".join(omitted_columns)
            )
        else:
            lines.append(
                f"- 逐日 CSV 欄位：Meta 為這個活動這段窗口回報過 {total} 種 actions／"
                f"action_values 欄位，每一種整個窗口都有活動，都照常送出。"
            )
    return "\n".join(lines)


def coverage_text(rows: list[dict], since: date, until: date, roster: list[dict]) -> str:
    """D8 segment [4]-2b（A2，票 S2b）：一個實體一行，涵蓋範圍全部是 Python 算好的、
    絕不問模型——這正是逐日 CSV 原本真正有用的那一半工作（讓模型自己算哪幾天沒資料），
    決定④（GRILL：外殼算算術、模型做判斷）把這件事收回外殼，ADR 0045 把這兩個數字訂成
    未來做時間分桶的先決條件。

    `roster`：這個活動底下**所有**的實體（campaign 自己＋它的 adsets／ads），呼叫端從
    `campaign`／`adsets`／`ads` 這三份既有清單原封組出來——不能用 `rows`／`totals` 那份
    名單，因為那兩份天生只包含 Meta 真的回報過資料的實體：一個實體如果整段窗口一天都
    沒被回報，根本不會出現在 `rows` 裡，用 `rows` 當名單來源，這種實體就會悄悄消失
    （票 S2b：「an entity with zero rows must still appear with zero days-of-data, not
    vanish」）。`roster` 保證即使一列資料都沒有，這個實體照樣印出一行、天數全部是 0。

    每一行：窗口天數／有資料的天數／有花費卻沒 ROAS 的天數／第一天跟最後一天有資料／
    最長缺口的起訖。缺口計算涵蓋整段窗口（`since`～`until`），不是只看第一筆到最後一筆
    資料之間——缺口可能就落在窗口最前面或最後面（票 S2b 明講的邊界情形），從 `since`
    當天就開始算才不會漏掉那種缺口；一列資料都沒有的實體，缺口就是整段窗口。"""
    if not roster:
        return ""
    by_entity: dict[tuple, list[dict]] = {}
    for row in rows:
        by_entity.setdefault((row.get("level"), row.get("entity_id")), []).append(row)

    days_in_window = (until - since).days + 1
    all_buckets = onboarding_slice_csv.buckets_in_window(since, until)
    lines = ["## 每個實體的涵蓋範圍（外殼算好的）"]
    for entity in roster:
        key = (entity["level"], entity["entity_id"])
        entity_rows = by_entity.get(key, [])
        present = {row["spend_date"] for row in entity_rows}
        days_spend_no_roas = sum(
            1 for row in entity_rows
            if row.get("spend") not in (None, 0) and row.get("roas") is None
        )
        first_day = min(present) if present else None
        last_day = max(present) if present else None
        gap_start, gap_end = _longest_gap(present, since, until)

        first_last = (
            f"{first_day.isoformat()}～{last_day.isoformat()}"
            if first_day is not None and last_day is not None else "無"
        )
        gap = (
            f"{gap_start.isoformat()}～{gap_end.isoformat()}"
            if gap_start is not None and gap_end is not None else "無缺口"
        )
        # B1（票 S2b／ADR 0045）：整個窗口沒有資料的時間桶在這裡逐個點名。分桶表格只印
        # 真的有資料的桶（見 `onboarding_slice_csv.bucketed_csv()` 的 docstring：照 ADR
        # 原句每個實體印滿 24 個桶，實測列數反而漲 61%），缺席就改由這一行承擔——
        # **點名不是沉默**，ADR 0045 要擋的是「把缺席洗成沉默」，不是要求它一定佔一整列。
        # 桶規則本身只有一份（`time_bucket()`），這裡讀的是同一份，不是另外算一次。
        empty_buckets = [
            name for name in all_buckets
            if not any(onboarding_slice_csv.time_bucket(day) == name for day in present)
        ]
        empty_text = (
            f"整個沒資料的時間桶（{len(empty_buckets)}／{len(all_buckets)}）："
            + "、".join(empty_buckets)
            if empty_buckets else f"每個時間桶（共 {len(all_buckets)} 個）都有資料"
        )
        lines.append(
            f"- [{entity['level']}] {entity.get('entity_name', '')}（{entity['entity_id']}）："
            f"窗口 {days_in_window} 天／有資料 {len(present)} 天／"
            f"有花費卻沒 ROAS {days_spend_no_roas} 天／首末有資料 {first_last}／"
            f"最長缺口 {gap}／{empty_text}"
        )
    return "\n".join(lines)


def _longest_gap(present: set, since: date, until: date) -> tuple[date | None, date | None]:
    """`present` 是這個實體真的有資料的那幾天。回傳 `[since, until]` 這段窗口裡最長的
    連續無資料區間的起訖日——`present` 是空集合（這個實體一列資料都沒有）時，整段窗口
    `since`～`until` 就是那個缺口；窗口裡天天都有資料時回 `(None, None)`（A2，票 S2b）。"""
    best_start = best_end = None
    best_len = 0
    run_start = None
    day = since
    while day <= until:
        if day not in present:
            if run_start is None:
                run_start = day
        elif run_start is not None:
            run_len = (day - run_start).days
            if run_len > best_len:
                best_len, best_start, best_end = run_len, run_start, day - timedelta(days=1)
            run_start = None
        day += timedelta(days=1)
    if run_start is not None:
        run_len = (until - run_start).days + 1
        if run_len > best_len:
            best_start, best_end = run_start, until
    return best_start, best_end
