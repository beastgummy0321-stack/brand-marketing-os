"""HTTP transaction primitive evidence; domain regressions remain ads-owned."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.core import db
from app.shared import web


def test_handled_error_keeps_separate_attempt_receipt_but_not_business_rows():
    with db.connection() as setup:
        setup.execute("CREATE TABLE atomic_http_scratch (kind text)")
    app = FastAPI()
    app.middleware("http")(main._db_connection_middleware)
    app.add_exception_handler(web.ApiError, main.handle_api_error)

    @app.post("/edit")
    def edit():
        # A failed-attempt receipt precedes the domain operation on purpose.
        web.conn.execute("INSERT INTO atomic_http_scratch VALUES ('attempt')")
        try:
            with web.conn.atomic():
                web.conn.execute("INSERT INTO atomic_http_scratch VALUES ('business')")
                web.conn.commit()
                raise ValueError("rejected")
        except ValueError:
            raise web.ApiError(400, "rejected", "Rejected") from None

    try:
        response = TestClient(app).post("/edit")
        assert response.status_code == 400, response.text
        with db.connection() as observer:
            assert observer.execute("SELECT kind FROM atomic_http_scratch").fetchall() == [
                {"kind": "attempt"}]
    finally:
        with db.connection() as cleanup:
            cleanup.execute("DROP TABLE atomic_http_scratch")
