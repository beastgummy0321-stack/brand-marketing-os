-- numeric(14,2) 把不到半分錢的呼叫記成 0.00；每月花費上限（check_spend_cap →
-- settings.org_ai_spent_this_month）加總的就是這一欄，帳愈跑愈少。
-- 這是 ALTER 不是 CREATE：llm_task 是既有的 core 表，本票沒有建任何新表。
ALTER TABLE llm_task ALTER COLUMN cost TYPE numeric(14,6);
