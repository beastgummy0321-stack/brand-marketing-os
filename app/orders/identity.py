"""app/orders/identity.py — 顧客單向雜湊（GitHub issue #33，決策 0025 補遺第 2 點）。

只認訂購人（billing）email／電話，收件人（fulfillment）欄位一律不用於顧客識別。
正規化規則全系統唯一，就定義在這裡：email 小寫去空白；電話去除非數字字元，
+886／886 開頭一律換算回 0 開頭——0912 與 +886912 因此雜湊出同一個人。
email 正規化優先，缺 email 才退回電話；兩者都沒有就是查無此人（識別鍵回 None，
訂單仍然入庫，只是掛不到顧客身上——見 app/orders/repository.py）。

consistency_self_check() 是每次匯入前都要跑一次的一致性自檢：拿幾組已知等價寫法
（0912 vs +886912、大小寫 email）跑過正規化，雜湊值對不上就是規則本身壞了，
不是資料問題，直接 assert 炸掉擋下整批匯入（比對到一半才發現同一人變兩人更糟）。
"""

import hashlib
import re


def normalize_email(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return raw.strip().lower()


def normalize_phone(raw: str | None) -> str | None:
    """去符號、+886／886 開頭一律轉回 0 開頭的台灣手機格式。"""
    if not raw or not raw.strip():
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("886"):
        digits = "0" + digits[3:]
    return digits


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity_key(*, billing_email: str | None = None,
                  billing_phone: str | None = None) -> tuple:
    """回傳 (identity_hash, identity_type)；都沒有可用資料時回 (None, None)。"""
    email = normalize_email(billing_email)
    if email:
        return _hash(email), "email"
    phone = normalize_phone(billing_phone)
    if phone:
        return _hash(phone), "phone"
    return None, None


def consistency_self_check() -> None:
    """匯入一致性自檢：常見等價寫法必須雜湊出同一個人，規則壞了要在匯入前就擋下。"""
    assert normalize_phone("0912345678") == normalize_phone("+886912345678"), (
        "電話正規化規則壞了：0912345678 與 +886912345678 應該是同一個人")
    assert normalize_phone("0912345678") == normalize_phone("886912345678"), (
        "電話正規化規則壞了：0912345678 與 886912345678 應該是同一個人")
    assert normalize_email("A@Example.com") == normalize_email("a@example.com"), (
        "email 正規化規則壞了：大小寫應該是同一個人")


if __name__ == "__main__":
    consistency_self_check()
    print("identity self-check ok")
