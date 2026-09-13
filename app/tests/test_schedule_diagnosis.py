"""app/tests/test_schedule_diagnosis.py — 票 01（T6c）：成效判讀（後端）。

只寫全域 CLAUDE.md 測試四類允許的（資料正確性），三支，不多寫（ticket done-check 3 明文）：

1. `CompressionConservesMoneyTest`：`compress()` 印出來的每個維度，各列花費＋未標座標那列
   ＝ `total_spend`——壓縮層說謊等於後面全部白算。
2. `ConvergeDedupesTest`：兩個 lens 給同一個 `(dimension, coordinate_key, direction)`，
   `converge()` 只留一條、`agreed_by` 有兩個名字、`impact_spend` 取大的那個。
3. `BreakevenFallbackTest`：三層順序——有實際毛利率用實際；沒有但有規則卡用規則卡；
   兩者皆無回 `None`（絕不回 1.0）。

票 02（T6c，02-diagnosis-on-cockpit.md）加一支（done-check 5 明文，只測這一支）：

4. `AdoptSuggestionTest`：「採用」寫出來的那列 `rule` 形狀對——`rule_type` 落在
   `SOFT_REJECT_RULE_TYPES`、`severity == "soft"`、`source_reference_id IS NULL`
   （決定 8：FK 會炸，來源改寫進 `content`）、`content` 含來源日期那句、同一條採用兩次
   只有一列（API 契約／資料正確性）。

`docs/issues/plan-quality/02-diagnosis-label-map-from-this-round.md` 加一支（done-check 1／2
明文，只測這一支）：

5. `LabelMapFromPerformanceTest`：`label_map_from_performance()` 只從這一輪壓縮表（`values`
   清單）建圖，不是品牌整個座標庫——`untagged`-only 的維度不貢獻任何鍵；一個這一輪零花費的
   舊座標值因此不在圖裡，`_valid_suggestions()` 就把引用它的建議丟掉，即使那個座標值真的
   登記在這個品牌名下（資料正確性）。
"""

import re
import unittest
from uuid import UUID, uuid4

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards, vocab
from app.core import settings as coresettings
from app.identity import ActorContext
from app.llm import methodology, providers
from app.orders import repository as orders_repo
from app.schedule import creative as creative_mod
from app.schedule import diagnosis
from app.schedule import jobs as schedule_jobs
from app.schedule import routes as schedule_routes
from app.schedule import state as schedule_state

_SPEND_CELL_RE = re.compile(r"^\|[^|]*\|\s*([\d,]+)\s*\|")


def _bucket(spend: float, *, roas=None, roas_conservative=None, coverage=1.0, ad_count=1) -> dict:
    return {
        "spend": spend, "impressions": 100, "clicks": 10, "revenue": None,
        "roas": roas, "roas_conservative": roas_conservative,
        "roas_coverage": coverage, "ad_count": ad_count,
    }


def _performance_fixture() -> dict:
    """跟 `performance.brand_creative_performance()` 同一個輸出形狀——每個維度自己的
    `values[].spend` ＋ `untagged.spend` 都等於這個幣別的 `total_spend`（1000）。刻意用整數
    金額：`compress()` 用 `{:,.0f}` 格式印出來，測試才能逐字解析回整數比對，不必擔心小數點
    捨入把守恆測試自己弄假紅。"""
    dimensions = [
        {
            "dimension": dim_key,
            "untagged": {"spend": 100.0, "ad_count": 1},
            "values": [
                {"key": "v1", "label": "座標甲", **_bucket(600.0, roas=2.0, roas_conservative=1.5)},
                {"key": "v2", "label": "座標乙", **_bucket(300.0, roas=1.0, roas_conservative=0.8)},
            ],
        }
        for dim_key in creative_mod.COORDINATE_KEYS
    ]
    return {
        "window": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
        "currencies": [{
            "currency": "TWD", "total_spend": 1000.0,
            "untagged": {"spend": 100.0, "ad_count": 1}, "dimensions": dimensions,
        }],
    }


