# -*- coding: utf-8 -*-
"""T2 批次 A 後端契約：真相卡、照片產品卡與人物誌。全程只用暫存 DB／假 AI。"""

from types import SimpleNamespace
from unittest import mock
import json
import time

import anthropic
from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import personas
from app.brand_intelligence import repository as bi_repo
from app.intake import repository as ir
from app.intake import ai as intake_ai
from app.intake import persona_generation
from app.intake import state
from app.llm import context_compiler, providers
from app.llm.providers import ProviderResponse, Usage


ACTOR = "測試員"


class QueueProvider:
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(text="", structured=None):
    return ProviderResponse(
        output_text=text, structured=structured,
        usage=Usage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def test_persona_migration_and_replace_list_contract():
    columns = [row["name"] for row in main.conn.execute("PRAGMA table_info(persona)")]
    assert columns == [
        "id", "brand_id", "title", "when_needed", "care_about", "hesitation",
        "where_to_find", "created_at",
    ]
    brand = bi_repo.create_brand(
        main.conn, name="虛構人物誌資料品牌", client_name=None, actor=ACTOR,
    )
    personas.replace_personas(main.conn, brand["id"], [{
        "title": "臨時找禮物的人", "when_needed": "拜訪客戶前",
        "care_about": "包裝體面", "hesitation": "怕送錯口味",
        "where_to_find": "地圖評論",
    }])

    saved = personas.list_personas(main.conn, brand["id"])
    assert len(saved) == 1
    assert {key: saved[0][key] for key in (
        "title", "when_needed", "care_about", "hesitation", "where_to_find",
    )} == {
        "title": "臨時找禮物的人", "when_needed": "拜訪客戶前",
        "care_about": "包裝體面", "hesitation": "怕送錯口味",
        "where_to_find": "地圖評論",
    }


def _persona_rows(prefix: str):
    return [
        {"title": f"{prefix}臨時送禮的人", "when_needed": "拜訪客戶前",
         "care_about": "包裝體面", "hesitation": "怕選錯口味", "where_to_find": "地圖評論"},
        {"title": f"{prefix}辦公室採購", "when_needed": "月底補貨時",
         "care_about": "交期穩定", "hesitation": "怕數量不足", "where_to_find": "同業社團"},
    ]


def _wait_personas(client: TestClient, brand_id: str):
    deadline = time.time() + 5
    while time.time() < deadline:
        response = client.get(f"/api/intake/brands/{brand_id}/personas")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        if data["generation"]["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError("人物誌背景工作逾時")


def test_anthropic_provider_sends_official_base64_image_block_to_fake_sdk():
    captured = []
    sdk_response = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="看到了")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, server_tool_use=None),
    )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def with_options(self, **_kwargs):
            return self

        @property
        def messages(self):
            return self

        def create(self, **kwargs):
            captured.append(kwargs)
            return sdk_response

    image_block = providers.base64_image_block("image/png", b"fake-png-bytes")
    messages = [{"role": "user", "content": [image_block, {"type": "text", "text": "讀這張圖"}]}]
    with mock.patch.object(providers.settings, "get_api_key", lambda: "sk-ant-fake-test"), \
            mock.patch.object(anthropic, "Anthropic", FakeClient):
        providers.AnthropicProvider().complete(
            model="claude-opus-5", system=None, messages=messages, max_tokens=200,
        )

    assert captured[0]["messages"] == messages
    assert image_block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "ZmFrZS1wbmctYnl0ZXM="},
    }


