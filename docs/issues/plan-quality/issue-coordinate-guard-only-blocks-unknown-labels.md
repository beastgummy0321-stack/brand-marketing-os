# 判讀的座標守門擋得住「不存在的座標」，擋不住「這輪零花費的座標」

Status: 開著——票 01 的獨立審查（2026-09-06）抓到，判 note 不判 reject，理由見下。

## 成因

`app/schedule/diagnosis.py:193-219`（`_valid_suggestions`）用 `repository.list_coordinates()`
建 `label_to_key` 對照表——那是**這個品牌註冊過的全部座標**（`brd_bughunt` 光 `angle` 一個維度
就有 35 個種子標籤），不是**這一輪壓縮表格裡真的印出來、真的有花費的那幾個**。

於是：
- 代理憑空發明一個系統裡沒有的座標名字 → 擋得住（查不到 key，整條丟掉）。
- 代理引用一個**真實存在、但這一輪零花費**的座標，再編一段像樣的 `evidence` 與 `impact_spend`
  → **擋不住**，那條會一路走進收斂、排序、畫面。

現在擋著這件事的只有 `diagnosis.py:181,187-189` 的 prompt 措辭（「只准對上面表格裡已經出現過的
座標值下判斷」「不要硬掰」）。

## 影響

這個模組自己的契約頁就記著一條實測教訓：`docs/contracts/schedule.md`
「Position in the prompt decides whether an instruction runs; wording does not」——T8b 那次換三次
措辭都沒用、換位置才有用。同一個模組已經證明過「只靠 prompt 措辭」不可靠，這裡正好就是這麼做的。

2026-09-06 實際跑的那一輪沒有踩到（5 條建議全部對應真的有花費的座標），但程式碼層面這條路開著。
真踩到時，使用者會看到一條有頭有尾、數字卻是編的建議，而且可以按「採用」把它變成規則卡。

## 為什麼票 01 沒有當場修

票 01 原文寫的是「`coordinate_key` 對不上**這個品牌現有座標**的那一條整條丟掉」——實作照字面做了，
不牴觸票面；沒有任何 done-check 測到這個情境；也不屬於四類 route C（schema／模組邊界／金流／
權限隔離）之一。所以是 note 不是 reject（`agent-brief.md` 的三判決規則）。

## 修法（便宜）

`_valid_suggestions()` 的對照表改成用**這一輪 `compress()` 實際印出來的座標值**建
（`performance` 的輸出裡每個維度的 `values[].label` 就是那份清單），而不是整個品牌的座標庫。
零花費的座標本來就不在表格裡，代理引用它就會被丟掉。

`app/schedule/diagnosis.py:193`
