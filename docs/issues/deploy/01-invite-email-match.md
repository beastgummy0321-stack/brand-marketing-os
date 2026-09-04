# 01 — accept_invite 只接受被邀請的那個信箱

Route C（權限／租戶隔離）。ADR 0061 是這張票的裁決來源；票與 ADR 衝突時 ADR 贏。
不動 schema，不動 migration，不動前端。

## What

`POST /api/identity/invites/{token}/accept`（`app/identity/routes.py:152`）在既有的三道檢查
（找不到 → 404、已用過或過期 → 410）之後，加第四道：**登入者的 email 必須等於 `org_invite.email`**，
不符就回 403，且**不得寫入任何 membership**。

比對規則（ADR 0061）：兩邊各做 `.strip().lower()` 後比較；登入者 email 為空字串時一律不符。
檢查順序不變：找不到 → 已用／過期 → email 不符。

`repo.get_invite_by_token` 已經把 `email` 一起讀回來（`app/identity/repository.py:139-146`），
不必改 repository。

成功（不變）：

```json
{"org": {"id": "org_bughunt", "name": "Bug Hunt", "kind": "company", "role": "member"}}
```

email 不符（新增）— HTTP 403，走 `app/main.py` 既有的錯誤信封：

```json
{"error": {"code": "invite_not_yours", "message": "這張邀請不是發給你現在登入的帳號的。請用收到邀請信的那個信箱登入，再點一次連結。"}}
```

訊息裡**不得**出現被邀請的信箱地址（ADR 0061）。錯誤用 `app.shared.web` 既有的 `Forbidden(msg, code=...)`，
不新增例外類別（`forbidden_org` 是同一個用法的既有先例）。

前端 `AcceptInvitePage.tsx` 直接顯示後端 `error.message`，所以**前端 diff 必須為零**。

## How we know it's done

1. 新測試 `test_invite_accepted_by_wrong_email_is_403`（加在 `app/tests/test_identity_orgs.py`）：
   owner 開一張給 `invitee@example.com` 的邀請 → 用 `mint_hs256(email="stranger@example.com")`
   的 token 打 accept → 斷言 `403`、`body["error"]["code"] == "invite_not_yours"`、
   且 `identity_repo.get_membership(web.conn, org_id, stranger_id) is None`（沒有偷偷加入）。
   **這條必須先證紅**：在還沒改 code 的樹上跑一次，看到它失敗（會拿到 200），才算數。
2. 大小寫／空白不擋人：同一測試檔加 `test_invite_accepted_with_different_case_email_is_200`——
   邀請 `Invitee@Example.com`，登入者 email `invitee@example.com` → `200`，membership 建立。
3. 既有兩條測試改成用被邀請的信箱（它們現在用不同信箱卻斷言成功，是舊行為的化石，不是決定）：
   - `test_invite_create_and_accept_local_returns_accept_url`（`:101`）：`mint_hs256` 的 email
     改成 `invitee@example.com`，其餘斷言不動，仍要 `200`。
   - `test_invite_accept_twice_is_410`（`:133`）：**兩次都用 `twice@example.com`**、user_id 不同 →
     第一次 `200`、第二次仍要 `410`（不是 403）。這條就是「已用過先於身分」順序的守門員。
4. 機器閘門，逐行照跑：
   - `uv run ruff check app`
   - `uv run pyright`
   - `uv run pytest app/tests/test_identity_orgs.py -q`
   - `cd frontend && npm run build`
   - `cd frontend && npm run e2e`（前提 `supabase start`；自己起 8720 後端跑完收掉）
5. `git diff --name-only` 的結果必須只有 `app/identity/routes.py` 與
   `app/tests/test_identity_orgs.py` 兩個檔（見下一節）。前端出現任何 diff ＝ 違約，停下回報。

## Shared files touched

以下四個名字（`accept_invite`、`AcceptInvitePage`、`accept-invite`、`invite_gone`）各跑一次
全 repo、不限目錄、不限副檔名的搜尋，命中原樣貼在這裡（排除 `.git/`、`node_modules/`、
`.scratch/`、`frontend/dist/`）。**這張票只准改前兩個檔**，其餘是「動了要先回報」的相關者。

