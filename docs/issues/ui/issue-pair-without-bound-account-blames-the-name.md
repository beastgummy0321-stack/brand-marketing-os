# 沒綁廣告帳戶就按「配對」，系統說「在 Meta 上找不到」——它其實根本沒去找

Status: open（drill 2026-09-09，Vivian step 8／8b，小杰 step 9 operator 複驗）。
**2／3 角色撞到**：Vivian 與小杰都在「權杖已連、帳戶清單出得來、品牌的勾選框沒勾」的狀態下
按了配對。跟 `issue-bind-success-is-silent.md` 不同——那條講成功沒有字，這條講**失敗講錯話**。

成因：`app/schedule/binding.py:135` 先拿 `meta_repo.bound_account_ids_for_brand()`，
這個品牌一個帳戶都沒綁時它回空清單；`app/meta/repository.py:311-312` 的
`campaign_ids_by_exact_name()` 開頭就是 `if not ad_account_ids: return []`——**一次 Graph 都不打**。
零筆回到 `binding.py:154`，走 `_failure_reason()` 的「找不到」分支，於是每一個第一層節點都拿到
「「<名字>」在 Meta 上找不到」，第二層第三層整批不比對。

畫面因此把使用者導向錯的動作：訊息接著說「名稱要一字不差（區分大小寫，前後空白也算）」——
Vivian 照做去比對名字，真正要做的是回設定頁把品牌的勾選框勾起來。她的原話：
> 「按了配對但沒反應……原來上次配對沒效果是因為我沒先綁帳戶！」

她是自己反覆試綁定／解綁兩次才推出來的（step 8b 的對照表），不是系統告訴她的。
小杰更慘：帳戶 0、綁定 0，一路核准完檔期都沒被擋。

`file:line`：`app/schedule/binding.py:135`（取帳戶清單）、`app/meta/repository.py:311-312`
（空清單直接回空）、`app/schedule/binding.py:105-109`（`_failure_reason()` 的兩種說法）、
`frontend/src/components/schedule/CampaignTree.tsx`（配對按鈕）。

做法（未裁決）：最小一刀在 `_run_bind()` 進 `bind_tree()` 之前先問一次
`bound_account_ids_for_brand()`，空的就回一句自己的訊息「這個品牌還沒綁 Meta 廣告帳戶，
先到設定→Meta 廣告連線勾起來」＋連結，不要讓「找不到名字」那句出場。route A／B 邊界。
一併考慮：帳戶沒綁時把配對按鈕本身 disabled，跟 `issue-settings-detour-has-no-link.md`
的繞路問題是同一種形狀（畫面知道前置條件沒滿足，卻等使用者撞牆才講）。
