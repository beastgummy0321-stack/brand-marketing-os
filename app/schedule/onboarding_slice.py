"""app/schedule/onboarding_slice.py — 票 S2「開帳讀歷史」提示詞 segment [4]-1 的組裝：
一個活動的結構（廣告組受眾）與素材（廣告文案）攤成事實卡。

**這一族從 S2b 步驟 0 機械式搬出來、S2b A1～A4 直接在這裡加的**（票 S2b 步驟 0，
2026-08-31；A1～A4，2026-08-31）：原本 `onboarding.py` 的 segment [4] 七支函式先整批搬進
`onboarding_slice.py`（那時 205 行），A1～A4 陸續改在這裡，長到 765 行、頂到
`FILE_LINE_CAP = 800`（app/tests/test_architecture_boundaries.py）。這次（同一天）把那 765 行
按三個各自獨立的家族拆開：這一份留住原本的檔名，收「結構與素材事實卡」這一族——往後
A4 的收尾與後續調整幾乎全落在這裡，所以留給它最多餘裕；另外兩族搬去
`app/schedule/onboarding_slice_totals.py`（期間總計／涵蓋範圍）與
`app/schedule/onboarding_slice_csv.py`（逐日 CSV／實體對照表／四捨五入）。三族之間除了
`onboarding_slice_totals.totals_text()` 借用 `onboarding_slice_csv` 的四捨五入函式，互不
呼叫——這是純粹搬檔，函式本體一行沒改，只動了檔案歸屬、import 跟這幾份 docstring。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/onboarding.py import 這裡。
全部是純函式（拿資料回文字，不碰連線、不打網路）。
"""

import json


def structure_text(
    campaign: dict, adsets: list, ads: list, creatives_by_ad: dict,
) -> tuple[str, list]:
    """D8 segment [4]-1：這個活動的結構與素材，攤成事實卡（A4，票 S2b）——原本整包
    `json.dumps(indent=2)` 直接倒出去，2026-08-31 實機驗收量到一個活動 97,220 字元；
    改成一個廣告組一張受眾卡、一則廣告一張素材卡，欄位名稱一律用 Meta 自己的
    （`targeting`／`geo_locations`／`call_to_action_type`……，D5：不新造「主文案／標題」
    這種友善名字），文案本身逐字照登、絕不改寫摘要（票明講：a summarised quote is not
    a quote）。

    回不出素材的廣告列在文字裡（「Meta 現在回不出這一則的素材」）也列進回傳的
    `unreadable`（供呼叫端存進 context_scope_json 給 GET 用）——絕不整筆消失（票 S2 §1）。

    **保險絲**：`_creative_variants()` 回空清單（四條路各有各的理由，見那支函式與
    `_FUSE_*` 四個常數），代表 Meta 回了一個讀不出可信文案的形狀，這則素材的原始 JSON
    原封不動送出去，並且**印出是哪一條路觸發的**——寧可貴，不可漏（票 S2b A4，三個獨立
    審查者都要求這條）。這種廣告本身還是讀得到素材，不算進 `unreadable`（那份名單只收
    Meta 真的一則素材都不給的廣告）。"""
    lines = [
        "## 這個活動的結構與素材",
        f"campaign：[{campaign['id']}] {campaign['name']}（{campaign['effective_status']}）",
        "",
        "### 廣告組（受眾）",
    ]
    lines.extend(_adset_fact_card(adset) for adset in adsets)
    lines.append("")
    lines.append("### 廣告（素材）")
    unreadable = []
    for ad in ads:
        creatives = creatives_by_ad.get(ad["id"], [])
        if not creatives:
            unreadable.append({"ad_id": ad["id"], "name": ad.get("name", "")})
            lines.append(f"- [{ad['id']}] {ad.get('name', '')}：Meta 現在回不出這一則的素材")
            continue
        lines.append(_ad_fact_card(ad, creatives))
    return "\n".join(lines), unreadable


def _classify_audience_type(targeting: dict) -> str:
    """判斷這個廣告組的受眾型態：lookalike／retargeting／interest／prospecting 四選一
    （A4，票 S2b：「audience type (prospecting / retargeting / lookalike / interest)」）。
    判斷順序由窄到寬——`lookalike_spec` 存在＝從既有受眾長出來的相似受眾；沒有
    lookalike_spec 但有 `custom_audiences`＝拿既有名單做再行銷；都沒有但
    `flexible_spec` 裡帶興趣＝用興趣鎖定開發受眾；什麼都沒有＝廣泛開發（prospecting）。

    `ponytail:` 這是啟發式分類，不是 Meta 自己的欄位——真帳號如果 `custom_audiences`
    只拿來排除、真正鎖定靠別的欄位，這裡會誤判成 retargeting；S2b 手上沒有真帳號的
    `targeting` 原始形狀可比對，等 golden-sample 那輪真的跑出這種帳號再調順序。"""
    if targeting.get("lookalike_spec"):
        return "lookalike"
    if targeting.get("custom_audiences"):
        return "retargeting"
    for group in targeting.get("flexible_spec") or ():
        if isinstance(group, dict) and group.get("interests"):
            return "interest"
    return "prospecting"