def test_run_scan_reads_fake_photo_into_product_card_without_guessing_price(monkeypatch):
    brand = bi_repo.create_brand(
        main.conn, name="虛構照片果茶品牌", client_name=None, actor=ACTOR,
    )
    uploaded = state.save_new_photo("fake-product.png", b"fake-png-bytes")
    photos = state.resolve_photo_tokens([uploaded["token"]])
    draft = state.new_draft(
        brand["id"], brand["name"], description="照片裡是一款虛構果茶。", urls=[], photos=photos,
        actor=ACTOR, conn=main.conn,
    )
    provider = QueueProvider([
        _response(json.dumps({
            "impressions": [{"looks_like": "產品線", "title": "單一品項",
                             "content": "看起來只有一款。", "basis": "業主描述"}],
            "products": ["虛構網址果茶"],
        }, ensure_ascii=False)),
        _response(structured={
            "readable": True,
            "name": "虛構山霧果茶",
            "specification": "8 入茶包",
            "selling_points": ["低溫乾燥", "獨立包裝"],
            "gaps": [],
            "price": 999,
        }),
    ])
    monkeypatch.setattr(intake_ai, "PROVIDER", provider)
    progress = []

    ok, error = intake_ai.run_scan(main.conn, draft, on_photo_progress=lambda n, total: progress.append((n, total)))

    assert ok is True and error is None
    saved = state.get_draft(brand["id"], conn=main.conn)
    assert saved["scan_products"] == ["虛構網址果茶", "虛構山霧果茶"]
    assert progress == [(1, 1)]
    card = saved["product_card_drafts"][0]
    assert card == {
        "status": "ready",
        "name": "虛構山霧果茶",
        "specification": "8 入茶包",
        "selling_points": ["低溫乾燥", "獨立包裝"],
        "source_photo_token": uploaded["token"],
        "gaps": ["價格"],
        "message": None,
    }
    assert "price" not in card
    image_content = provider.calls[1]["messages"][0]["content"]
    assert image_content[0]["type"] == "image"
    assert image_content[0]["source"]["type"] == "base64"


def test_photo_failures_are_recorded_per_photo_without_blocking_scan(monkeypatch):
    brand = bi_repo.create_brand(
        main.conn, name="虛構照片誠實態品牌", client_name=None, actor=ACTOR,
    )
    uploaded = state.save_new_photo("unreadable.png", b"fake-png-bytes")
    readable_file = state.resolve_photo_tokens([uploaded["token"]])[0]
    missing_file = {
        "token": "pht_missing_test", "name": "missing.png",
        "path": str(state.get_upload_dir() / "definitely-missing.png"), "size_mb": 0.1,
    }
    draft = state.new_draft(
        brand["id"], brand["name"], description="測試每張照片的誠實狀態。", urls=[],
        photos=[missing_file, readable_file], actor=ACTOR, conn=main.conn,
    )
    provider = QueueProvider([
        _response(json.dumps({"impressions": [], "products": []}, ensure_ascii=False)),
        _response(structured={
            "readable": False, "name": "", "specification": "",
            "selling_points": [], "gaps": [],
        }),
    ])
    monkeypatch.setattr(intake_ai, "PROVIDER", provider)

    ok, error = intake_ai.run_scan(main.conn, draft)

    assert ok is True and error is None
    cards = state.get_draft(brand["id"], conn=main.conn)["product_card_drafts"]
    assert [card["status"] for card in cards] == ["failed", "unreadable"]
    assert "找不到照片" in cards[0]["message"]
    assert "讀不出" in cards[1]["message"]
    assert all("價格" in card["gaps"] for card in cards)


def test_existing_scan_product_endpoint_creates_confirmed_prefill_but_no_price():
    brand = bi_repo.create_brand(
        main.conn, name="虛構預填產品品牌", client_name=None, actor=ACTOR,
    )
    draft = state.new_draft(
        brand["id"], brand["name"], description="測試產品預填。", urls=[], photos=[],
        actor=ACTOR, conn=main.conn,
    )
    draft["scan_products"] = ["虛構晨露茶"]
    draft["product_card_drafts"] = [{
        "status": "ready", "name": "虛構晨露茶", "specification": "12 入茶包",
        "selling_points": ["無香料", "單包沖泡"], "source_photo_token": "pht_fake_prefill",
        "gaps": ["價格"], "message": None,
    }]
    state.save(draft, conn=main.conn)

    response = TestClient(main.app).post(
        f"/api/intake/brands/{brand['id']}/scan/products",
        json={"source_photo_token": "pht_fake_prefill"},
    )

    assert response.status_code == 200, response.text
    product = next(p for p in bi_repo.list_products(main.conn, brand["id"]) if p["name"] == "虛構晨露茶")
    facts = bi_repo.list_product_facts(main.conn, brand["id"], product["id"])
    assert [(fact["label"], fact["value"], fact["status"], fact["confirmed_by"]) for fact in facts] == [
        ("規格", "12 入茶包", "confirmed", "使用者"),
        ("賣點", "無香料、單包沖泡", "confirmed", "使用者"),
    ]
    assert bi_repo.get_product_economics(main.conn, brand["id"], product["id"]) is None