class CompressionConservesMoneyTest(unittest.TestCase):
    """壓縮層說謊等於後面全部白算：每個維度**印出來的文字**（含未標座標那一列）加總花費要
    等於 `total_spend`——不只是輸入資料本身守恆，是印出去給 agent 看的表格也要守恆，才防得住
    「表格印漏一列」這種不改資料、只改顯示就會出事的錯。"""

    def test_every_dimension_table_sums_to_total_spend(self):
        performance = _performance_fixture()
        total_spend = int(performance["currencies"][0]["total_spend"])
        text = diagnosis.compress(performance, (1.43, "規則卡毛利率 70%"))

        sections = text.split("\n## ")[1:]  # 第一段是幣別總覽，之後每段是一個維度
        self.assertEqual(len(sections), len(creative_mod.COORDINATE_KEYS))
        for section in sections:
            rows_spend = sum(
                int(match.group(1).replace(",", ""))
                for line in section.splitlines()
                if (match := _SPEND_CELL_RE.match(line)) is not None
            )
            self.assertEqual(
                rows_spend, total_spend,
                msg=f"維度區塊沒有加總到 total_spend：\n{section}",
            )


class ConvergeDedupesTest(unittest.TestCase):
    """去重鍵 `(dimension, coordinate_key, direction)`：同鍵只留一條，`agreed_by` 累加成
    名單，`impact_spend` 取大的那個——重複是信號不是雜訊（spec 新規則）。"""

    def test_two_lenses_agreeing_collapse_into_one_with_larger_impact_spend(self):
        outputs = [
            {"dimension": "audience", "coordinate_key": "cold_problem_aware",
             "coordinate_label": "陌生・知道問題", "direction": "scale_up",
             "impact_spend": 500.0, "headline": "受眾角度的說法", "evidence": "e1",
             "lens": "audience"},
            {"dimension": "audience", "coordinate_key": "cold_problem_aware",
             "coordinate_label": "陌生・知道問題", "direction": "scale_up",
             "impact_spend": 800.0, "headline": "預算角度的說法", "evidence": "e2",
             "lens": "budget"},
        ]
        result = diagnosis.converge(outputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["impact_spend"], 800.0)
        self.assertEqual(result[0]["headline"], "預算角度的說法")  # 較大 impact_spend 那條的內文
        self.assertEqual(set(result[0]["agreed_by"]), {"audience", "budget"})


class LabelMapFromPerformanceTest(unittest.TestCase):
    """Ticket `02-diagnosis-label-map-from-this-round.md`：guard map keys off this round's
    compressed table (`performance["currencies"][*]["dimensions"][*]["values"]`), not the
    brand's whole registered-coordinate library — a coordinate with zero spend this round must
    be absent from the map even though it is a real, registered coordinate."""

    def test_literal_example_maps_only_the_tagged_value_and_skips_untagged(self):
        performance = {"currencies": [{
            "currency": "TWD", "total_spend": 300.0, "untagged": {"spend": 0.0},
            "dimensions": [
                {"dimension": "angle", "untagged": {"spend": 0.0},
                 "values": [{"key": "angle_value", "label": "價值感", "spend": 300.0}]},
                {"dimension": "hook", "untagged": {"spend": 300.0}, "values": []},
            ],
        }]}
        self.assertEqual(
            diagnosis.label_map_from_performance(performance),
            {("angle", "價值感"): "angle_value"},
        )

    def test_valid_suggestions_drops_a_label_absent_from_this_rounds_table(self):
        # Only one coordinate value carries a spend row this round; a suggestion citing a real
        # but zero-spend label ("CP值") must fall out here, not survive on the strength of being
        # registered in the brand's coordinate library (that would be the pre-fix behaviour this
        # ticket removes: `list_coordinates()` would carry both labels regardless of spend).
        performance = {"currencies": [{
            "currency": "TWD", "total_spend": 300.0, "untagged": {"spend": 0.0},
            "dimensions": [
                {"dimension": "angle", "untagged": {"spend": 0.0},
                 "values": [{"key": "angle_value", "label": "價值感", "spend": 300.0}]},
            ],
        }]}
        label_to_key = diagnosis.label_map_from_performance(performance)
        raw = [
            {"dimension": "angle", "coordinate_label": "價值感", "direction": "scale_up",
             "impact_spend": 300.0, "headline": "h1", "evidence": "e1"},
            {"dimension": "angle", "coordinate_label": "CP值", "direction": "scale_up",
             "impact_spend": 0.0, "headline": "h2", "evidence": "e2"},
        ]
        out = diagnosis._valid_suggestions(raw, label_to_key)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["coordinate_key"], "angle_value")