# `flexible_spec` 底下的細節鎖定不是只有 interests——真帳號 368741390835357 驗證過
# （完整性審查第二輪，2026-08-31）behaviors／industries／work_positions 也是同一個
# `flexible_spec` 陣列裡的真實鍵，27/50 個廣告組帶了這三種之一，原本只收
# interests 一種，另外三種連同一句「還有 N 個未列出」都沒有——卡片上唯一的
# honesty counter 因此把模型永遠看不到的東西也算進「已經看過整個受眾」。四種鎖定
# 用同一套去重＋前 10／還有 N 個未列出的邏輯，寫成共用函式，不是各自抄一份。
_FLEXIBLE_SPEC_KINDS = ("interests", "behaviors", "industries", "work_positions")


def _flexible_spec_items(targeting: dict, kind: str) -> list[dict]:
    """從 `targeting.flexible_spec` 收集某一種明細鎖定，用 (id, name) 去重——理由跟
    `_adset_fact_card()` 原本收集 interests 那段一樣：沒有 id 的項目全部會收斂成同一把
    `id=None` 的 key，第一個以外的全部悄悄消失，honesty counter 卻沒有跟著少算
    （審查回應：content 審查點名，四種鎖定都要守同一條規矩）。"""
    items: list[dict] = []
    seen_keys: set = set()
    for group in targeting.get("flexible_spec") or ():
        if not isinstance(group, dict):
            continue
        for item in group.get(kind) or ():
            if not isinstance(item, dict):
                continue
            key = (item.get("id"), item.get("name"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            items.append(item)
    return items


def _flexible_spec_line(kind: str, items: list[dict]) -> str:
    """一種明細鎖定印一行：前 10 個名稱＋「還有 N 個未列出」——跟原本 interests 那行
    格式一模一樣，只是換了鍵名跟資料來源。"""
    shown = items[:10]
    text = "、".join(i.get("name") or str(i.get("id", "")) for i in shown) or "（無）"
    remaining = len(items) - len(shown)
    if remaining > 0:
        text += f"，還有 {remaining} 個未列出"
    return f"  {kind}（前 10／共 {len(items)} 個）：{text}"


def _adset_fact_card(adset: dict) -> str:
    """A4（票 S2b）：一個廣告組一張受眾卡——受眾型態／前 10 個興趣加「還有 N 個未列出」／
    地理／年齡性別／排除數。欄位名稱一律用 Meta 自己的鍵名（`targeting` 原始形狀的
    `geo_locations`／`age_min`／`age_max`／`genders`），不新造「主受眾」這種友善名字
    （票明講：keep using Meta's own field names for anything you surface）。

    `effective_status`／`optimization_goal`／`billing_event`：審查回應補回——這三個
    `app/meta/graph.py` 本來就打 Meta 要回來（`_ENTITY_FIELDS["adset"]`），A4 攤成卡片
    時漏掉了；`optimization_goal`／`billing_event` 就是 ADR 0045 講的「budget mode（結構性
    事實）」，兩個廣告組沒有這兩個欄位就沒辦法分辨表現差異是不是「平台自己分配預算」造成
    的（部門任務檔明講的那條線）；`effective_status` 沒有它，PAUSED／ARCHIVED 的廣告組跟
    正在跑的長得一模一樣，涵蓋範圍那段的缺口會被誤讀成「投遞崩了」。

    `audience_type` 後面帶的 `custom_audiences`／`lookalike_spec` 個數：這個型態是
    `_classify_audience_type()` 猜的啟發式，不是 Meta 自己的欄位（見那支函式的
    `ponytail:` 段落）；A4 把 `targeting` 原始形狀拿掉之後，這行猜測變成模型唯一能看到
    的「證據」，等於逼模型全盤相信一個沒有來源可查的判斷。印出猜測所依據的原始個數，
    這行字才是「摘要」不是「判決」——審查回應：constitution 審查點名。"""
    targeting = adset.get("targeting") or {}
    audience_type = _classify_audience_type(targeting)
    audience_basis = (
        f"custom_audiences={len(targeting.get('custom_audiences') or ())}／"
        f"lookalike_spec={'有' if targeting.get('lookalike_spec') else '無'}"
    )

    flexible_lines = [
        _flexible_spec_line(kind, _flexible_spec_items(targeting, kind))
        for kind in _FLEXIBLE_SPEC_KINDS
    ]

    # `excluded_product_audience_specs`（審查回應點名的漏項）——這個帳號沒有
    # `exclusions` 這個鍵，但有 `excluded_product_audience_specs`（例如排除「已購買
    # 過某個 product set 的人」的再行銷排除法），原本沒算進 exclusion_count，
    # 一個真的有排除受眾的廣告組會印出「exclusion_count：0」。
    exclusions = targeting.get("exclusions") or {}
    exclusion_count = (
        len(targeting.get("excluded_custom_audiences") or ())
        + len(exclusions.get("interests") or ())
        + len(targeting.get("excluded_product_audience_specs") or ())
    )

    # `age_range`／`targeting_automation.advantage_audience`：原本只印
    # `age_min`／`age_max`，這帳號 30/50 個廣告組開了 Advantage+ 受眾擴張
    # （`advantage_audience: 1`），Meta 因此把 age_min／age_max 灌成平台上限，
    # 廣告主真正選的年齡範圍留在 `age_range` 裡——只印前者、拿掉後者，會讓兩個
    # age_range 完全不同的廣告組印出同一組 age_min／age_max，看起來像鎖定了同一個
    # 年齡帶（完整性審查第二輪，2026-08-31，真帳號驗證過）。
    advantage_audience = (targeting.get("targeting_automation") or {}).get("advantage_audience")

    return "\n".join([
        f"- [{adset.get('id')}] {adset.get('name', '')}"
        f"（{adset.get('effective_status', '')}）",
        f"  optimization_goal={adset.get('optimization_goal')}／"
        f"billing_event={adset.get('billing_event')}",
        f"  audience_type：{audience_type}（{audience_basis}）",
        *flexible_lines,
        f"  geo_locations：{json.dumps(targeting.get('geo_locations'), ensure_ascii=False)}",
        f"  age_min={targeting.get('age_min')}／age_max={targeting.get('age_max')}／"
        f"age_range={targeting.get('age_range')}／advantage_audience={advantage_audience}／"
        f"genders={targeting.get('genders')}",
        f"  exclusion_count：{exclusion_count}",
    ])


def _resolve_labelled_asset(assets, label):
    """`asset_feed_spec` 用 label 間接對應：`bodies`／`titles`／`images`／`videos`
    每個條目自己帶一組 `adlabels`（`[{"name": ..., "id": ...}]`），
    `asset_customization_rules` 的 `body_label`／`title_label`／`image_label`／
    `video_label` 用同一份 label 回頭指是哪一條——不是位置對位
    （Marketing API AdCreative `asset_feed_spec` 文件）。找不到就回 `None`。

    **A4 審查（完整性審查，2026-08-31）點名的 bug 1**：`label` 本身也是 Meta 回的
    AdAssetLabel 物件，不是純字串——真帳號 368741390835357 驗證過，`body_label` 長這樣：
    `{"name": "placement_asset_fac71af9335155a8c_1768207545468",
    "id": "120241518019330671"}`。原本這裡直接拿這整個字典去跟 `adlabel.get("name")`
    （字串）比對，字典永遠不等於字串，比對永遠失敗——這個帳號 23 則用
    `asset_customization_rules` 的素材全部因此掉進保險絲，97,220 字元的目標在這種
    帳號上完全達不到。**這裡先拆開 label 物件，`name`／`id` 都比，任一邊對上就算數**：
    真帳號目前兩邊永遠同時給、彼此一致，但文件沒保證以後也一樣，兩邊都比不會漏接
    只認一邊的帳號。"""
    if label is None:
        return None
    label_name = label.get("name") if isinstance(label, dict) else label
    label_id = label.get("id") if isinstance(label, dict) else None
    for asset in assets or ():
        for adlabel in asset.get("adlabels") or ():
            if (label_name is not None and adlabel.get("name") == label_name) or (
                label_id is not None and adlabel.get("id") == label_id
            ):
                return asset
    return None


# `object_story_spec` 底下四種形狀各自的文案欄位對到不同的 Meta 鍵名——不是同一組
# `message`／`name`：link_data 用 message（主文案）／name（標題），video_data 用
# message（主文案）／title（標題，不是 name！），photo_data 只有 caption。審查回應：
# content 審查點名 video_data 讀錯鍵名，把 `title：None` 印在真的有標題的廣告上——保險絲
# 沒有點火，因為 `message` 找到了，`_ad_fact_card()` 看到的是「讀到一半」不是「沒讀到」。
# `extra_fields`：同一個形狀裡除了主文案／標題還有的其他逐字文案欄位（description／
# caption／link_description），一併照登，不是只抽兩個欄位就當全部（票明講：a summarised
# quote is not a quote，這條線也包括「還有沒抽到的欄位」）。
#
# `template_data`（第四種，完整性審查第二輪，2026-08-31 補上）：Dynamic/Advantage+
# creative 的第五種真實形狀，欄位跟 link_data 一樣是 message／name，真帳號
# 368741390835357 158 則素材裡 25 則是這個形狀。原本 `_STORY_SHAPES` 不認得它，這種
# 素材直接落到下面的 `asset_feed_spec` 分支，印出 feed 那幾份文案、`template_data` 底下
# 逐張輪播卡片（`child_attachments`）的文案整個消失、保險絲也不會點火（因為 feed 那邊
# 抽得到 body）——34/158 則廣告因此漏字，73 條文案帳號全域漏接，這是這輪審查點名最大的
# 一個缺口。
# 保險絲的四個理由（票 S2b，2026-08-31）：`_creative_variants()` 有四條各自不同的路會回空
# 清單，`_ad_fact_card()` 原本不論走哪一條都印同一句「這則素材抽不出 body 也抽不出 title」。
# 真帳號 368741390835357 實測 34 次觸發裡 27 次那句是假的——緊接著印出來的原始 JSON 裡就有
# body。系統對分析員說一句它自己下一行就推翻的話，比不說更糟，所以理由跟著回傳值一起走。
_FUSE_BOTH_ENCODINGS = "object_story_spec 與 asset_feed_spec 兩邊都帶文案，讀不出哪一份算數"
_FUSE_RULE_UNMATCHED = "asset_customization_rules 有規則對不到任何 body／title，不送對得到的那幾條"
_FUSE_ASSET_UNUSED = "分組後仍有 body／title 文案沒被任何一條規則用到，label 配對讀不懂這則素材"
_FUSE_NO_COPY = "抽不出 body 也抽不出 title"

_STORY_SHAPES = (
    ("link_data", "message", "name", ("description", "caption")),
    ("video_data", "message", "title", ("link_description",)),
    ("photo_data", "caption", None, ()),
    ("template_data", "message", "name", ("description", "caption", "link_description")),
)


def _creative_variants(creative: dict) -> tuple[list[dict], str]:
    """從一則素材抽出 body／title／call_to_action_type／media_ids 各不相同的變體，
    依序試四種已知形狀，抽得到第一種就不再往下試（A4，票 S2b）。

    回傳 `(變體清單, 保險絲理由)`：抽得到就是 `(變體, "")`，抽不到就是 `([], 理由)`。
    **理由跟著回傳值走，不由呼叫端寫死**（票 S2b 完整性審查，2026-08-31）：下面有四條
    各自不同的路會回空清單，`_ad_fact_card()` 原本不論走哪一條都印同一句「抽不出 body
    也抽不出 title」，真帳號 34 次觸發裡 27 次那句話被緊接著印出的 JSON 當場推翻。

    1. `object_story_spec`（單一素材：`link_data`／`video_data`／`photo_data`／
       `template_data` 四選一，見 `_STORY_SHAPES`——`template_data` 是完整性審查第二輪
       才補上的第四種，真帳號 158 則素材裡 25 則是它，漏掉它輪播卡片文案會整批消失；
       `link_data`／`template_data` 帶 `child_attachments` 是輪播——每張卡片本身
       也是一個變體，逐字照登，不是只印外層那一句主文案）。
    2. `asset_feed_spec` 加 `asset_customization_rules`（Advantage+：每條規則對應一組
       版位客製化，同一份文案常常被好幾條規則共用——這裡按 (body, title) 分組，回傳
       `placement_count` 講清楚幾條規則共用同一份文案，不是每條規則各印一次一份一樣
       的文案（票明講：「say how many placements shared each variant — do not
       silently drop the count」）。**任何一條規則對不到 body 也對不到 title，代表
       這組規則用的 label 對應方式不是這裡認得的那種——整組規則回空清單，交給保險絲
       送原始 JSON，不要只送對得到的那幾條、悄悄漏掉對不到的**（審查回應：content／
       gate 審查都點名部分規則消失會讓 placement_count 講的數字是假的）。CTA 不進分組
       key——真帳號驗證過（完整性審查，2026-08-31）`asset_customization_rules` 逐條
       規則裡根本沒有 `call_to_action_label` 這個鍵，CTA 是整份 `call_to_action_types`
       共用一份，見下面讀它的那段註解。
    3. `asset_feed_spec` 有 `bodies`／`titles`，但沒有 `asset_customization_rules`——
       沒有規則就沒辦法配對「哪個 body 配哪個 title」，Meta 是投遞時才決定的，我們讀不
       出配對結果。回傳一則 `unpaired` 標記的紀錄（`_ad_fact_card()` 交給
       `_unpaired_variant_lines()` 印成兩份逐字清單＋一句配對規則的說明），不假裝配得
       出來、也不把「不知道」印成 `placement_count：1` 這種看似有意義的數字（完整性
       審查回應，2026-08-31：上一輪各自印成獨立變體，`title：（無）`／`media_ids：[]`／
       `placement_count：1` 全部是編出來的結構）。這是最常見的 Advantage+ 動態素材形狀
       （沒有做版位客製化的帳號，真帳號 158 則素材裡 92 則是這個形狀），漏接這種形狀
       會讓每一則這樣的廣告都退去保險絲、97 KB 目標在這種帳號上完全達不到（審查回應：
       gate 審查點名）。
    4. 素材最外層的 `body`／`title`／`call_to_action_type`（最舊、最簡單的形狀）。

    四種都抽不出 body 也抽不出 title，回空清單——呼叫端看到空清單就觸發保險絲，把這則
    素材的原始 JSON 原封不動送出去，不臆測、不用摘要頂替（票 S2b A4）。

    **`object_story_spec` 跟 `asset_feed_spec` 兩邊都帶文案，也算「沒預期到的形狀」**：
    Advantage+ 素材強化疊在一份基礎素材上時，Meta 可能兩邊都給——這裡認得的四種形狀
    互斥，沒有「先印 object_story_spec 那份、asset_feed_spec 那幾份文案不算」這種規則，
    真遇到這樣的素材，只抽第一種會讓 `asset_feed_spec` 那幾份文案悄悄消失（審查回應：
    constitution 審查點名）。回空清單讓保險絲送整包，不臆測該印哪一半。

    `asset_customization_rules` 的版位客製化欄位已經拿真帳號 368741390835357 的
    23 則素材逐欄位驗證過（完整性審查，2026-08-31：`body_label`／`title_label`／
    `image_label`／`video_label` 都是帶 `name`／`id` 的物件，`descriptions`／
    `call_to_action_types` 不分版位、整份共用，見 `_resolve_labelled_asset` 跟下面
    讀 `cta_types`／`descriptions` 那兩段註解）——這支函式的安全網仍然是上面那條
    保險絲：真遇到這裡沒預期到的形狀，不會生出錯的文案，只會退回送原始 JSON。"""
    story = creative.get("object_story_spec") or {}
    feed = creative.get("asset_feed_spec") or {}
    feed_has_copy = bool(feed.get("bodies") or feed.get("titles"))
    for key, body_field, title_field, extra_fields in _STORY_SHAPES:
        data = story.get(key)
        if not isinstance(data, dict):
            continue
        body = data.get(body_field)
        title = data.get(title_field) if title_field else None
        child_attachments = data.get("child_attachments") or ()
        # 完整性審查第二輪點名：原本這裡只看外層自己的 body／title，帶輪播卡片
        # （`child_attachments`）卻外層兩個欄位都沒給的形狀（真帳號驗證過：
        # link_data 只有 link／image_hash／call_to_action，文案全部在卡片裡）會直接
        # `continue` 跳過——`child_attachments` 迴圈（下面）根本沒機會跑到，9～10 則
        # 輪播卡片文案整個消失，保險絲也不會點火。「這個形狀有沒有讀到東西」要連
        # child_attachments 一起算，不能只看外層兩個欄位。
        if not (body or title or child_attachments):
            continue
        # ponytail: 兩套編碼都帶文案就整包送原始 JSON，上限是貴——真帳號 34 次保險絲裡有
        # 一部分是這條，每次多送整包素材 JSON。升級路徑不是寫更聰明的猜法，是等一條成文
        # 規則說「兩邊都有時哪一半算數」（票 S2b 明講不自己發明），有了才改成只送那一半。
        if feed_has_copy:
            return [], _FUSE_BOTH_ENCODINGS
        # CTA 這個形狀自己沒給時退回素材最外層的 `call_to_action_type`——完整性審查
        # 第二輪點名：真帳號 86/158 則廣告的 CTA 只在素材最外層有，object_story_spec
        # 跟 asset_feed_spec 兩邊都沒有，原本印「（無）」等於斷言 Meta 沒給 CTA，其實只是
        # 這裡沒往外層多看一眼。
        top_level_cta = creative.get("call_to_action_type")
        media_ids = [v for v in (data.get("image_hash"), data.get("video_id")) if v]
        extra = {f: data[f] for f in extra_fields if data.get(f)}
        variants = [{
            "body": body, "title": title,
            "call_to_action_type": (data.get("call_to_action") or {}).get("type") or top_level_cta,
            "media_ids": media_ids, "ad_format": key, "placement_count": 1,
            "extra": extra,
        }]
        for child in child_attachments:
            if not isinstance(child, dict):
                continue
            child_media = [v for v in (child.get("image_hash"), child.get("video_id")) if v]
            variants.append({
                "body": child.get("description"), "title": child.get("name"),
                "call_to_action_type": (
                    (child.get("call_to_action") or {}).get("type") or top_level_cta
                ),
                "media_ids": child_media, "ad_format": f"{key}.child_attachment",
                "placement_count": 1, "extra": {},
            })
        return variants, ""

    bodies, titles = feed.get("bodies"), feed.get("titles")
    images, videos = feed.get("images"), feed.get("videos")
    rules = feed.get("asset_customization_rules")
    # A4 審查（完整性審查，2026-08-31）點名的 bug 2：這裡原本讀 `call_to_actions`，
    # 真帳號驗證過 Meta 從來不回這個鍵——`asset_customization_rules` 逐條規則裡也沒有
    # `call_to_action_label`（真帳號 4 條規則只帶 body_label／title_label／image_label／
    # video_label／link_url_label，見 `_resolve_labelled_asset` docstring 那個例子）。
    # CTA 不是逐版位客製化的個別素材，是整份 `asset_feed_spec` 共用一個
    # `call_to_action_types`（純字串陣列，不是帶 `adlabels` 的素材，不能送進
    # `_resolve_labelled_asset`）——只有一個就直接印那一個，真的不只一個才列出來
    # （這帳號 23 則用得到 rules 的素材，`call_to_action_types` 全部只有一項）。
    # `asset_feed_spec` 沒帶 `call_to_action_types` 時退回素材最外層的
    # `call_to_action_type`（完整性審查第二輪，2026-08-31：真帳號 86/158 則廣告是這種
    # 情形，原本印「（無）」是斷言 Meta 沒給 CTA，其實只是沒往外層多看一眼）。
    cta_types = feed.get("call_to_action_types") or ()
    if len(cta_types) == 1:
        cta_display = cta_types[0]
    elif cta_types:
        cta_display = "、".join(cta_types)
    else:
        cta_display = creative.get("call_to_action_type")
    # bug 2b：`descriptions` 本來完全沒讀，真帳號 77 則素材（23 則走 rules、54 則沒有）
    # 的這份逐字文案因此悄悄消失，保險絲還不會點火（因為 body 找到了）——票明講一句摘要
    # 都不算，何況整欄不見。真帳號的 `descriptions` 沒有 `adlabels`（跟 bodies／titles
    # 不同，不分版位），是整份共用，所以不比照 body／title 逐條規則配對，原封不動列進
    # `extra`（跟 `_STORY_SHAPES` 的 extra_fields 同一種「逐字照登不臆測配對」的做法）。
    descriptions = feed.get("descriptions")
    desc_texts = [
        d.get("text") for d in (descriptions or ()) if isinstance(d, dict) and d.get("text")
    ]
    if rules and (bodies or titles):
        grouped: dict[tuple, dict] = {}
        order: list[tuple] = []
        for rule in rules:
            body_asset = _resolve_labelled_asset(bodies, rule.get("body_label"))
            title_asset = _resolve_labelled_asset(titles, rule.get("title_label"))
            key = (
                body_asset.get("text") if body_asset else None,
                title_asset.get("text") if title_asset else None,
            )
            if key[0] is None and key[1] is None:
                # 這條規則的 label 對不到任何一份 body／title——整組規則回空清單讓
                # 保險絲接手，不要只印對得到的那幾條（見函式 docstring 第 2 點）。
                return [], _FUSE_RULE_UNMATCHED
            if key not in grouped:
                grouped[key] = {
                    "body": key[0], "title": key[1], "call_to_action_type": cta_display,
                    "media_ids": [],
                    "ad_format": ",".join(feed.get("ad_formats") or ()) or None,
                    "placement_count": 0,
                    "extra": ({"descriptions": list(desc_texts)} if desc_texts else {}),
                }
                order.append(key)
            image_asset = _resolve_labelled_asset(images, rule.get("image_label"))
            video_asset = _resolve_labelled_asset(videos, rule.get("video_label"))
            # 同一份文案被好幾條規則共用時，每條規則常常各自配不同的版位圖片／影片
            # （手機版 vs 桌面版 vs 限時動態）——只留第一條規則的 media_ids 會讓其他
            # 版位用的素材悄悄消失（審查回應：content 審查點名），改成聯集、保留順序。
            for asset_id in (
                image_asset.get("hash") if image_asset else None,
                video_asset.get("video_id") if video_asset else None,
            ):
                if asset_id and asset_id not in grouped[key]["media_ids"]:
                    grouped[key]["media_ids"].append(asset_id)
            grouped[key]["placement_count"] += 1
        variants = list(grouped[k] for k in order)
        if variants:
            # 完整性審查第二輪點名的 bug 3：真帳號 368741390835357 驗證過，同一則素材
            # 底下每一份 body／title 資產的 `adlabels` 常常帶著「這則素材全部規則」的
            # label（不是各自一條），`_resolve_labelled_asset()` first-match-wins 因此
            # 對每條規則都解析到同一份 bodies[0]／titles[0]，全部規則收斂成一組——
            # 4 條規則各自要送的其他 4 份文案（帳號全域 13/39 bodies、12/38 titles）
            # 就這樣悄悄不見，`placement_count` 印出來的數字也是假的（4 條規則共用
            # 一份文案，其實是同一份文案被解析錯成 4 條規則的結果）。這裡不試著把
            # label 解析得更聰明——真帳號的 adlabels 形狀含糊到猜不出真正配對，改成
            # 斷言涵蓋率：分組後如果還有 body／title 資產的文字沒被任何一組用到，代表
            # 這裡的 label 解析法讀不懂這則素材的真配對，整組回空清單讓保險絲送原始
            # JSON（延續函式 docstring 第 2 點「對不到就不要只送對得到的那幾條」的
            # 同一條規矩，這裡是它在「對得到、但對錯」這個新形狀下的樣子）。
            used_bodies = {key[0] for key in grouped}
            used_titles = {key[1] for key in grouped}
            all_body_texts = {
                a.get("text") for a in (bodies or ())
                if isinstance(a, dict) and a.get("text")
            }
            all_title_texts = {
                a.get("text") for a in (titles or ())
                if isinstance(a, dict) and a.get("text")
            }
            # ponytail: 涵蓋率對不上就整包送原始 JSON，上限一樣是貴。升級路徑是一份讀得懂
            # 這個帳號 `adlabels` 真實配對規則的解析法（今天的形狀含糊到猜不出來），不是
            # 放寬這條斷言——放寬等於讓 `placement_count` 繼續印假數字。
            if (all_body_texts - used_bodies) or (all_title_texts - used_titles):
                return [], _FUSE_ASSET_UNUSED
            return variants, ""

    if not rules and (bodies or titles):
        # 沒有 `asset_customization_rules` 就沒辦法配對「哪個 body 配哪個 title」
        # （見函式 docstring 第 3 點）——上一輪把每個 body／title 各自印成一個
        # `{"body":..., "title": None, "media_ids": [], "placement_count": 1}` 的
        # 「變體」，看起來像一則獨立廣告，其實 title：（無）／media_ids：[]／
        # placement_count：1 全部是編出來的結構：這裡的每個 body 跟每個 title 根本
        # 不是配對出來的一則廣告，是 Meta 在投遞時才配對、我們讀不出配對結果的兩份
        # 獨立清單（完整性審查回應，2026-08-31：真帳號 158 則素材裡 92 則落在這個
        # 形狀，是所有形狀裡最常見的一種）。改成回傳一個 `unpaired` 標記的紀錄，讓
        # `_ad_fact_card()` 老實印成兩份清單＋一句配對規則的說明，不臆測配對、也不再
        # 印一句摘要頂替真話（票明講：a summarised quote is not a quote，這條線也擋
        # 「用結構暗示一個不存在的配對」）。`descriptions` 一樣沒有規則可配對，跟
        # `_STORY_SHAPES` 的 extra_fields 同一種做法，原封不動掛進 `extra`。
        ad_format = ",".join(feed.get("ad_formats") or ()) or None
        body_texts = [
            asset.get("text") for asset in (bodies or ())
            if isinstance(asset, dict) and asset.get("text")
        ]
        title_texts = [
            asset.get("text") for asset in (titles or ())
            if isinstance(asset, dict) and asset.get("text")
        ]
        # `asset_feed_spec` 常常只給 bodies 沒給 titles（或反過來）——素材最外層的
        # `body`／`title` 這兩個欄位在這個帳號會回聲那一份沒被 feed 收進去的內容
        # （完整性審查第二輪，2026-08-31：真帳號 35/158 則廣告是「有 bodies 沒
        # titles」，最外層 `title` 就是那句真的標題）。這裡沒有規則可配對、也不需要
        # 配對——單獨一份文字沒有「跟誰配對」的問題，原封不動補進去，不然
        # `_unpaired_variant_lines()` 印出的 `titles（0）` 會是一句假話：Meta 明明給了
        # 標題，只是沒放進 feed 那份清單。
        if not body_texts and creative.get("body"):
            body_texts = [creative["body"]]
        if not title_texts and creative.get("title"):
            title_texts = [creative["title"]]
        if body_texts or title_texts:
            # A4 那句「plus media ids」在這條路上從來沒被兌現過（票 S2b 完整性審查，
            # 2026-08-31：真帳號 158 則素材有 69 則走這條 `unpaired` 路，一個 media id
            # 都沒印，而 65 則的 media id 就躺在同一包 payload 的 `images`／`videos`
            # 裡）。配不出「哪一個 media 配哪一句文案」不是「沒有 media」——前者是這條路
            # 本來就承認的無知，後者是一句假話。配對讀不出來就照實說配對讀不出來，
            # media 本身照樣逐一列出來，比照 bodies／titles 兩份清單同一個做法。
            media_ids = _feed_media_ids(feed, creative)
            return [{
                "unpaired": True, "bodies": body_texts, "titles": title_texts,
                "call_to_action_type": cta_display, "ad_format": ad_format,
                "media_ids": media_ids,
                "extra": ({"descriptions": list(desc_texts)} if desc_texts else {}),
            }], ""

    body, title = creative.get("body"), creative.get("title")
    if body or title:
        media_ids = [v for v in (creative.get("image_hash"), creative.get("video_id")) if v]
        return [{
            "body": body, "title": title,
            "call_to_action_type": creative.get("call_to_action_type"),
            "media_ids": media_ids, "ad_format": None, "placement_count": 1, "extra": {},
        }], ""
    return [], _FUSE_NO_COPY


def _feed_media_ids(feed: dict, creative: dict) -> list[str]:
    """`asset_feed_spec` 的 `images`／`videos` 兩份清單裡全部的 media id，去重、保留順序；
    兩份都空時退回素材最外層的 `image_hash`／`video_id`（跟 `bodies`／`titles` 退回最外層
    `body`／`title` 是同一個理由：feed 沒收進去的那一份常常只在最外層有）。

    這裡**不**試著把 media 配到某一句文案上——走到這條路就是因為這則素材沒有
    `asset_customization_rules`，沒有規則就沒有配對可讀（見 `_creative_variants()`
    docstring 第 3 點）。列出來的是「這則素材用到的全部 media」，不是「第 N 句文案用的
    media」。"""
    ids: list[str] = []
    for assets, key in ((feed.get("images"), "hash"), (feed.get("videos"), "video_id")):
        for asset in assets or ():
            asset_id = asset.get(key) if isinstance(asset, dict) else None
            if asset_id and asset_id not in ids:
                ids.append(asset_id)
    if not ids:
        ids = [v for v in (creative.get("image_hash"), creative.get("video_id")) if v]
    return ids


def _unpaired_variant_lines(variant: dict) -> list[str]:
    """`_creative_variants()` 第 3 種形狀（`asset_feed_spec` 有 `bodies`／`titles`
    但沒有 `asset_customization_rules`）回傳的 `unpaired` 紀錄，印成兩份逐字清單，
    不臆測配對（完整性審查回應，2026-08-31，真帳號 92/158 則素材是這個形狀）。

    只有 bodies／titles 兩邊都非空才印「Meta 在投遞時才配對」那句說明——只有一邊有
    內容時（例如只有 titles、沒有 bodies）根本沒有配對可言，印那句說明會是一句
    多餘的猜測。"""
    bodies = variant.get("bodies") or []
    titles = variant.get("titles") or []
    lines = []
    if bodies and titles:
        lines.append("  Meta 在投遞時才配對這些 body 與 title，這裡讀不出哪一句配哪一句：")
    lines.append(f"  bodies（{len(bodies)}）：")
    lines.extend(f"    - {text}" for text in bodies)
    lines.append(f"  titles（{len(titles)}）：")
    lines.extend(f"    - {text}" for text in titles)
    lines.append(f"  call_to_action_type：{_blank_or(variant.get('call_to_action_type'))}")
    lines.append(f"  ad_format：{_blank_or(variant.get('ad_format'))}")
    # media 跟 bodies／titles 一樣讀不出配對，所以印成第三份清單而不是掛在某一句文案下面
    # （見 `_feed_media_ids()`）。空清單照樣印一行 `media_ids（0）`：這則素材的 payload
    # 裡真的一個 media 都沒有，也是一件事實，跟「有但沒印」要分得開。
    media_ids = variant.get("media_ids") or []
    lines.append(f"  media_ids（{len(media_ids)}，讀不出哪一個配哪一句）：{media_ids}")
    lines.extend(_extra_lines(variant.get("extra")))
    return lines


def _blank_or(value):
    """`_ad_fact_card()` 專用：一個欄位 Meta 真的沒給（`None`）跟「Meta 給了空字串」是
    兩件不同的事，但印出 Python 的 `None` 字面值會被誤讀成「有這個欄位、值真的叫
    None」——跟這整份切片一路守的 null≠0／null≠空字串是同一條線，這裡是它在印文字這一步
    的樣子（審查回應：gate 審查點名 `body：None` 這種輸出）。"""
    return "（無）" if value is None else value


def _extra_lines(extra: dict | None) -> list[str]:
    """`_unpaired_variant_lines()` 跟 `_ad_fact_card()` 都要把 `extra`（`descriptions`
    這類逐字文案）印成文字——完整性審查第二輪點名：兩處原本都是
    `f"  {field}：{value}"`，`value` 是清單（`descriptions` 就是）時直接塞進 f-string
    會印成 Python 的 `repr()`：方括號、引號、換行字元被跳脫成看得見的 `\\n`，帶換行的
    真實文案因此不是逐字（票明講：a summarised quote is not a quote，跳脫符號也是一種
    改寫）。清單值比照 `_unpaired_variant_lines()` 印 bodies／titles 的樣子：一行標頭
    ＋每則一行 `- 文字`；非清單值照舊一行印完。兩處共用同一支，不是各自修一次——同一個
    bug 在兩個地方，修一次就夠。"""
    lines = []
    for field, value in (extra or {}).items():
        if isinstance(value, list):
            lines.append(f"  {field}：")
            lines.extend(f"    - {text}" for text in value)
        else:
            lines.append(f"  {field}：{value}")
    return lines


def _ad_fact_card(ad: dict, creatives: list[dict]) -> str:
    """A4（票 S2b）：一則廣告一張卡，逐一素材抽變體。文案（body／title）逐字照登，絕不
    改寫、截斷、摘要（票明講：a summarised quote is not a quote）——**保險絲**：一則
    素材抽不出 body 也抽不出 title，代表 Meta 回了沒預期到的形狀，這則素材的原始 JSON
    原封不動印出來，不是靜靜漏掉（票 S2b A4，三個獨立審查者都要求這條）。

    `effective_status` 加在第一行：審查回應補回——PAUSED／DISAPPROVED 的廣告跟正在跑的
    廣告，A4 之前卡片長得一模一樣，涵蓋範圍那段報出來的缺口沒有欄位可以解釋「是人關掉
    的」還是「投遞真的崩了」。"""
    lines = [f"- [{ad.get('id')}] {ad.get('name', '')}（{ad.get('effective_status', '')}）"]
    for creative in creatives:
        variants, fuse_reason = _creative_variants(creative)
        if not variants:
            # 理由由 `_creative_variants()` 一起回傳，不在這裡寫死（票 S2b 完整性審查，
            # 2026-08-31：四條路共用一句「抽不出 body 也抽不出 title」，真帳號 34 次觸發
            # 裡 27 次緊接著印出的 JSON 就含 body，那句話當場被自己的下一行推翻）。
            lines.append(
                f"  保險絲觸發（{fuse_reason}），原始素材 JSON 原封送出："
                + json.dumps(creative, ensure_ascii=False)
            )
            continue
        for variant in variants:
            if variant.get("unpaired"):
                lines.extend(_unpaired_variant_lines(variant))
                continue
            lines.append(f"  body：{_blank_or(variant['body'])}")
            lines.append(f"  title：{_blank_or(variant['title'])}")
            lines.append(f"  call_to_action_type：{_blank_or(variant['call_to_action_type'])}")
            lines.append(f"  ad_format：{_blank_or(variant['ad_format'])}")
            lines.append(f"  media_ids：{variant['media_ids']}")
            lines.append(f"  共用這份文案的版位規則數：{variant['placement_count']}")
            lines.extend(_extra_lines(variant.get("extra")))
    return "\n".join(lines)
