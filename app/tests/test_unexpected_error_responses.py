"""Exercise production error handlers through HTTP without application startup."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import main
from app.shared.web import ApiError

_PRIVATE_ERROR = "private database password=do-not-expose"
_SAFE_MESSAGE = "系統出了點狀況，再試一次。"


@pytest.fixture
def client():
    isolated = FastAPI(exception_handlers=main.app.exception_handlers.copy())

    @isolated.get("/api/crash")
    @isolated.get("/page/crash")
    @isolated.get("/apiary/crash")
    @isolated.get("/api")
    def crash():
        raise RuntimeError(_PRIVATE_ERROR)

    @isolated.get("/api/business-error")
    def business_error():
        raise ApiError(409, "conflict", "請先完成目前工作。", {"field": "state"})

    @isolated.get("/api/forbidden")
    def forbidden():
        raise HTTPException(403, "沒有權限", headers={"X-Reason": "policy"})

    @isolated.get("/api/number")
    def number(value: int):
        return {"value": value}

    with TestClient(isolated, raise_server_exceptions=False) as http:
        yield http


def test_unexpected_api_error_returns_safe_json(client):
    response = client.get("/api/crash")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "error": {"code": "internal", "message": _SAFE_MESSAGE, "details": None}
    }
    assert _PRIVATE_ERROR not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize("path", ["/page/crash", "/apiary/crash", "/api"])
def test_non_api_unexpected_error_keeps_safe_html(client, path):
    response = client.get(path)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!doctype html>")
    assert _SAFE_MESSAGE in response.text
    assert _PRIVATE_ERROR not in response.text
    assert "Traceback" not in response.text


def test_not_found_keeps_api_json_and_page_html(client):
    api = client.get("/api/missing")
    assert api.status_code == 404
    assert api.json() == {"detail": "找不到頁面"}

    page = client.get("/missing")
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")
    assert "找不到這一頁。" in page.text


def test_business_error_keeps_status_and_envelope(client):
    response = client.get("/api/business-error")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "message": "請先完成目前工作。",
            "details": {"field": "state"},
        }
    }


def test_http_exception_keeps_status_detail_and_headers(client):
    response = client.get("/api/forbidden")

    assert response.status_code == 403
    assert response.json() == {"detail": "沒有權限"}
    assert response.headers["X-Reason"] == "policy"


def test_request_validation_still_returns_422(client):
    response = client.get("/api/number", params={"value": "invalid"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "value"]
