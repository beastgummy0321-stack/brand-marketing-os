"""顧問分析報告的生成與顯示資料。

對外進入點：本檔。
輸入輸出：generate(conn, brand_id, actor, provider=None) -> (True, None) | (False, str)；
sections(report) -> list[dict]；recent(brand_id) -> bool。
誰依賴它：app.brand_web.routes、app.brand_web.routes_report_api。
不碰什麼：不 import app.brand_web.routes；不修改或 import app.brand_intelligence.report 的內部實作。
"""

from datetime import UTC

from app.brand_intelligence import report as brand_report_mod
from app.brand_intelligence import repository as repo
from app.core import settings as coresettings
from app.core.db import now_utc
from app.llm import context_compiler, gateway, providers
from app.shared import web

PROVIDER = providers.AnthropicProvider()
REPORT_SECTION_LABELS = {
    "positioning": "品牌定位",
    "market": "市場與競爭觀察",
    "audience": "受眾洞察",
    "claims": "可用宣稱與紅線",
    "rhythm": "建議節奏方向",
}

# ponytail: 手殘重整進度頁不重跑一次；真的要再生成一份，兩分鐘後再按即可
_REPORT_RECENT_SECONDS = 120


def generate(conn, brand_id: str, actor: str, provider=None) -> tuple:
    """生成一份顧問分析報告並入庫。成功回 (True, None)；失敗回 (False, 人話錯誤)，不入庫。"""
    provider = provider or PROVIDER
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")

    context_text, knowledge_item_ids, brand_version, _ = context_compiler.compile(conn, brand_id)
    products = [p["name"] for p in repo.knowledge_products(conn, brand_id)]
    source_fact_count = len(knowledge_item_ids)
    today = coresettings.today_for_org(conn, org_id=brand["org_id"]).isoformat()
    user_text = brand_report_mod._build_user_text(
        brand, products, context_text, source_fact_count, today)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id}, knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
    )
    task = gateway.run_task(
        conn, provider, brand_id=brand_id, task_type="brand_report",
        prompt_template_id="brand_report", prompt_template_version="v1",
        system=brand_report_mod._SYSTEM, messages=[{"role": "user", "content": user_text}], context=context,
        options=gateway.TaskOptions(max_tokens=16000),
    )
    if task["status"] != "succeeded":
        return False, task["error"]

    data = gateway.parse_json_reply(task["rendered_output"])
    report_sections = brand_report_mod._normalize_sections(data)
    if report_sections is None:
        return False, brand_report_mod.PARSE_FAIL_MESSAGE

    repo.create_brand_report(
        conn, brand_id, actor=actor, model=task["model"], llm_task_id=task["id"],
        brand_version=brand_version, source_fact_count=source_fact_count, sections=report_sections,
    )
    return True, None


def sections(report: dict) -> list:
    return [
        {"label": REPORT_SECTION_LABELS[key], **report["sections"][key]}
        for key in brand_report_mod.SECTION_KEYS
    ]


def recent(brand_id: str) -> bool:
    latest = repo.get_latest_brand_report(web.conn, brand_id)
    if latest is None:
        return False
    generated_at = latest["generated_at"]
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    age = (now_utc() - generated_at).total_seconds()
    return age < _REPORT_RECENT_SECONDS


# 舊 Jinja 路由仍使用這兩個名稱；票 05 移除舊頁後只保留上面的公開名稱。
_report_sections = sections
_report_recent = recent