def test_photo_card_gaps_feed_existing_question_aspect_context(monkeypatch):
    brand = bi_repo.create_brand(
        main.conn, name="虛構缺口問答品牌", client_name=None, actor=ACTOR,
    )
    draft = state.new_draft(
        brand["id"], brand["name"], description="測試照片缺口出題。", urls=[], photos=[],
        actor=ACTOR, conn=main.conn,
    )
    draft["product_card_drafts"] = [{
        "status": "ready", "name": "虛構暮色茶", "specification": "",
        "selling_points": ["方便沖泡"], "source_photo_token": "pht_gap",
        "gaps": ["規格", "價格"], "message": None,
    }]
    state.save(draft, conn=main.conn)
    provider = QueueProvider([_response(json.dumps({
        "done": False, "aspect": "價格帶", "question": "這款茶預計賣多少？",
        "suggested": {"label": "等你填", "desc": "商業數字由你決定。"},
        "branches": [{"label": "尚未決定", "desc": "之後再補。"}],
    }, ensure_ascii=False))])
    monkeypatch.setattr(intake_ai, "PROVIDER", provider)

    ok, error = intake_ai.run_next_question(main.conn, state.get_draft(brand["id"], conn=main.conn))

    assert ok is True and error is None
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "照片產品卡缺口（優先補問）" in prompt
    assert "虛構暮色茶：規格、價格" in prompt


def _new_truth_card_fixture(suffix: str):
    brand = bi_repo.create_brand(
        main.conn, name=f"虛構真相卡品牌{suffix}", client_name=None, actor=ACTOR,
    )
    product = bi_repo.create_product(
        main.conn, brand["id"], name=f"虛構果茶{suffix}", actor=ACTOR,
    )
    draft = state.new_draft(
        brand["id"], brand["name"], description="測試真相卡分格。", urls=[], photos=[],
        actor=ACTOR, conn=main.conn,
    )
    items = ir.create_items(main.conn, brand["id"], draft["id"], [
        {"kind": "品牌事實", "category": "定位", "title": "產地直送",
         "content": "只使用虛構果園原料。", "scope": "整個品牌", "evidence": "測試資料"},
        {"kind": "產品事實", "category": "價格帶", "title": "產品售價",
         "content": "售價等使用者補。", "scope": product["name"], "evidence": "測試資料"},
        {"kind": "宣稱", "category": "高風險", "title": "幫助消化",
         "content": "需要決定可不可以講。", "scope": "整個品牌", "evidence": "測試資料"},
        {"kind": "宣稱", "category": "禁用", "title": "治療過敏",
         "content": "使用者已說不能講。", "scope": "整個品牌", "evidence": "測試資料"},
    ])
    forbidden = items[3]
    ir.resolve_item(
        main.conn, brand["id"], forbidden["id"], "confirmed", processed_by="使用者",
        edits={"category": "forbidden"},
    )
    return brand, draft, items


def test_truth_card_mechanical_buckets_cover_default_price_claim_and_forbidden():
    brand, _draft, items = _new_truth_card_fixture("分格")

    response = TestClient(main.app).get(f"/api/intake/brands/{brand['id']}/truth-card")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [item["id"] for item in data["accepted"]] == [items[0]["id"]]
    assert [(item["id"], item["answer_kind"]) for item in data["needs_confirmation"]] == [
        (items[1]["id"], "price"),
        (items[2]["id"], "claim_permission"),
    ]
    assert [item["id"] for item in data["forbidden"]] == [items[3]["id"]]


def test_truth_card_batch_rejects_missing_yellow_answers_before_writing_anything():
    brand, draft, items = _new_truth_card_fixture("缺答")

    response = TestClient(main.app).post(
        f"/api/intake/brands/{brand['id']}/truth-card/confirm", json={"answers": {}},
    )

    assert response.status_code == 400, response.text
    assert "產品售價" in response.json()["error"]
    assert "幫助消化" in response.json()["error"]
    pending_ids = {item["id"] for item in ir.list_pending_items(main.conn, brand["id"], draft["id"])}
    assert pending_ids == {items[0]["id"], items[1]["id"], items[2]["id"]}


