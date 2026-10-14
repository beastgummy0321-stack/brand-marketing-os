"""Offline, explicit saved-output replay. No database, provider, queue or history discovery."""

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from app.ads import review_jobs, review_policy, review_rounds


class ContextUnavailable(RuntimeError):
    pass


class NoDatabase:
    def execute(self, *args, **kwargs):
        raise ContextUnavailable("Historical brand/learning policy context was not supplied")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[redacted]"
            if re.search(r"password|secret|token|api.?key|authorization", k, re.I)
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"https?://[^\s\"<>]+", "[url]", value)
        value = re.sub(r"(?i)bearer\s+\S+|\bsk-[A-Za-z0-9_-]+", "[redacted]", value)
        return re.sub(
            r"(?i)\b(password|secret|token|api.?key)\s*[:=]\s*[^\s,;]+", "[redacted]", value
        )
    return value


def input_state(case, task):
    capture = case.get("input_capture")
    if capture:
        bound = (
            capture.get("task_id") == task["id"]
            and capture.get("template_hash") == task.get("prompt_template_version")
            and capture.get("sha256") == sha(capture.get("text", ""))
        )
        return {
            "state": "exact_saved" if bound else "unknown",
            "capture_bound": bound,
            "delivery_proof": "unknown",
            "source_kind": case.get("source_kind", "unknown"),
        }
    return {
        "state": "regenerated" if case.get("regenerated_input") is not None else "unknown",
        "capture_bound": False,
        "delivery_proof": "unknown",
    }


def replay(case):
    review, task = deepcopy(case["review"]), deepcopy(case["task"])
    evidence = review["evidence_json"]
    result = {
        "case_id": case["id"],
        "source_kind": case.get("source_kind", "unknown"),
        "identity": {
            "review_id": review["id"],
            "task_id": task["id"],
            "evidence_hash": review["evidence_hash"],
            "template_id": task.get("prompt_template_id"),
            "template_hash": task.get("prompt_template_version"),
        },
        "inputs": input_state(case, task),
        "validator": "unknown",
        "projection": None,
        "stored_projection": case.get("stored_projection"),
        "human_judgment": case.get(
            "human_judgment", {"grounding": "unverified", "usefulness": "unverified"}
        ),
        "limits": [
            "offline_saved_bytes_only",
            "no_model_or_platform_success_proof",
            "current_validator_not_historical_validator",
            "learning_context_not_rechecked",
        ],
    }
    try:
        review_jobs.validate_saved_binding(review, task)
        if review_rounds.evidence_digest(evidence) != review["evidence_hash"]:
            raise review_policy.ReviewRejection(
                "evidence_digest_mismatch", "Saved evidence changed"
            )
        if task.get("status") != "succeeded":
            result["reason_code"] = "output_not_succeeded"
        else:
            result["projection"] = review_jobs.evaluate_saved_output(NoDatabase(), review, task)
            result["validator"] = "accepted"
    except review_policy.ReviewRejection as exc:
        result.update(validator="rejected", reason_code=exc.code)
        result["projection"] = {
            "recommendations": [],
            "limitations": evidence["limitations"],
            "causality": "unavailable",
            "rejected": {"code": exc.code, "reason": str(exc)},
        }
    except ContextUnavailable:
        result["reason_code"] = "policy_context_unavailable"
    if result["stored_projection"] is None:
        result["storage_match"] = "unknown"
    else:
        result["storage_match"] = result["projection"] == result["stored_projection"]
    return redact(result)


def fixture_case(name, **changes):
    evidence = {
        "target": {"id": "ad-fixture"},
        "previous_review": None,
        "sources": [],
        "limitations": ["Synthetic fixture; causality unavailable"],
        "provider": "scripted",
        "model": "fixture",
        "template_hash": "template-fixture",
        "current": {"result_kind": "lead", "result_count": None},
        "previous": {},
    }
    item = {
        "target_id": "ad-fixture",
        "recommendation": "observe",
        "evidence_refs": ["current"],
        "hypothesis": "目前資料仍有限",
        "risks": ["無法證明因果"],
        "next_step": "確認來源後再決定",
    }
    item.update(changes)
    digest = review_rounds.evidence_digest(evidence)
    review = {
        "id": "review-" + name,
        "org_id": "org-fixture",
        "brand_id": "brand-fixture",
        "campaign_id": "campaign-fixture",
        "evidence_json": evidence,
        "evidence_hash": digest,
    }
    task = {
        "id": "task-" + name,
        "org_id": review["org_id"],
        "brand_id": review["brand_id"],
        "task_type": review_rounds.TASK_TYPE,
        "provider": "scripted",
        "model": "fixture",
        "prompt_template_id": "ads/review_round",
        "prompt_template_version": "template-fixture",
        "context_scope_json": {
            "review_id": review["id"],
            "campaign_id": review["campaign_id"],
            "evidence_hash": digest,
        },
        "status": "succeeded",
        "rendered_output": json.dumps({"recommendations": [item]}, ensure_ascii=False),
    }
    return {"id": name, "source_kind": "synthetic", "review": review, "task": task}


def corpus():
    cases = [
        fixture_case("proposed_duration", next_step="再觀察7天"),
        fixture_case("grounded_figure", hypothesis="目前有10筆名單"),
        fixture_case("unmeasured_quality", hypothesis="名單品質明顯變差"),
        fixture_case("bad_target", target_id="different-ad"),
        fixture_case("bad_ref", evidence_refs=["invented-source"]),
        fixture_case("missing_delayed", next_step="補讀延遲資料，核實成果定義"),
        fixture_case("incompatible_unit", next_step="先核實幣別與成果單位再比較"),
        fixture_case("task_mismatch"),
    ]
    cases[1]["review"]["evidence_json"]["current"]["result_count"] = 10
    cases[2]["review"]["evidence_json"]["current"]["quality_measurement"] = "unavailable"
    cases[5]["review"]["evidence_json"]["limitations"].append("Delayed read; missing data")
    cases[6]["review"]["evidence_json"]["current"]["comparison_reason"] = "result_kind_mismatch"
    for case in cases:
        digest = review_rounds.evidence_digest(case["review"]["evidence_json"])
        case["review"]["evidence_hash"] = digest
        case["task"]["context_scope_json"]["evidence_hash"] = digest
    cases[-1]["task"]["context_scope_json"]["evidence_hash"] = "changed"
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input and args.input.stat().st_size > 2_000_000:
        parser.error("Explicit corpus exceeds offline size bound")
    cases = json.loads(args.input.read_text("utf-8")) if args.input else corpus()
    if not isinstance(cases, list) or len(cases) > 100:
        parser.error("Use an explicit list of at most 100 sanitized cases")
    output = {"schema_version": 1, "mode": "offline", "cases": [replay(case) for case in cases]}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"mode": "offline", "cases": len(cases), "report": str(args.output)}))


if __name__ == "__main__":
    main()