class BreakevenFallbackTest(unittest.TestCase):
    """四層順序——有實際毛利率用實際；沒有就用這一期產品自己填的售價與成本（issue
    diagnosis-lacks-checkable-numbers 補的第②層）；再沒有用規則卡；全都沒有回 `None`
    （絕不回 1.0：1.0 等於宣稱毛利 100%，會把賠錢的座標畫成贏家）。四個品牌各自代表一層，
    互不干擾（一個 test 方法裡驗完四層，不拆成四支——ticket 明講只准三支測試）。"""

    def _new_brand(self, suffix: str) -> tuple[str, str]:
        org_id = f"org_diag_test_{suffix}_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]
        return org_id, brand_id

    def test_breakeven_roas_falls_through_the_four_layers_in_order(self):
        # 層 2：沒有任何訂單、沒有登記任何 SKU 成本——規則卡尚未被使用者改過，用 CARDS 預設
        # 值 0.70（打平線 1÷0.70 ≈ 1.43）。
        org_2, brand_2 = self._new_brand("card_default")
        roas_2, source_2 = diagnosis.breakeven_roas(web.conn, org_2, brand_2)
        self.assertEqual(roas_2, 1.43)
        self.assertIn("規則卡", source_2)

        # 層 1：這個月官網訂單登記過 SKU 成本，算得出實際毛利率（60%），優先用它，不用規則卡。
        org_1, brand_1 = self._new_brand("actual_margin")
        month_start = coresettings.today_for_org(web.conn, org_id=org_1).replace(day=1)
        orders_repo.save_orders(
            web.conn, brand_1,
            [{
                "order_number": "O-DIAG-1", "order_date": month_start.isoformat(),
                "total_amount": 1000, "refunded_amount": 0, "financial_status": "paid",
                "fulfillment_status": "fulfilled", "order_status": "paid", "voucher_code": None,
                "billing_email": None, "billing_phone": None,
                "items": [{"sku": "SKU-DIAG", "item_price": 1000, "quantity": 1}],
            }],
            source="easystore_xlsx", actor="測試員",
        )
        orders_repo.set_sku_cost(web.conn, brand_1, "SKU-DIAG", 400, actor="測試員")  # 毛利 60%
        roas_1, source_1 = diagnosis.breakeven_roas(web.conn, org_1, brand_1)
        self.assertAlmostEqual(roas_1, round(1 / 0.6, 2), places=2)
        self.assertIn("官網訂單", source_1)

        # 層 2：沒有訂單，但這一期方案選的產品自己填了售價與單位變動成本——1880／520 與
        # 990／240，加權（各一單位）毛利率 (1360+750)÷(1880+990) ≈ 73.5%，打平線 1.36。
        # 填了資料就要被用到，不准掉回規則卡的 0.70（issue diagnosis-lacks-checkable-numbers）。
        org_pe, brand_pe = self._new_brand("product_economics")
        product_ids = []
        for price, cost in ((1880, 520), (990, 240)):
            product_id = bi_repo.create_product(
                web.conn, brand_pe, name=f"產品{price}", actor="測試員",
            )["id"]
            bi_repo.save_product_economics(
                web.conn, brand_pe, product_id, actor="測試員", selling_price=price,
                currency="TWD", confirmed_by="測試員", unit_variable_cost=cost,
            )
            product_ids.append(product_id)
        _seed_plan_row(org_pe, brand_pe, product_ids)
        roas_pe, source_pe = diagnosis.breakeven_roas(web.conn, org_pe, brand_pe)
        self.assertEqual(roas_pe, 1.36)
        self.assertIn("這一期產品", source_pe)

        # 層 4：三層都算不出一個 >0 的毛利率（規則卡被使用者自己設成 0，沒有訂單）——絕不回
        # 1.0 頂著，誠實回 None。
        org_3, brand_3 = self._new_brand("nothing_usable")
        rule_cards.set_value(
            web.conn, brand_3, "gross_margin", "gross_margin_rate", 0.0,
            actor="測試員", org_id=org_3,
        )
        roas_3, _source_3 = diagnosis.breakeven_roas(web.conn, org_3, brand_3)
        self.assertIsNone(roas_3)
        self.assertNotEqual(roas_3, 1.0)


def _seed_plan_row(org_id: str, brand_id: str, product_ids: list) -> None:
    """一列成功的 `schedule_plan`——打平線第②層要問「這一期方案選了哪些產品」，答案就存在
    這一列的 `context_scope_json.product_ids`（`app/schedule/jobs.py::schedule_plan` 寫的）。"""
    web.conn.execute(
        "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
        " input_context_ids_json, input_context_hash, knowledge_item_ids_json, brand_version,"
        " prompt_template_id, prompt_template_version, provider, model, status, attempt_no,"
        " started_at) VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
        " 'succeeded', 1, now())",
        (coredb.new_id("llm"), org_id, brand_id, schedule_state.TASK_TYPE,
         coredb.jsonb({"brand_id": brand_id, "product_ids": product_ids})),
    )
    web.conn.commit()