```
### accept_invite
./app/identity/repository.py:148:def accept_invite(
./app/identity/routes.py:153:def accept_invite(request: Request, token: str):
./app/identity/routes.py:160:    repo.accept_invite(web.conn, invite["id"], actor.user_id, invite["org_id"], invite["role"])
./docs/issues/deploy/issue-invite-link-bearer.md:4:關聯：`app/identity/routes.py` accept_invite；前端 `AcceptInvitePage`。
./docs/issues/deploy/issue-invite-link-bearer.md:6:成因：accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟。
./docs/issues/deploy/spec.md:13:1. `issue-invite-link-bearer.md` — route C（權限）：accept_invite 比對 email＋前端加確認步驟。
### AcceptInvitePage
./docs/issues/deploy/issue-invite-link-bearer.md:4:關聯：`app/identity/routes.py` accept_invite；前端 `AcceptInvitePage`。
./docs/issues/deploy/issue-invite-link-bearer.md:6:成因：accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟。
./frontend/src/App.tsx:6:import { AcceptInvitePage } from "@/components/auth/AcceptInvitePage";
./frontend/src/App.tsx:39:      <Route path="/accept-invite" element={<AcceptInvitePage />} />
./frontend/src/components/auth/AcceptInvitePage.tsx:23:export function AcceptInvitePage() {
./frontend/src/lib/metaApi.ts:4: * frontend/src/components/auth/AcceptInvitePage.tsx 已經在用的解析方式，不要自己
### accept-invite
./.playwright-mcp/page-2026-08-28T05-16-37-604Z.yml:21:              - textbox [ref=f2e76]: http://localhost:8710/app/accept-invite?token=8OZHtuX9nkA2naI0eAWVrOT80KhCsy_3MjQdZsB95Os
./.playwright-mcp/page-2026-08-28T05-18-50-845Z.yml:21:              - textbox [ref=f5e90]: http://localhost:8710/app/accept-invite?token=yEhbYYeBxs_L-m-qbkNjVKXrcy--6-6Yf_Y78v_Iwtg
./app/identity/routes.py:148:        accept_url=f"/app/accept-invite?token={invite['token']}" if local else None,
./app/tests/test_identity_orgs.py:114:            body["accept_url"].startswith("/app/accept-invite?token="),
./docs/adr/0051-the-interface-is-a-dashboard-not-a-document.md:126:  route. Built as `frontend/e2e/width-overflow.spec.ts`, 14 routes (all but `/accept-invite`,
./frontend/e2e/width-overflow.spec.ts:20: * `/accept-invite` 不在這 13 條路由裡：它要另一個角色先發邀請信才進得去，
./frontend/e2e/width-overflow.spec.ts:22: * 14 條路由（`App.tsx`）扣掉 `/accept-invite`，共測 13 條。
./frontend/e2e/width-overflow.spec.ts:25:test("14 條路由（扣 /accept-invite）在 1280 寬不橫向溢出", async ({ page }) => {
./frontend/src/App.tsx:39:      <Route path="/accept-invite" element={<AcceptInvitePage />} />
./frontend/src/App.tsx:58:/** 登入守門（票 03-2）：包住除了 `/login`／`/accept-invite` 以外的每一條路由（layout
./frontend/src/components/auth/AcceptInvitePage.tsx:19:/** 接受邀請頁（票 03-2）：路由 `/accept-invite?token=…`（`App.tsx`）。刻意不掛在
./frontend/src/lib/http.test.ts:127:    window.history.pushState({}, "", "/app/accept-invite?token=abc123");
./frontend/src/lib/http.test.ts:132:    expect(takePendingPath()).toBe("/accept-invite?token=abc123");
./frontend/src/lib/http.test.ts:142:      JSON.stringify({ path: "/accept-invite?token=abc123", at: Date.now() - 11 * 60 * 1000 }),
./frontend/src/lib/http.test.ts:147:    sessionStorage.setItem("pendingPath", "/accept-invite?token=abc123"); // 舊格式：純字串
### invite_gone
./app/identity/routes.py:159:        raise ApiError(410, "invite_gone", "這張邀請已經用過或過期了。")
```

沒有任何名字被刪除或改名，所以命中清單裡除了這張票自己的文件外，沒有需要同步修改的呼叫端。
`docs/issues/deploy/issue-invite-link-bearer.md` 已由本票取代（開票時刪除），
`docs/issues/deploy/spec.md` 第 13 行由主對話台改寫，不屬實作者的工作。

## Contradiction check

會互相打架的是 done-check 3 的兩條：

- 「已用過的邀請回 **410**」（`test_invite_accept_twice_is_410`）
- 「email 不符回 **403**」（`test_invite_accepted_by_wrong_email_is_403`）

**能同時命中兩條的輸入**：一張已經被接受過的邀請，由一個 email 不符的人再點一次。
兩條 done-check 都主張自己的狀態碼，讀法不同就會有兩種都算過的實作。

**裁決（ADR 0061，實作者不得自行改判）**：先答 410，再答 403。所以
`test_invite_accept_twice_is_410` 的第二次嘗試刻意用**相同 email、不同 user_id**——
把「已用過先於身分」這個順序釘在測試上，而不是留給讀法。
若實作者把 email 檢查移到 410 檢查之前，這條測試會紅，那就是它該紅。
