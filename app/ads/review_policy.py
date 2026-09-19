"""Reject untraceable targets, facts and causal claims before exposing a proposal."""

import re

from app.ads import asset_suggestion_policy as policy


def unsupported_claim(text):
    if re.search(r"\d|[$€£¥]", text):
        return True
    for clause in re.split(r"[，。；！？,;.!?]|(?:但是|然而|但)", text):
        if re.search(r"已改善|造成|證明有效|caused|proven|increased revenue", clause, re.I):
            if not re.search(
                r"無法確認|不能確認|尚未確認|無法證明|不能證明|不代表|cannot confirm|not proven",
                clause,
                re.I,
            ):
                return True
    return False


def validate(conn, org, brand, evidence, reply):
    if not isinstance(reply, dict) or set(reply) != {"recommendations"}:
        raise ValueError("檢討回覆格式錯誤，未採用。")
    items = reply["recommendations"]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("每回只接受一至三項可追溯建議。")
    refs = {
        "current",
        "previous",
        "conditions",
        "campaign",
        "commerce.current",
        "commerce.previous",
    }
    if evidence["previous_review"]:
        refs.add("previous_review")
    if evidence.get("source_review"):
        refs.add("source_review")
    refs |= {f"source:{s['id']}" for s in evidence["sources"]}
    output = []
    required = {"target_id", "recommendation", "evidence_refs", "hypothesis", "risks", "next_step"}
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or not required <= set(item)
            or set(item) - required - {"suggested_copy"}
        ):
            raise ValueError("模型不得補寫金額、狀態或其他事實欄位。")
        if item["target_id"] != evidence["target"]["id"] or item["recommendation"] not in {
            "retain",
            "observe",
            "adjust",
            "new_test",
        }:
            raise ValueError("模型回傳了不同廣告或不支援的建議。")
        citations = item["evidence_refs"]
        if (
            not isinstance(citations, list)
            or not citations
            or any(not isinstance(r, str) or r not in refs for r in citations)
        ):
            raise ValueError("建議缺少可追溯的證據來源。")
        if not isinstance(item["risks"], list) or not 1 <= len(item["risks"]) <= 6:
            raise ValueError("每项判斷必須保留风险與未知。")
        texts = [item["hypothesis"], item["next_step"], *item["risks"]]
        if any(not isinstance(t, str) or not t.strip() or len(t) > 1200 for t in texts):
            raise ValueError("檢討文字缺漏或超出上限。")
        # Numeric facts are rendered directly from computed evidence by the UI.
        # This conservative filter is not a general semantic truth detector.
        if any(unsupported_claim(t) for t in texts):
            raise ValueError("模型包含未允許的數字或因果斷言；請依原始證據人工判讀。")
        copy = item.get("suggested_copy") or {}
        if (
            not isinstance(copy, dict)
            or set(copy) - {"title", "body"}
            or any(not isinstance(v, str) or len(v) > 4000 for v in copy.values())
        ):
            raise ValueError("建議文案格式錯誤。")
        if copy and policy.violations(
            conn, org, brand, copy, evidence["sources"], evidence["forbidden"], generated=True
        ):
            raise ValueError("建議文案含無法逐字追溯的事實或品牌禁語，未採用。")
        output.append(
            {
                **item,
                "id": f"recommendation-{index + 1}",
                "risks": list(dict.fromkeys([*item["risks"], *evidence["limitations"]])),
                "suggested_copy": copy,
            }
        )
    return {
        "recommendations": output,
        "limitations": evidence["limitations"],
        "causality": "unavailable",
    }