class CheckableNumbersTest(unittest.TestCase):
    """**資料正確性**：`attach_checkable_numbers()` 把「這一組」與「對照組」的花費／廣告數
    照抄過來，不重算、不跨幣別（ADR 0057 §4）。issue diagnosis-lacks-checkable-numbers：
    有經驗的使用者拒絕採用一條沒有花費與樣本數的建議——數字本來就在同一份輸入裡。"""

    def test_numbers_and_peers_come_from_the_same_currency_block(self):
        def value(key, label, spend, ad_count):
            return {"key": key, "label": label, "spend": spend, "ad_count": ad_count,
                    "impressions": 0, "clicks": 0, "revenue": None, "roas": None,
                    "roas_conservative": 2.5, "roas_coverage": 0.5}

        performance = {"currencies": [
            {"currency": "TWD", "total_spend": 3000, "untagged": {"spend": 0, "ad_count": 0},
             "dimensions": [{"dimension": "offer", "untagged": {"spend": 0, "ad_count": 0},
                             "values": [value("discount", "折扣", 2000, 5),
                                        value("none", "無優惠", 1000, 3)]}]},
            {"currency": "USD", "total_spend": 7, "untagged": {"spend": 0, "ad_count": 0},
             "dimensions": [{"dimension": "offer", "untagged": {"spend": 0, "ad_count": 0},
                             "values": [value("discount", "折扣", 5, 1),
                                        value("none", "無優惠", 2, 1)]}]},
        ]}
        suggestion = {"dimension": "offer", "coordinate_key": "discount",
                      "coordinate_label": "折扣", "direction": "scale_up",
                      "impact_spend": 2000.0, "headline": "h", "evidence": "e",
                      "agreed_by": ["budget"]}

        out = diagnosis.attach_checkable_numbers([suggestion], performance)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["currency"], "TWD")  # 花費大的那個幣別，不跨幣別相加
        self.assertEqual(out[0]["numbers"]["spend"], 2000)
        self.assertEqual(out[0]["numbers"]["ad_count"], 5)
        self.assertEqual([p["label"] for p in out[0]["compared_with"]], ["無優惠"])
        self.assertEqual(out[0]["compared_with"][0]["spend"], 1000)  # 對照組同一個幣別
        self.assertEqual(out[0]["headline"], "h")  # 原本的欄位一個都沒掉


class AdoptSuggestionTest(unittest.TestCase):
    """票 02 done-check 5：呼叫 `_run_diagnosis_adopt()`（`routes.py`）兩次，寫出來的那列
    `rule` 形狀對，且第二次不多寫一列。直接呼叫路由的私有函式，不經 HTTP 層——跟本檔其他
    三支一樣直接測 `diagnosis.py`／`routes.py` 的函式，不新增第二套測試慣例。"""

    def _new_brand(self) -> tuple[str, str]:
        org_id = f"org_diag_adopt_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]
        return org_id, brand_id

    def _insert_succeeded_lens_row(self, org_id: str, brand_id: str, round_id: str, lens: str,
                                    *, started_at, structured=None) -> None:
        """比照 `test_schedule.py` `QueuedGenerationTest._insert_running_row` 既有的直接下
        SQL 寫法（那支造 running 列，這裡造 succeeded 列）——`app.llm` 沒有另開一支「測試專用
        造列」的寫入端，不重造第二份。"""
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at, structured_output_json)"
            " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'succeeded', 1, %s, %s)",
            (coredb.new_id("llm"), org_id, brand_id, schedule_state.DIAGNOSIS_TASK_TYPE,
             coredb.jsonb({"brand_id": brand_id, "round_id": round_id, "lens": lens}),
             started_at, coredb.jsonb(structured) if structured is not None else None),
        )
        web.conn.commit()

    def test_adopt_writes_a_soft_rule_with_no_source_reference_id_and_is_idempotent(self):
        org_id, brand_id = self._new_brand()
        started_at = coredb.now_utc()
        round_id = coredb.new_id("dgr")
        suggestion = {
            "dimension": "audience", "coordinate_key": "cold_problem_aware",
            "coordinate_label": "陌生・知道問題", "direction": "scale_up",
            "impact_spend": 500.0, "headline": "下一輪把預算往「陌生・知道問題」加碼",
            "evidence": "這群人保守 ROAS 2.58x／樂觀 3.17x、覆蓋率 75%", "agreed_by": ["budget"],
        }
        for lens in diagnosis.LENSES:
            self._insert_succeeded_lens_row(
                org_id, brand_id, round_id, lens, started_at=started_at,
                structured=[suggestion] if lens == "budget" else None,
            )

        actor = ActorContext(
            user_id=UUID(int=0), org_id=org_id, role="owner", email="t@example.com",
        )
        body = schedule_routes.AdoptRequest(suggestion_index=0)
        result1 = schedule_routes._run_diagnosis_adopt(web.conn, brand_id, actor, body)
        result2 = schedule_routes._run_diagnosis_adopt(web.conn, brand_id, actor, body)

        self.assertEqual(result1["id"], result2["id"])  # 同一條採用兩次只回既有那列

        rows = bi_repo.list_rules_for_brand(web.conn, brand_id)
        self.assertEqual(len(rows), 1, "同一條採用兩次只該有一列")
        rule = rows[0]
        # issue adopted-advice-can-invert：採用一條判讀寫的是「這一期要去做的實驗」，固定
        # 落在 EXPERIMENT_RULE_TYPE，不再按維度借用角度／受眾的抽屜（決定 9 已撤銷）。
        self.assertEqual(rule["rule_type"], vocab.EXPERIMENT_RULE_TYPE)
        self.assertEqual(rule["severity"], "soft")
        self.assertIsNone(rule["source_reference_id"])
        self.assertIn(started_at.date().isoformat(), rule["content"])  # 來源日期那句


