"""app/schedule/onboarding_slice_csv.py — 票 S2「開帳讀歷史」提示詞 segment [4]-3 的組裝：
一個活動的成效 CSV、實體對照表（A3，票 S2b）、欄位省略判斷（A1，票 S2b），加上金額／
比率的四捨五入（A3：CPM／CPC／花費／CPA 到分，ROAS／CTR 到 2～3 位有效數字，理由是 Meta
Ads Manager 自己顯示的精度）。

**B1（票 S2b／ADR 0045，2026-08-31）：逐日列換成時間分桶**，`daily_csv()` 連同它專用的
`_daily_cell_value()` 一起刪掉——`bucketed_csv()` 取代了它，沒有第二個呼叫端，留著就是
一份會慢慢跟真正走的那條路漂移的死碼（要看它長什麼樣子去翻 git）。它守的兩條規矩
（null≠0、整個窗口加總 0 的欄位不送）原封搬到新粒度上重新斷言，一條都沒有放鬆。

**從 `app/schedule/onboarding_slice.py` 拆出來（票 S2b，二次拆檔，2026-08-31）**：那個檔案
原本裝了 S2 segment [4] 全部七支函式，A1～A4 陸續加完長到 765 行、頂到
`FILE_LINE_CAP = 800`，這次按三個各自獨立的家族拆開，這一份收「逐日 CSV、實體對照表、
四捨五入」這族。純粹搬檔，函式本體一行沒改，只動了檔案歸屬、import 跟這份 docstring。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/onboarding.py 與
`app/schedule/onboarding_slice_totals.py`（借用這裡的 `_round_money()`／`_round_sig_figs()`，
見那份 docstring）import 這裡。全部是純函式（拿資料回文字，不碰連線、不打網路）。
"""

import csv
import io
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


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


_CENT = Decimal("0.01")


def _round_money(value):
    """花費／CPA／CPM／CPC 四捨五入到分（A3，票 S2b；CPM／CPC 是審查回應加進來的——
    這兩個也是「每千次曝光／每次點擊多少錢」，是錢，不是比率，本來就該跟花費／CPA 走
    同一條路，之前誤用 `_round_sig_figs`，一個 TWD 1,234.56 的 CPM 會被磨成 1230，
    跟 Ads Manager 顯示的數字對不上，違反這支函式自己存在的理由）：Meta Ads Manager
    自己就只顯示到分，分以下的位數對一個常常只有個位數訂單撐出來的數字是雜訊不是訊號，
    而且人只查得到自己在另一個畫面上看得到的位數——四捨五入到模型看不到的精度，等於
    逼人重算才能核對。

    全程留在 `Decimal`，不轉 `float`（審查回應：`float(Decimal("0.145"))` 四捨五入到
    分會磨成 0.14，正確的四捨五入是 0.15，這種一分錢的落差正是這支函式的存在理由要
    擋住的東西；`Decimal` 四捨五入完直接 `str()`，也不會像 `float` 那樣把很小的數字
    印成科學記號 `1.2e-05` 塞進 CSV 儲存格）。`None` 原樣穿過，不會變成 0；非 0 的金額
    如果磨到分剛好變成 0.00，改退去 `_round_sig_figs` 頂住，不讓「有花費」看起來像
    「沒花費」。"""
    if value is None:
        return None
    value = value if isinstance(value, Decimal) else Decimal(str(value))
    if value == 0:
        return _CENT - _CENT  # Decimal("0.00")，不是 int/float 的 0
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    return rounded if rounded != 0 else _round_sig_figs(value, 2)


