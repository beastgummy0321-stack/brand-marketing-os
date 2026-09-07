# 貼錯權限的 Meta 權杖，畫面只轉述 Graph 的原話，不說少了哪個權限

Status: 開著——2026-09-07 幫使用者接真帳號時撞到，卡在閉環第 ① 站，人不看程式碼是走不出去的。

## 成因

`app/meta/routes.py:56-72`（`connect_token`）先拿權杖去打 `graph.list_ad_accounts()`（`me/adaccounts`），
失敗就把 Meta 的訊息原樣接在後面：

```
Meta 拒絕了這個權杖：(#100) Unsupported get request. Please read the Graph API
documentation at https://developers.facebook.com/docs/graph-api
```

Meta 對「權杖有效、但沒有 `ads_read` 這個授權範圍」回的就是 `(#100) Unsupported get request`——
它不說少了什麼，只說這個請求不支援。所以使用者看到的字面意思是「網址打錯了」，實際原因是「權限沒勾」。

實測（`.env` 的 `META_MCP_TOKEN`，2026-09-07）：

```
GET /v21.0/debug_token → is_valid: true, type: USER, expires_at: 2026-11-03,
                          scopes: ["catalog_management", "business_management", "public_profile"]
GET /v21.0/me          → 200
GET /v21.0/me/adaccounts → (#100) Unsupported get request
```

權杖是好的、沒過期，就是沒有 `ads_read`。

## 影響

設定頁只寫「貼上 Meta 的存取權杖」（`frontend/src/components/settings/MetaSection.tsx:72`），
**沒有任何一個地方寫要哪些授權範圍**。使用者貼一把自己手上的權杖、拿到一句在講 Graph API 文件的
錯誤訊息，接下來只能猜。這是閉環第一站，猜不出來後面整條都走不了。

## 修法（便宜）

1. 錯誤訊息在 `code == 100` 時換一句自己的話：「這把權杖看不到廣告帳戶，通常是少了 `ads_read` 授權。」
   ——不要把 Graph 的原話當成給人看的訊息。
2. 貼權杖那個輸入框旁邊直接寫要哪些授權範圍。這一刀比第 1 條更值：訊息是事後補救，說明是事前避免。
3. 要更準的話可以先打 `debug_token` 拿 `scopes` 再判斷，但那是第二步——多一次網路往返，先做上面兩條看夠不夠。

`file:line`：`app/meta/routes.py:63-69`（原話轉述）、`frontend/src/components/settings/MetaSection.tsx:72`
（沒寫授權範圍的說明）。