class DiagnosisPromptCachingTest(unittest.TestCase):
    """票 F04-I05：三個 lens 共用的前四段標上 `cache_control`，只算一次，逐字內容跟改動前
    完全相同——省的是 Anthropic 快取的錢，不是 prompt 的內容。"""

    def _new_brand(self) -> tuple[str, str]:
        org_id = f"org_diag_cache_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]
        return org_id, brand_id

    def test_shared_prefix_is_cached_and_byte_identical_to_the_old_single_string_prompt(self):
        org_id, brand_id = self._new_brand()
        fake = providers.FakeProvider(providers.ProviderResponse(
            output_text="這是一段判讀說明。\n\n```json\n{\"suggestions\": []}\n```",
            structured=None, usage=providers.Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        ))
        original_provider = schedule_jobs.PROVIDER
        schedule_jobs.PROVIDER = fake
        try:
            schedule_jobs.schedule_diagnosis(org_id, brand_id)
        finally:
            schedule_jobs.PROVIDER = original_provider

        self.assertEqual(len(fake.calls), 3)  # 三個 lens 各打一次

        # 斷言 1：三次呼叫共用前綴 [0]["text"] 逐字相同、都帶 cache_control；[1]["text"]
        # （role_text(lens)）三次各不相同。
        shared_texts = [call["messages"][0]["content"][0]["text"] for call in fake.calls]
        self.assertEqual(len(set(shared_texts)), 1, "三次呼叫的共用前綴必須逐字相同")
        for call in fake.calls:
            block = call["messages"][0]["content"][0]
            self.assertEqual(block["cache_control"], {"type": "ephemeral"})
        role_texts = [call["messages"][0]["content"][1]["text"] for call in fake.calls]
        self.assertEqual(len(set(role_texts)), 3, "三個 lens 的角色段必須各不相同")

        # 斷言 2：攤平後的全文跟改動前「一段字串」的 prompt 逐字相同——證明省的是錢不是內容。
        performance_mod_result = _performance_via_schedule(org_id, brand_id)
        compressed = diagnosis.compress(performance_mod_result, diagnosis.breakeven_roas(
            web.conn, org_id, brand_id,
        ))
        reminders = diagnosis.reminders_text(diagnosis.tree_reminders(web.conn, brand_id))
        methodology_result = methodology.compile(
            web.conn, schedule_state.DIAGNOSIS_METHODOLOGY_TASK_LABELS, brand_id=brand_id
        )
        for lens, call in zip(diagnosis.LENSES, fake.calls, strict=True):
            expected = "\n\n".join(
                section for section in
                (methodology_result.text, compressed, reminders, None,
                 diagnosis.role_text(lens)) if section
            )
            flattened = "".join(
                block["text"] for block in call["messages"][0]["content"]
            )
            self.assertEqual(flattened, expected)


def _performance_via_schedule(org_id: str, brand_id: str) -> dict:
    """跟 `jobs.schedule_diagnosis()` 讀同一支——不重造第二份，讀 `app.schedule.performance`
    的既有公開函式。"""
    from app.schedule import performance as performance_mod
    return performance_mod.brand_creative_performance(web.conn, org_id, brand_id)


if __name__ == "__main__":
    unittest.main()