def _round_sig_figs(value, sig: int = 3):
    """ROAS／CTR 四捨五入到 2～3 位有效數字（A3，票 S2b；CPC／CPM 改用 `_round_money`，
    見上），同一個理由：這是 Meta Ads Manager 顯示的精度，小數點後更多位是雜訊不是
    訊號。`None` 原樣穿過；用「有效數字」而不是「固定小數位」四捨五入，所以不論值多小，
    非 0 的值都不會被磨成 0——有效數字的定義本身就是從第一個非 0 位數起算，不是固定
    小數位。

    全程留在 `Decimal`，用 `adjusted()`（等同 `floor(log10(abs(value)))`，但不會有
    `float` 的浮點誤差）找最高位數字的位置，不轉 `float`——理由跟 `_round_money` 一樣：
    `float` 印小數字會變成科學記號。

    **只留在 `Decimal` 不夠（完整性審查回應，2026-08-31）**：小數字這裡本來就對，但
    `quantize()` 磨一個大數字（例如 ROAS／CPM ≥ 1000）到 3 位有效數字時，Decimal 自己
    的結果內部指數是正的，`str()`／f-string 一樣會印成 `1.23E+3`，跟這支函式自己
    docstring 講的「不會像 float 那樣印成科學記號」正好相反——這是上一輪只修了小數字那半
    留下的另一半。`format(rounded, "f")` 先逼出固定小數點的字串（不論正負指數），
    再用這個字串重建 `Decimal`：新物件的內部指數不會是正的，`str()`／CSV／f-string
    印出來一律是一般數字。"""
    if value is None:
        return None
    value = value if isinstance(value, Decimal) else Decimal(str(value))
    if value == 0:
        return Decimal(0)
    quantum = Decimal(1).scaleb(value.adjusted() - sig + 1)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return Decimal(format(rounded, "f"))


def entity_dictionary_text(rows: list[dict]) -> str:
    """A3（票 S2b）：名字跟層級只在這裡講一次，逐日 CSV 的資料列只留 `entity_id`。今天
    每一列 CSV 都重複一次完整的實體名稱（`entity_name`），這裡把它們收成一張對照表放在
    CSV 表格前面——模型讀表格前先讀這張表，就知道每個 id 是哪一層、叫什麼名字，不必
    每一列都再讀一次同一個名字。

    以 `entity_id` **最後一次**出現時的 `level`／`entity_name` 為準——`rows` 依
    `spend_date` 由舊到新排序，「最後一次」就是這個實體窗口裡最新的名字，跟
    `spend_summary()`（`app/meta/repository.py:414-419`，記錄過真帳號窗口內改名這個
    真實案例）改名時取最新名字的規則一致，不然對照表跟總計那節報的名字會兜不起來
    （審查回應：content 審查點名，原本取第一次出現的名字，一個實體窗口內真的改過名字
    時，新名字會整個消失）。如果窗口內真的改過名，把舊名字也印出來，不能只留一個。

    沒有任何一列有 `entity_id` 就回空字串，不硬造一張空表。每一行用
    `- [{level}] {name}（{entity_id}）`，跟 `coverage_text()` 同一個形狀——不用 `｜`
    分隔（審查回應：`｜` 是台灣廣告帳號常見的命名字元，拿它當分隔符，名字裡本來就有
    `｜` 的實體會撐爆成四個以上的欄位，沒辦法可靠切回三個欄位）。"""
    first_seen: dict[str, tuple[str, str]] = {}
    last_seen: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for row in rows:
        entity_id = row.get("entity_id")
        if entity_id is None:
            continue
        entry = (row.get("level", ""), row.get("entity_name", ""))
        if entity_id not in first_seen:
            first_seen[entity_id] = entry
            order.append(entity_id)
        last_seen[entity_id] = entry
    if not order:
        return ""
    lines = ["## 這個活動涉及的實體對照表（id → 層級／名稱；下面逐日表只留 id）"]
    for entity_id in order:
        level, name = last_seen[entity_id]
        old_name = first_seen[entity_id][1]
        rename_note = f"（窗口內曾用名：{old_name}）" if old_name and old_name != name else ""
        lines.append(f"- [{level}] {name}（{entity_id}）{rename_note}")
    return "\n".join(lines)


