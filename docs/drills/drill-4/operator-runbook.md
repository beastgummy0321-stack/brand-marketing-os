# 操作者手冊（Drill 4）

後端：`scripts.drill.serve --port 8710`（替身已裝）＋ `app.worker`。替身狀態：`.scratch/drill/meta_state.json`。
DB：`docker exec supabase_db_marketing psql -U postgres -tAc "<sql>"`（需要 PATH 加 DockerDesktop）。
Python：`.venv/Scripts/python.exe -m scripts.drill.fake_meta <cmd>`（從 repo 根目錄跑；讀 .env）。

## 找到角色的 org / brand

```sql
select o.id org_id, b.id brand_id, b.name from brand b join org o on o.id=b.org_id order by b.created_at desc limit 5;
```
（帳號 email → `auth.users` → `org_member`，視 schema；最簡單是用 brand.name 對角色。）

## 每站證據查詢（把結果貼進 <persona>/evidence.md）

- Goal：`select id,name,goal_text,objective,success_metric,success_target,success_basis,start_date,end_date,status,context_json->'field_sources' fs from ads_campaign where brand_id='<b>' order by created_at;`
- Decision：`select task_type,status,usage_json->>'input_tokens' i,usage_json->>'output_tokens' o,created_at from llm_task where brand_id='<b>' order by created_at;`
  `select g.name,g.role,g.daily_budget,count(a.id) ads from ads_delivery_group g left join ads_ad a on a.group_id=g.id where g.campaign_id='<c>' group by 1,2,3;`
  → sum(daily)×days 應等於畫面總額。
- Production：`select id,approved_at,context_json->>'origin_label' from workbench_pack where brand_id='<b>';`
  `select name,asset_ready_source,asset_ready_at from ads_ad where campaign_id='<c>';`
- Execution：`select kind,target_kind,sync_state,approved_by,created_at from ads_action where campaign_id='<c>' order by created_at;`
  `select 'c',external_id,external_name,local_state from ads_campaign where id='<c>' union all select 'g',external_id,external_name,local_state from ads_delivery_group where campaign_id='<c>' union all select 'a',external_id,external_name,local_state from ads_ad where campaign_id='<c>';`
- Outcome：`select entity_kind,count(*),sum(spend),sum(purchases),sum(revenue),min(day),max(day) from ads_outcome_daily where campaign_id='<c>' group by 1;`
- Learning：`select id,confidence,sample_size,learning_text,source_cycle_id,learned_at from learning_ledger where brand_id='<b>' order by learned_at;`
  `select status,verdict,verdict_json,closed_at from ads_campaign where id='<c>';`
- Next Decision：`select budget_basis_json->'basis'->'learnings' from ads_campaign where id='<c2>';` 與兩圈的 `budget_basis_json->'strategy'->'allocation'`。

## 交接動作

1. 角色回報「發布清單出現」→ `fake_meta mirror <brand_id>`（第二圈用 `--append`）→ 叫角色回來按「配對」。
2. 角色回報「配對成功」→ `fake_meta spend <brand_id> --round 1 --days 7`（第二圈 `--round 2 --new-only`）
   → `fake_meta pull <org_id> --since <campaign start_date>` → 查 `meta_entity_spend` 有列 → 叫角色回來看成效。
   注意：角色的 Campaign 日期若在未來（例如 9 月但今天是 9/13），成效只會補到今天；spend 的 `today` 預設今天。
3. 結案後：查 learning_ledger；第二圈建立後查 basis.learnings。

## 演練中不修程式

任何缺陷：記進 `<persona>/findings.md`（症狀、截圖、查證 SQL 結果、初判成因），演練結束再由規劃師寫 backlog。
