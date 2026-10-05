"""app/tests/test_workbench_visual_identity.py — F07-I05 (ARCHITECTURE.md §5.9, Decision 20):
`app/workbench/identity.py::ensure_identity()` derives and caches a brand's visual identity
from brand facts alone, no user tuning. FakeProvider only, no real network request.
"""

import unittest

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core import db as coredb
from app.llm import gateway, providers
from app.workbench import identity as workbench_identity
from app.workbench import looks
from app.workbench import repository as workbench_repo

ACTOR = "測試員"

_DEPARTMENT_PROMPT_LINE = "你是品牌視覺總監。只根據下面的品牌事實與規則回答："

_SPEC_TEXT = (
    "iPhone 手持原生抓拍，未修圖，輕微晃動模糊、失焦柔焦、雜亂背景、不均勻光線／直閃、"
    "輕微色差，真實自然、不擺拍、有模糊瑕疵的日常照片感。文案文字樣式請用純色填滿，"
    "請不要出現磨砂質感、金屬流光、浮雕等過多風格。人物自然東亞日常面孔，像街上隨機"
    "遇到的普通上班族／學生／路人，而非廣告選角或韓系偶像。"
)


def _reply(identity="這個品牌走溫暖生活感，人物是二十到三十五歲的都會上班族，穿搭休閒但不隨便，"
                     "配色以暖米與大地色為主，字體圓潤親切，情緒放鬆自在。",
           fit_looks=None, excluded_looks=None, reason="依品牌事實推導。"):
    default_fit = ["soft_lifestyle", "documentary", "clean_bright"]
    return {
        "identity": identity,
        "fit_looks": fit_looks if fit_looks is not None else default_fit,
        "excluded_looks": excluded_looks or [],
        "reason": reason,
    }


def _provider(data: dict) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text="", structured=data,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


class _CountingProvider:
    """跟 `providers.FakeProvider` 同一個呼叫介面，記次數＋記送出的訊息內容——測試 1／2／7
    要斷言呼叫幾次、送了什麼。"""

    name = "fake"

    def __init__(self, data: dict):
        self._data = data
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None) -> providers.ProviderResponse:
        self.calls.append({"messages": messages, "tools": tools})
        return providers.ProviderResponse(
            output_text="", structured=self._data,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )


class _RaceProvider:
    """模擬「兩輪同時推導」：這次呼叫回覆之前，先塞一列別的推導結果進資料表——
    `ensure_identity()` 的 `ON CONFLICT DO NOTHING` 之後要讀到那一列，不是自己這次的內容。"""

    name = "fake"

    def __init__(self, conn, org_id, brand_id, version, winner_identity_text):
        self._conn = conn
        self._org_id = org_id
        self._brand_id = brand_id
        self._version = version
        self._winner_identity_text = winner_identity_text
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None) -> providers.ProviderResponse:
        self.calls.append({"messages": messages})
        workbench_repo.insert_visual_identity(
            self._conn, org_id=self._org_id, brand_id=self._brand_id,
            knowledge_version=self._version, identity_text=self._winner_identity_text,
            fit_looks=["documentary", "clean_bright", "cinematic"], excluded_looks=[],
            brand_spec_text=None, llm_task_id=None,
        )
        loser = _reply(identity="這個不該被存起來的推導結果，內容隨便寫一段湊字數而已。")
        return providers.ProviderResponse(
            output_text="", structured=loser,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )


