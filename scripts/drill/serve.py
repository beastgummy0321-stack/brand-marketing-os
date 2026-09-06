"""scripts/drill/serve.py — start the real backend with the Meta stand-in installed.

    .venv\\Scripts\\python.exe -m scripts.drill.serve --port 8710

Same app, same routes, same database; the only difference is that `app.meta.graph.fetch_page`
reads `scripts/drill/fake_meta.py`'s state file instead of graph.facebook.com. Drill only —
never start the product this way for anything a real user will see.
"""

import argparse

import uvicorn

from scripts.drill import fake_meta

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m scripts.drill.serve")
    parser.add_argument("--port", type=int, default=8710)
    args = parser.parse_args()

    fake_meta.install()  # before app.main is imported by uvicorn's factory-free import below
    import app.main

    print(f"[drill] Meta 替身已掛上，狀態檔 {fake_meta.STATE_PATH}")
    uvicorn.run(app.main.app, host="127.0.0.1", port=args.port)
