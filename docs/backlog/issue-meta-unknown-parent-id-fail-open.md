# A Meta parent id nobody has ever bound still reaches Meta on this org's token

Status: known-residual — 票 06 收尾時由審查員量出並記下（2026-09-05）。今天打不到，未來多一個呼叫端就打得到。

成因：`app/meta/repository.py:335-356` 的 `_refuse_if_parent_owned_by_another_org` 是
**「確定是別人的就擋，沒紀錄的放行」**（fail-closed on conflict, fail-open on unknown）。
它查 `channel_entity_map` 有沒有把這個 `campaign_id`／`adset_id` 記成別的組織；查無紀錄就照舊
走到 Meta。

為什麼當初這樣做：要把「沒被證明屬於這個組織就拒絕」做到底，會撞到兩件事——
(1) `app/tests/test_meta_daily_spend.py:988-1007` `AdSetMatchUnreachableTest` 明確餵一個從沒被
任何人綁過的 `"camp-1"`，要求它照樣打到 Meta（票 06 done-check 3 指名這支不准改）；
(2) 這個資料庫沒有一張表存「Meta 的某個 id 屬於哪個組織」，要補只能多打一次 Meta API，
而票 06 已裁決不走那條（唯一相近的 insights 端點會漏掉沒花錢的實體）。

影響：今天為零。唯一的呼叫端 `app/schedule/binding.py` 的 `bind_tree` 會先 `upsert_binding`
把該列寫進 `channel_entity_map`、才遞迴進下一層，所以「查無紀錄」這條分支從現有路徑打不到；
而路由 `app/schedule/routes.py:427-430` 沒有 request body，塞不進外部 id。
真正會踩到的是**未來的第二個呼叫端**（補登腳本、後台工具、新路由）——它可以拿一個亂數 id
呼叫這兩支，於是用這個組織的 Meta 權杖去打一個不屬於任何人的 id。花的是 API 額度不是廣告費。

`file:line`：`app/meta/repository.py:335-356`、`:372-374`、`:404-406`；
`app/tests/test_meta_daily_spend.py:988-1007`、`:1041-1057`；`app/schedule/binding.py:99-143`。

要補的話（不是現在）：新增一張「Meta 實體 → 組織」的對照表，在名稱比對成功的當下就寫進去，
然後把猜擋改成「不在這張表裡就拒絕」。那是一張 route C schema 票，門檻是「真的多了第二個
呼叫端」——`docs/contracts/meta.md` 已逐字記下這個殘留。