class WorkbenchVisualIdentityTest(unittest.TestCase):
    def setUp(self):
        self.conn = coredb.current()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：視覺識別", client_name=None, actor=ACTOR,
        )
        self.brand_id = self.brand["id"]

    def test_first_call_stores_and_caches(self):
        provider = _CountingProvider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["fit_looks"], ["soft_lifestyle", "documentary", "clean_bright"])
        self.assertEqual(result["knowledge_version"], 1)

        again = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(len(provider.calls), 1)  # 同一版本沒有第二次呼叫
        self.assertEqual(again["id"], result["id"])

    def test_knowledge_version_bump_triggers_one_more_call(self):
        provider = _CountingProvider(_reply())
        first = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)

        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="定位",
            value="測試內容", status="confirmed", confirmed_by=ACTOR,
        )
        second = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["knowledge_version"], 2)

    def test_exclusion_kept_only_with_verbatim_fact(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="風格限制",
            value="不要出現任何動物元素", status="confirmed", confirmed_by=ACTOR,
        )
        data = _reply(
            fit_looks=["soft_lifestyle", "documentary", "clean_bright", "cinematic"],
            excluded_looks=[
                {"look": "cinematic", "fact": "不要出現任何動物元素"},
                {"look": "documentary", "fact": "這句話沒有真的出現在品牌事實裡"},
            ],
        )
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertNotIn("cinematic", result["fit_looks"])
        self.assertIn("documentary", result["fit_looks"])  # 沒有逐字依據的排除被丟棄
        excluded_keys = [e["look"] for e in result["excluded_looks"]]
        self.assertEqual(excluded_keys, ["cinematic"])

    def test_brand_spec_fact_becomes_first_fit_look(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="visual_base", label="視覺基礎",
            value=_SPEC_TEXT, status="confirmed", confirmed_by=ACTOR,
        )
        provider = _provider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["fit_looks"][0], looks.BRAND_SPEC)
        self.assertEqual(result["brand_spec_text"], _SPEC_TEXT)

    def test_too_few_valid_fit_looks_raises_and_stores_nothing(self):
        data = _reply(fit_looks=["soft_lifestyle", "documentary"])  # 只有 2 個，< 3
        provider = _provider(data)
        with self.assertRaises(RuntimeError) as ctx:
            workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(str(ctx.exception), "品牌視覺推導失敗，請再生成一次。")
        self.assertIsNone(
            workbench_repo.get_visual_identity(self.conn, self.org_id, self.brand_id, 1)
        )

    def test_row_inserted_between_call_and_insert_wins(self):
        provider = _RaceProvider(
            self.conn, self.org_id, self.brand_id, version=1,
            winner_identity_text="搶先寫入的那一列才是真正存起來的內容。",
        )
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["identity_text"], "搶先寫入的那一列才是真正存起來的內容。")

    def test_prompt_contains_catalogue_labels_and_context(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="定位",
            value="一句可以被找到的定位描述文字", status="confirmed", confirmed_by=ACTOR,
        )
        provider = _CountingProvider(_reply())
        workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        sent = provider.calls[0]["messages"][0]["content"]
        for key in looks.LOOKS:
            self.assertIn(looks.look_label(key), sent)
        self.assertIn("一句可以被找到的定位描述文字", sent)

    def test_brand_delete_removes_the_row(self):
        provider = _provider(_reply())
        workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNotNone(
            workbench_repo.get_visual_identity(self.conn, self.org_id, self.brand_id, 1)
        )
        bi_repo.update_brand(
            self.conn, self.brand_id, name=self.brand["name"], client_name=None,
            status="archived", actor=ACTOR,
        )
        bi_repo.delete_brand(self.conn, self.brand_id, actor=ACTOR)
        self.assertIsNone(
            workbench_repo.get_visual_identity(self.conn, self.org_id, self.brand_id, 1)
        )

    # -- mutation-proof tests (Done 6) -----------------------------------------------------

    def test_brand_spec_cannot_be_excluded(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="visual_base", label="視覺基礎",
            value=_SPEC_TEXT, status="confirmed", confirmed_by=ACTOR,
        )
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="風格限制",
            value="不要出現任何動物元素", status="confirmed", confirmed_by=ACTOR,
        )
        data = _reply(excluded_looks=[{"look": looks.BRAND_SPEC, "fact": "不要出現任何動物元素"}])
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["fit_looks"][0], looks.BRAND_SPEC)
        self.assertNotIn(looks.BRAND_SPEC, [e["look"] for e in result["excluded_looks"]])

    def test_unknown_fit_look_dropped(self):
        data = _reply(fit_looks=["soft_lifestyle", "nope", "documentary", "clean_bright"])
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["fit_looks"], ["soft_lifestyle", "documentary", "clean_bright"])

    def test_duplicate_fit_look_deduped_order_kept(self):
        data = _reply(fit_looks=["documentary", "documentary", "clean_bright", "soft_lifestyle"])
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["fit_looks"], ["documentary", "clean_bright", "soft_lifestyle"])

    def test_exclusion_can_drop_below_minimum(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="風格限制",
            value="不要出現任何動物元素", status="confirmed", confirmed_by=ACTOR,
        )
        data = _reply(
            fit_looks=["soft_lifestyle", "documentary", "clean_bright"],
            excluded_looks=[{"look": "documentary", "fact": "不要出現任何動物元素"}],
        )
        provider = _provider(data)
        with self.assertRaises(RuntimeError):
            workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNone(
            workbench_repo.get_visual_identity(self.conn, self.org_id, self.brand_id, 1)
        )

    def test_exclusion_of_unknown_look_key_dropped(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="風格限制",
            value="不要出現任何動物元素", status="confirmed", confirmed_by=ACTOR,
        )
        data = _reply(excluded_looks=[{"look": "not_a_look", "fact": "不要出現任何動物元素"}])
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(result["excluded_looks"], [])

    def test_exclusion_with_empty_fact_dropped(self):
        data = _reply(
            fit_looks=["soft_lifestyle", "documentary", "clean_bright", "cinematic"],
            excluded_looks=[{"look": "cinematic", "fact": ""}],
        )
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIn("cinematic", result["fit_looks"])
        self.assertEqual(result["excluded_looks"], [])

    def test_exclusion_fact_must_be_in_context_not_prompt(self):
        data = _reply(
            fit_looks=["soft_lifestyle", "documentary", "clean_bright", "cinematic"],
            excluded_looks=[{"look": "cinematic", "fact": _DEPARTMENT_PROMPT_LINE}],
        )
        provider = _provider(data)
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIn("cinematic", result["fit_looks"])
        self.assertEqual(result["excluded_looks"], [])

    def test_empty_identity_raises(self):
        data = _reply(identity="   ")
        provider = _provider(data)
        with self.assertRaises(RuntimeError):
            workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNone(
            workbench_repo.get_visual_identity(self.conn, self.org_id, self.brand_id, 1)
        )

    def test_failure_message_is_the_literal_text(self):
        data = _reply(fit_looks=["soft_lifestyle", "documentary"])
        provider = _provider(data)
        with self.assertRaises(RuntimeError) as ctx:
            workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertEqual(str(ctx.exception), "品牌視覺推導失敗，請再生成一次。")

    def test_llm_task_row_has_task_type_and_template_id(self):
        provider = _provider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNotNone(result["llm_task_id"])
        task = gateway.get_task(self.conn, result["llm_task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["task_type"], "workbench_derive_identity")
        self.assertEqual(task["prompt_template_id"], "workbench_derive_identity")

    def test_tool_schema_sent_matches_literal(self):
        provider = _CountingProvider(_reply())
        workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        tools = provider.calls[0]["tools"]
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], "visual_identity")
        expected_schema = {
            "type": "object",
            "properties": {
                "identity": {"type": "string"},
                "fit_looks": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(looks.LOOKS)},
                    "minItems": 3, "maxItems": 5,
                },
                "excluded_looks": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "look": {"type": "string", "enum": list(looks.LOOKS)},
                            "fact": {"type": "string"},
                        },
                        "required": ["look", "fact"],
                        "additionalProperties": False,
                    },
                },
                "reason": {"type": "string"},
            },
            "required": ["identity", "fit_looks", "excluded_looks", "reason"],
            "additionalProperties": False,
        }
        self.assertEqual(tool["input_schema"], expected_schema)

    def test_brand_spec_requires_visual_base_fact_type(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="定位",
            value=_SPEC_TEXT, status="confirmed", confirmed_by=ACTOR,
        )
        provider = _provider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNone(workbench_identity.brand_spec_text(self.conn, self.brand_id))
        self.assertIsNone(result["brand_spec_text"])
        self.assertNotIn(looks.BRAND_SPEC, result["fit_looks"])

    def test_brand_spec_requires_confirmed_status(self):
        bi_repo.create_brand_fact(
            self.conn, self.brand_id, actor=ACTOR, fact_type="visual_base", label="視覺基礎",
            value=_SPEC_TEXT, status="pending",
        )
        provider = _provider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNone(workbench_identity.brand_spec_text(self.conn, self.brand_id))
        self.assertIsNone(result["brand_spec_text"])
        self.assertNotIn(looks.BRAND_SPEC, result["fit_looks"])

    def test_no_visual_base_fact_gives_none_not_empty_string(self):
        provider = _provider(_reply())
        result = workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        self.assertIsNone(result["brand_spec_text"])

    def test_prompt_includes_department_header(self):
        provider = _CountingProvider(_reply())
        workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("# 任務：從品牌事實推出這個品牌的視覺識別", sent)

    def test_prompt_includes_full_texture_lines(self):
        provider = _CountingProvider(_reply())
        workbench_identity.ensure_identity(self.conn, self.org_id, self.brand_id, provider)
        sent = provider.calls[0]["messages"][0]["content"]
        for key, (label, texture) in looks.LOOKS.items():
            self.assertIn(f"- {key}：{label}——{texture}", sent)