def test_truth_card_confirmation_generates_personas_notifies_and_can_regenerate(monkeypatch):
    brand, draft, items = _new_truth_card_fixture("人物誌")
    provider = QueueProvider([
        _response(structured={"personas": _persona_rows("第一批")}),
        _response(structured={"personas": _persona_rows("第二批")}),
    ])
    monkeypatch.setattr(persona_generation, "PROVIDER", provider)
    persona_generation.JOBS.clear()
    client = TestClient(main.app)

    response = client.post(
        f"/api/intake/brands/{brand['id']}/truth-card/confirm",
        json={"answers": {
            items[1]["id"]: {"value": "NT$ 480"},
            items[2]["id"]: {"decision": "cannot_say"},
        }},
    )
    assert response.status_code == 204, response.text
    first = _wait_personas(client, brand["id"])
    assert [row["title"] for row in first["personas"]] == [
        "第一批臨時送禮的人", "第一批辦公室採購",
    ]
    processed = main.conn.execute(
        "SELECT processed_by FROM intake_item WHERE intake_draft_id = ? ORDER BY row_no",
        (draft["id"],),
    ).fetchall()
    assert {row["processed_by"] for row in processed} == {"使用者"}
    notices = main.conn.execute(
        "SELECT category, message FROM interrupt WHERE brand_id = ? ORDER BY created_at",
        (brand["id"],),
    ).fetchall()
    assert notices[-1]["category"] == "personas_ready"
    assert "人物誌好了" in notices[-1]["message"]
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "產地直送" in prompt
    assert "NT$ 480" in prompt

    response = client.post(f"/api/intake/brands/{brand['id']}/personas/regenerate")
    assert response.status_code == 202, response.text
    second = _wait_personas(client, brand["id"])
    assert [row["title"] for row in second["personas"]] == [
        "第二批臨時送禮的人", "第二批辦公室採購",
    ]


def test_persona_failure_is_honest_and_keeps_previous_rows(monkeypatch):
    brand = bi_repo.create_brand(
        main.conn, name="虛構人物誌失敗品牌", client_name=None, actor=ACTOR,
    )
    personas.replace_personas(main.conn, brand["id"], _persona_rows("舊版"))
    provider = QueueProvider([_response(structured={"personas": _persona_rows("不足")[:1]})])
    monkeypatch.setattr(persona_generation, "PROVIDER", provider)
    persona_generation.JOBS.clear()
    client = TestClient(main.app)

    response = client.post(f"/api/intake/brands/{brand['id']}/personas/regenerate")
    assert response.status_code == 202, response.text
    data = _wait_personas(client, brand["id"])

    assert data["generation"]["status"] == "failed"
    assert "格式不完整" in data["generation"]["error"]
    assert [row["title"] for row in data["personas"]] == [
        "舊版臨時送禮的人", "舊版辦公室採購",
    ]


def test_context_compiler_adds_capped_plain_language_persona_summary():
    brand = bi_repo.create_brand(
        main.conn, name="虛構摘要上限品牌", client_name=None, actor=ACTOR,
    )
    rows = []
    for number in range(1, 6):
        rows.append({
            "title": f"第{number}類客人", "when_needed": "需要準備禮物時",
            "care_about": "體面" * 50, "hesitation": "怕不合口味",
            "where_to_find": "虛構社群",
        })
    saved = personas.replace_personas(main.conn, brand["id"], rows)

    text, item_ids, _brand_version, _product_version = context_compiler.compile(
        main.conn, brand["id"],
    )

    assert "【典型客人】" in text
    assert "什麼時候需要：需要準備禮物時" in text
    assert "去哪找他：虛構社群" in text
    assert "第4類客人" in text
    assert "第5類客人" not in text
    assert set(item_ids).intersection(row["id"] for row in saved) == {
        row["id"] for row in saved[:4]
    }
    assert "體面" * 41 not in text


def test_fact_confirm_defaults_confirmer_to_user():
    brand = bi_repo.create_brand(
        main.conn, name="虛構確認人品牌", client_name=None, actor=ACTOR,
    )
    product = bi_repo.create_product(
        main.conn, brand["id"], name="虛構確認產品", actor=ACTOR,
    )
    fact = bi_repo.create_product_fact(
        main.conn, brand["id"], product["id"], actor=ACTOR,
        fact_type="core_info", label="規格", value="6 入", status="pending",
    )

    response = TestClient(main.app).post(
        f"/api/products/brands/{brand['id']}/products/{product['id']}/facts/{fact['id']}/confirm",
        json={},
    )

    assert response.status_code == 204, response.text
    saved = bi_repo.get_product_fact(main.conn, brand["id"], product["id"], fact["id"])
    assert saved["confirmed_by"] == "使用者"
