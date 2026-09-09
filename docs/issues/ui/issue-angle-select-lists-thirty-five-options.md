# 新工單的「切角」是 35 個選項的平坦下拉，新手不知道要選哪個

Status: open（drill 2026-09-09，阿明 step 8）。阿明整份逐欄位「看得懂嗎」清單裡
**唯一的 NO**（其餘全 YES）。欄位是選填，所以不擋人，但它是新手在這張表上唯一停下來的地方。

成因：`frontend/src/components/workbench/NewBriefPanel.tsx:216-228` 把
`dimension === "angle"` 且未停用的座標整批平鋪進一個原生 `<select>`，沒有分組、沒有搜尋、
沒有排序依據。種子資料就是 35 筆（`app/schedule/repository.py:7` 註明「the 35 angle seeds」），
加上「不指定」共 36 個 option；使用者還能自己再加（品牌智庫→創意座標→新增座標），只會更長。

`brand_coordinate` 本身有分類欄位——Vivian 在品牌智庫看到的篩選器就是用它做的
（Meta 特化／促銷／反向行銷／審美治癒／感性／權威／理性／視覺／買家視角／賣家視角，
她 step 4B 給了 **10 分**，說這是全站最亮眼的地方）。**同一份資料，在智庫那頁有分類，
在新工單這頁沒有。**

使用者的話（阿明）：
> 「切角：NO，40+ 個選項對初級使用者來說太複雜了。建議提供一些預設組合或分類。」
（他數的「40+」是估的，實際 35＋不指定。）

`file:line`：`frontend/src/components/workbench/NewBriefPanel.tsx:216-228`（平坦的 select）、
`app/schedule/repository.py:7`（35 筆種子）、品牌智庫那頁的分類篩選器（同一份 `brand_coordinate`）。

做法（未裁決）：最小一刀是把智庫那頁已經有的分類拿過來當 `<optgroup>`，一行改法、
不加元件、不引搜尋套件。要裁決的是要不要更進一步（依這個品牌的使用頻率排序、或直接只列
前段／中段／末端三組）——那需要先有投放歷史，現在做等於猜。route A。