def action_columns(rows: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """這一片實際出現過的 `actions`／`action_values` 種類，各自再分成「送」跟「不送」兩堆
    （A1，票 S2b）。回傳 `(action_kept, value_kept, action_omitted, value_omitted)`，四份都
    已排序去重。

    只收這一片真的有的種類，不是整個帳號的全部：2026-08-31 對真帳號實測，整個帳號有 77 種
    action_type，但單一活動用得到的遠少於此——欄位表照全帳號展開會讓每一列多背幾十個永遠
    空著的欄位。

    「送」跟「不送」的分界是**這個活動整個窗口加總起來是不是 0**，不是「看起來不重要」
    （票 S2b A1：assert 先、才能砍）。加總不出來的值（不是數字）一律當「無法證明是 0」，
    留在送的那一堆——寧可多送，不能錯砍。

    這裡不處理「整欄從頭到尾都空白」的情況，因為那種情況不存在：一個種類要能進到這個
    函式回傳的名單裡，前提就是它在某一列的 `actions`／`action_values` 裡至少出現過一次
    （不論那次的值是不是 0）。「出現過但加總是 0」跟「從沒出現過」是兩件不同的事，後者
    本來就不會變成一欄，也就沒有「整欄空白」還被拿去跟「加總是 0」相比的問題——`action_cells()`
    的空白，指的是同一種類在**其他天**沒被回報，不是這一整種類全灰。"""
    action_kept, action_omitted = _zero_sum_split(rows, "actions")
    value_kept, value_omitted = _zero_sum_split(rows, "action_values")
    return action_kept, value_kept, action_omitted, value_omitted


def _zero_sum_split(rows: list[dict], field: str) -> tuple[list[str], list[str]]:
    """`rows` 裡 `field`（`"actions"` 或 `"action_values"`）出現過的種類，依「這個活動整個
    窗口加總是不是 0」分成 (kept, omitted) 兩堆，都已排序。只加總「真的有回報」的那幾天，
    其他天沒回報的不算進去、也不當 0 算——這正是 `action_cells()` 那條 null≠0 規矩在加總
    這一步的樣子（GRILL 決定1(d)）。

    審查回應，兩處修正：(1) 一個種類「有回報但沒給數字」（`value` 是 `None`）原本會先
    `setdefault` 成 0 再 `continue`，等於把「無法證明」偷渡成「證明是 0」——三位審查者
    都點名這一行，改成跟 `InvalidOperation` 那支同一條路，進 `unprovable`（留），不進
    `totals`（0）。(2) 判斷「這個種類整個窗口有沒有活動」改用絕對值加總，不是簽名加總——
    `purchase` 當天 1000、隔天退款 -1000，簽名加總是 0 但那不是「沒有這個事件」，是
    「發生過又全額退回」，`totals_text()` 的省略提示不該把後者講成前者。"""
    totals: dict[str, Decimal] = {}
    abs_totals: dict[str, Decimal] = {}
    unprovable: set[str] = set()
    for row in rows:
        for entry in row.get(field) or ():
            if not (isinstance(entry, dict) and entry.get("action_type")):
                continue
            action_type = entry["action_type"]
            raw = entry.get("value")
            totals.setdefault(action_type, Decimal(0))
            abs_totals.setdefault(action_type, Decimal(0))
            if raw is None:
                unprovable.add(action_type)
                continue
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                unprovable.add(action_type)
                continue
            totals[action_type] += value
            abs_totals[action_type] += abs(value)
    kept = {t for t, total in abs_totals.items() if total != 0} | unprovable
    omitted = {t for t in totals if t not in kept}
    return sorted(kept), sorted(omitted)


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


# ---------------------------------------------------------------------------
# B1（票 S2b／ADR 0045）：時間分桶取代逐日列
# ---------------------------------------------------------------------------

def time_bucket(day: date) -> str:
    """一天屬於哪個時間桶：**月 ×（平日｜週末）**（B1，票 S2b；ADR 0045）。

    **週末絕不跟平日併成一桶，這條規則只活在這一行，理由寫在旁邊**：這套系統目前產出過
    最有價值的一條結論是「外送折扣那組廣告週末的每次點擊成本比平日低約 40%」。用自然週
    當桶會把那句話平均掉——那等於用手刪掉整個系統存在的理由所要生產的那一類發現
    （ADR 0045「Natural weeks are forbidden as a bucket boundary」）。搭配的粗軸（月／
    週序）是實作選擇，golden-sample diff 可以改；週末這一刀不是那種可以改的選擇。

    月份選擇的理由是「先粗後細」（票 S2b B1）：361 天的窗口下，月×平日週末＝每個實體
    最多 24 個桶，對照今天最多 361 列。真的磨掉了什麼，由黃金樣本逐條 diff 說了算，不是
    現在先猜——所以桶規則只有這一支函式，換成週序是改這一行，不是改整條路。"""
    return f"{day:%Y-%m}/" + ("週末" if day.weekday() >= 5 else "平日")


def buckets_in_window(since: date, until: date) -> list[str]:
    """`[since, until]` 這段窗口裡實際存在的全部時間桶，依時間排序。窗口不滿一整月、或
    某個月剛好沒有週末（不可能，但不假設）時，不存在的桶就不會出現——桶清單從真實日期
    長出來，不是拿月數乘二算出來的。"""
    seen: list[str] = []
    day = since
    while day <= until:
        name = time_bucket(day)
        if name not in seen:
            seen.append(name)
        day += timedelta(days=1)
    return seen


def _bucket_day_counts(since: date, until: date) -> dict[str, int]:
    """每個桶在這段窗口裡涵蓋幾天——`days_covered` 那一欄的來源。月份長度不同、週末天數
    也不同，所以逐日數，不套公式。"""
    counts: dict[str, int] = {}
    day = since
    while day <= until:
        name = time_bucket(day)
        counts[name] = counts.get(name, 0) + 1
        day += timedelta(days=1)
    return counts


def _sum_or_none(values: list):
    """有值就加總，一個值都沒有回 `None`——**不是 0**。這是 null≠0 那條規矩在換了時間
    粒度之後的樣子（ADR 0045：「Null ≠ zero survives the change of grain」）：這個桶裡
    Meta 一天都沒回報這個數字，跟這個桶的這個數字真的是 0，是兩件不同的事。"""
    present = [v for v in values if v is not None]
    if not present:
        return None
    total = Decimal(0)
    for value in present:
        total += value if isinstance(value, Decimal) else Decimal(str(value))
    return total


def _bucket_roas(day_rows: list[dict]):
    """一個桶的 ROAS＝**這幾天的營收加總 ÷ 這幾天的花費加總**，而且只算「那天真的有
    ROAS」的日子（營收＝那天的 `roas × spend`）。跟 `spend_summary()` 的
    `SUM(spend * roas) / SUM(spend)` 是同一個算法，不是把每天的 ROAS 平均——平均會讓一天
    花 10 元的 ROAS 跟一天花 10,000 元的 ROAS 一樣重。

    一天都沒有 ROAS 就回 `None`，不回 0（ADR 0045 明訂）。有 ROAS 的天數另外印在
    `days_with_roas` 欄——真帳號 560 個有花費的廣告日裡只有 191 天帶 ROAS，不講分母的話
    這個數字讀起來像整個桶的表現，其實只涵蓋其中幾天。"""
    revenue = Decimal(0)
    spend = Decimal(0)
    for row in day_rows:
        roas, day_spend = row.get("roas"), row.get("spend")
        if roas is None or day_spend is None:
            continue
        roas = roas if isinstance(roas, Decimal) else Decimal(str(roas))
        day_spend = day_spend if isinstance(day_spend, Decimal) else Decimal(str(day_spend))
        revenue += roas * day_spend
        spend += day_spend
    if spend == 0:
        return None
    return _round_sig_figs(revenue / spend)


def _action_sums(day_rows: list[dict], field: str, prefix: str, types: list[str]) -> dict:
    """一個桶的 `actions`／`action_values` 加總，一個種類一欄。**這個桶裡沒有任何一天
    回報過這個種類就留空白，不是 0**——跟 `action_cells()` 逐日那層守的是同一條線
    （GRILL 決定 1(d)），只是換了粒度。"""
    totals: dict[str, list] = {t: [] for t in types}
    for row in day_rows:
        for entry in row.get(field) or ():
            if not (isinstance(entry, dict) and entry.get("action_type")):
                continue
            action_type = entry["action_type"]
            if action_type in totals and entry.get("value") is not None:
                totals[action_type].append(entry["value"])
    return {f"{prefix}{t}": _blank_if_none(_sum_or_none(v)) for t, v in totals.items()}


def _blank_if_none(value):
    """CSV 儲存格：`None` 印成空白，不印成 Python 的 `None` 字面值，也不印成 0。"""
    return "" if value is None else value


def _outlier_days(day_rows: list[dict], conversion_types: tuple) -> list[dict]:
    """一個桶裡要額外原封送出的逐日原列：**花費最高的那一天，加上轉換最高的那一天**
    （B1，票 S2b）。兩天可能是同一天，去重後最多 2 列。

    **這條規則沒有任何門檻常數**，這正是它被選中的理由（票 S2b B1）：手稿版本提過「花費
    或轉換超過該實體自己中位數的某個倍數」，那個倍數沒有來源，而沒有來源的數字不准進
    程式（憲章；`app/methodology/ab-testing.md:73` 「不用自訂常數」）。用排名不用門檻，
    每個桶固定最多兩列，沒有數字要辯護。

    「轉換」的定義來自品牌自己的 `conversion_goal`（`meta_repo.conversion_action_types()`
    ——CPA 分母用的是同一份），不是「所有 actions 加起來最多」：後者會讓一天 800 次
    連結點擊贏過一天 9 筆成交。目標是 `awareness`（沒有對應的標準事件）時 `conversion_types`
    是空的，那就只挑花費最高那天，不隨便找個事件充數。

    分桶最容易磨掉的就是「某一天爆單」這類單日發現，這兩列是把那件事留在桌上的方式。"""
    if not day_rows:
        return []
    picked: list[dict] = []

    def _remember(row):
        if row is not None and not any(r["spend_date"] == row["spend_date"] for r in picked):
            picked.append(row)

    spend_rows = [r for r in day_rows if r.get("spend") is not None]
    if spend_rows:
        _remember(max(spend_rows, key=lambda r: r["spend"]))
    if conversion_types:
        scored = [(_conversion_count(r, conversion_types), r) for r in day_rows]
        scored = [(c, r) for c, r in scored if c > 0]
        if scored:
            _remember(max(scored, key=lambda pair: pair[0])[1])
    return sorted(picked, key=lambda r: r["spend_date"])


def _conversion_count(row: dict, conversion_types: tuple) -> Decimal:
    """一列裡屬於這個品牌轉換目標的事件次數加總。同一次成交常常被好幾個同義 action_type
    各回報一次（`app/meta/graph.py` 檔頭記過這個形狀），所以**只取優先序裡第一個真的有
    回報的種類**，不是把同義字全部加起來——加起來會把一筆成交數成三筆。"""
    by_type = {
        entry["action_type"]: entry.get("value")
        for entry in (row.get("actions") or ())
        if isinstance(entry, dict) and entry.get("action_type")
    }
    for action_type in conversion_types:
        value = by_type.get(action_type)
        if value is not None:
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return Decimal(0)
    return Decimal(0)


def bucketed_csv(
    rows: list[dict], since: date, until: date, conversion_types: tuple = (),
) -> tuple[str, str, list[str], list[str]]:
    """D8 segment [4]-3，B1（票 S2b；ADR 0045）：**逐日列換成時間分桶**，回傳形狀跟
    `daily_csv()` 完全一樣 `(實體對照表文字, csv 內容, 送出的欄位, 省掉的欄位)`，呼叫端
    一行都不用改。

    一列＝一個實體的一個時間桶，外加每個桶最多兩列原封的逐日原列（見 `_outlier_days()`）。
    有 `spend_date` 的是某一天的原始資料，沒有 `spend_date` 的是那個桶的加總——這一欄
    空不空就是「這一列是哪一種」，不另外開一個 `row_kind` 欄位。

    **只有真的有資料的桶會變成一列。** ADR 0045 原本要求空桶也留一列，2026-08-31 拿真
    帳號量過之後改掉了（改動寫在 ADR 0045 自己那一節）：195 個實體 × 24 個桶裡 83% 是
    空的，照原句做列數會從 3,531 變成 5,702，比原本的逐日列還胖 61%，B1 存在的理由當場
    消失。空桶改成由 `coverage_text()` 逐個實體點名（「這些桶整個窗口沒有資料：…」），
    一行抵 24 列——**缺席照樣被講出來，只是不占一整列**，ADR 0045 真正要擋的「把缺席
    洗成沉默」沒有鬆。

    每一列都帶 `days_covered`／`days_with_data`／`days_with_roas`：沒有前兩個數字就不准
    分桶（ADR 0045 的先決條件），第三個是 ROAS 那一欄的分母（見 `_bucket_roas()`）。

    加總只改形狀不改內容：一個桶的 spend／impressions／clicks 等於它取代的那幾天加起來
    （`app/tests/test_onboarding_read.py` 有一支閘門守這件事）。花費先加總再四捨五入，
    不是把每天四捨五入過的值相加——後者會累積捨入誤差，跟期間總計那節對不起來。"""
    if not rows:
        return "", "", [], []
    entity_dict_text = entity_dictionary_text(rows)
    action_kept, value_kept, action_omitted, value_omitted = action_columns(rows)
    days_covered = _bucket_day_counts(since, until)

    # 實體的出現順序照 `rows` 原本的順序（level 分區塊、區塊內 entity_id 排序），跟實體
    # 對照表印出來的順序一致——模型讀表格時對得起來。
    grouped: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for row in rows:
        key = (row.get("entity_id"), time_bucket(row["spend_date"]))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    fieldnames = (
        ["entity_id", "campaign_id", "adset_id", "ad_id", "bucket", "spend_date",
         "days_covered", "days_with_data", "days_with_roas",
         "spend", "impressions", "clicks", "roas", "attribution_window"]
        + [f"action_{t}" for t in action_kept]
        + [f"action_value_{t}" for t in value_kept]
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for key in order:
        entity_id, bucket_name = key
        day_rows = grouped[key]
        writer.writerow(_bucket_row(
            entity_id, bucket_name, day_rows, days_covered.get(bucket_name, 0),
            action_kept, value_kept,
        ))
        for day_row in _outlier_days(day_rows, conversion_types):
            writer.writerow(_outlier_row(bucket_name, day_row, action_kept, value_kept))

    kept_columns = [f"action_{t}" for t in action_kept] + [f"action_value_{t}" for t in value_kept]
    omitted_columns = (
        [f"action_{t}" for t in action_omitted] + [f"action_value_{t}" for t in value_omitted]
    )
    return entity_dict_text, buffer.getvalue(), kept_columns, omitted_columns


def _bucket_row(
    entity_id, bucket_name: str, day_rows: list[dict], days_covered: int,
    action_kept: list[str], value_kept: list[str],
) -> dict:
    """一個桶的加總列。`attribution_window` 這個桶裡出現過幾種就全部印出來（用 `|` 串）
    ——通常只有一種，但真的混到兩種時把它藏起來，等於把「這幾天的數字不是同一把尺量的」
    這件事洗掉。"""
    first = day_rows[0]
    windows = sorted(
        {str(r["attribution_window"]) for r in day_rows if r.get("attribution_window")}
    )
    cells = {
        "entity_id": entity_id,
        "campaign_id": first.get("campaign_id"),
        "adset_id": first.get("adset_id"),
        "ad_id": first.get("ad_id"),
        "bucket": bucket_name,
        "spend_date": "",  # 空＝這一列是加總，不是某一天
        "days_covered": days_covered,
        "days_with_data": len({r["spend_date"] for r in day_rows}),
        "days_with_roas": sum(1 for r in day_rows if r.get("roas") is not None),
        "spend": _blank_if_none(_round_money(_sum_or_none([r.get("spend") for r in day_rows]))),
        "impressions": _blank_if_none(_sum_or_none([r.get("impressions") for r in day_rows])),
        "clicks": _blank_if_none(_sum_or_none([r.get("clicks") for r in day_rows])),
        "roas": _blank_if_none(_bucket_roas(day_rows)),
        "attribution_window": "|".join(windows),
    }
    cells.update(_action_sums(day_rows, "actions", "action_", action_kept))
    cells.update(_action_sums(day_rows, "action_values", "action_value_", value_kept))
    return cells


def _outlier_row(
    bucket_name: str, row: dict, action_kept: list[str], value_kept: list[str],
) -> dict:
    """一個桶裡被挑出來原封送出的那一天（見 `_outlier_days()`）：跟分桶前的逐日列同一份
    內容，`days_*` 三欄留白——一天就是一天，那三個數字對它沒有意義，填 1 只是噪音。"""
    cells = {
        "entity_id": row.get("entity_id"),
        "campaign_id": row.get("campaign_id"),
        "adset_id": row.get("adset_id"),
        "ad_id": row.get("ad_id"),
        "bucket": bucket_name,
        "spend_date": csv_cell(row["spend_date"]),
        "days_covered": "", "days_with_data": "", "days_with_roas": "",
        "spend": _blank_if_none(_round_money(row.get("spend"))),
        "impressions": _blank_if_none(row.get("impressions")),
        "clicks": _blank_if_none(row.get("clicks")),
        "roas": _blank_if_none(_round_sig_figs(row.get("roas"))),
        "attribution_window": csv_cell(row.get("attribution_window")),
    }
    cells.update(action_cells(row.get("actions"), "action_", action_kept))
    cells.update(action_cells(row.get("action_values"), "action_value_", value_kept))
    return cells