class WorkbenchVisualIdentityRegistrationTest(unittest.TestCase):
    def test_registered_in_brand_tables(self):
        self.assertIn(
            "workbench_visual_identity", cleanup.declared_brand_tables()["素材工作檯"],
        )


class WorkbenchVisualIdentityGrantTest(unittest.TestCase):
    def test_authenticated_has_full_table_privileges(self):
        conn = coredb.current()
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            row = conn.execute(
                "SELECT has_table_privilege('authenticated', 'workbench_visual_identity', %s)"
                " AS ok",
                (priv,),
            ).fetchone()
            self.assertTrue(row["ok"], f"missing {priv} grant")


class WorkbenchVisualIdentityRlsTest(unittest.TestCase):
    def test_policy_isolates_rows_by_org(self):
        conn = coredb.current()
        org_a = coredb.new_id("org")
        org_b = coredb.new_id("org")
        brand_a = coredb.new_id("brd")
        brand_b = coredb.new_id("brd")
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "wvi rls org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "wvi rls org B"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_a, org_a, "wvi rls brand A"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_b, org_b, "wvi rls brand B"),
        )
        workbench_repo.insert_visual_identity(
            conn, org_id=org_a, brand_id=brand_a, knowledge_version=1,
            identity_text="A", fit_looks=["documentary"], excluded_looks=[],
            brand_spec_text=None, llm_task_id=None,
        )
        workbench_repo.insert_visual_identity(
            conn, org_id=org_b, brand_id=brand_b, knowledge_version=1,
            identity_text="B", fit_looks=["documentary"], excluded_looks=[],
            brand_spec_text=None, llm_task_id=None,
        )

        conn.execute("SET ROLE authenticated")
        try:
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            seen = {
                row["brand_id"] for row in conn.execute(
                    "SELECT brand_id FROM workbench_visual_identity WHERE brand_id IN (%s, %s)",
                    (brand_a, brand_b),
                )
            }
            self.assertEqual(seen, {brand_a})
        finally:
            conn.execute("RESET ROLE")


if __name__ == "__main__":
    unittest.main()
