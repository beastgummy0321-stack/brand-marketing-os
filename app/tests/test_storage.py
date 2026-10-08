"""app/tests/test_storage.py — 票 storage-01: app.storage 的四函式，對真的本機 Storage 跑
（這個 repo 沒有 mock 的習慣，且 `supabase start` 本來就是整套測試的前提）。

守的是租戶邊界（每個函式的 org_id 守門）與 D9「失敗不能靜默」（get 對到不存在的物件要丟出
命名例外，delete_prefix 真的要把東西刪掉而不是回報成功卻什麼都沒刪）。

兩處「proven red once」在實作時手動驗證過（不留在測試碼裡，過程記在票的完成報告）：
  - `get()` 改成 `if resp.status_code == 404` 分支，這支測試會失敗（Storage 對缺物件回的是
    HTTP 400，不是 404——見模組檔頭「錯誤模型」）。
  - `delete_prefix()` 改成只用 `DELETE`+`{"prefixes":[prefix]}`（不先 list-v2），
    `test_delete_prefix_removes_objects_two_levels_deep` 會失敗在「刪完之後 get() 沒有丟
    NotFound」——因為 DELETE+prefixes 只匹配完整物件名稱，餵它前綴會 200 但什麼都沒刪。
"""

import unittest
import uuid
from unittest import mock

import httpx

import app.storage as storage


def _org() -> str:
    return f"org_storagetest_{uuid.uuid4().hex[:8]}"


class PutGetRoundTripTest(unittest.TestCase):
    def test_put_get_round_trips_bytes_and_content_type(self):
        org_id = _org()
        key = f"{org_id}/roundtrip/{uuid.uuid4().hex}.png"
        content = b"\x89PNG\r\n\x1a\nfake-png-bytes"
        self.addCleanup(storage.delete, org_id=org_id, key=key)

        returned_key = storage.put(
            org_id=org_id, key=key, filename="a.png", content=content, content_type="image/png"
        )
        self.assertEqual(returned_key, key)

        got_bytes, got_content_type = storage.get(org_id=org_id, key=key)
        self.assertEqual(got_bytes, content)
        self.assertEqual(got_content_type, "image/png")


class GetMissingKeyTest(unittest.TestCase):
    def test_get_on_missing_key_raises_not_found(self):
        org_id = _org()
        key = f"{org_id}/missing/{uuid.uuid4().hex}.png"
        with self.assertRaises(storage.NotFound):
            storage.get(org_id=org_id, key=key)


class GetTransportFailureTest(unittest.TestCase):
    def test_timeout_and_connection_failures_use_the_facade_error(self):
        for failure in (httpx.ReadTimeout, httpx.ConnectError):
            with self.subTest(failure=failure.__name__):
                with mock.patch.object(storage.httpx, "get", side_effect=failure("transport down")):
                    with self.assertRaises(storage.StorageError) as caught:
                        storage.get(org_id="org_transport", key="org_transport/original.png")
                self.assertNotIn("transport down", str(caught.exception))

    def test_tenant_guard_precedes_http_even_when_transport_is_down(self):
        with mock.patch.object(storage.httpx, "get", side_effect=httpx.ConnectError("down")) as get:
            with self.assertRaises(ValueError):
                storage.get(org_id="org_transport", key="another_org/original.png")
            get.assert_not_called()


class DeletePrefixTest(unittest.TestCase):
    def test_delete_prefix_removes_objects_two_levels_deep(self):
        org_id = _org()
        prefix = f"{org_id}/x/"
        key_a = f"{prefix}a/1.txt"
        key_b = f"{prefix}b/c/2.txt"
        storage.put(
            org_id=org_id, key=key_a, filename="1.txt", content=b"one", content_type="text/plain"
        )
        storage.put(
            org_id=org_id, key=key_b, filename="2.txt", content=b"two", content_type="text/plain"
        )

        storage.delete_prefix(org_id=org_id, prefix=prefix)

        with self.assertRaises(storage.NotFound):
            storage.get(org_id=org_id, key=key_a)
        with self.assertRaises(storage.NotFound):
            storage.get(org_id=org_id, key=key_b)


class TenantIsolationTest(unittest.TestCase):
    """四個函式各一個測試，不寫迴圈——這是租戶邊界，每一個都要各自守住（見 SPEC D4）。"""

    def test_put_refuses_key_not_starting_with_org_id(self):
        org_id = _org()
        with self.assertRaises(ValueError):
            storage.put(
                org_id=org_id,
                key="other_org/x.png",
                filename="x.png",
                content=b"x",
                content_type="image/png",
            )

    def test_get_refuses_key_not_starting_with_org_id(self):
        org_id = _org()
        with self.assertRaises(ValueError):
            storage.get(org_id=org_id, key="other_org/x.png")

    def test_delete_refuses_key_not_starting_with_org_id(self):
        org_id = _org()
        with self.assertRaises(ValueError):
            storage.delete(org_id=org_id, key="other_org/x.png")

    def test_delete_prefix_refuses_prefix_not_starting_with_org_id(self):
        org_id = _org()
        with self.assertRaises(ValueError):
            storage.delete_prefix(org_id=org_id, prefix="other_org/x/")


if __name__ == "__main__":
    unittest.main()
