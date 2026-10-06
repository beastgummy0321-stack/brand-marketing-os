"""scripts/drill/serve.py — start the real backend with the Meta stand-in installed.

    .venv\\Scripts\\python.exe -m scripts.drill.serve --port 8710

Same app, same routes, same database; the only difference is that `app.meta.graph.fetch_page`
reads `scripts/drill/fake_meta.py`'s state file instead of graph.facebook.com. Drill only —
never start the product this way for anything a real user will see.
"""

import argparse

import uvicorn

from scripts.drill import clock, fake_meta, recovery_probe, site

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m scripts.drill.serve")
    parser.add_argument("--port", type=int, default=8710)
    args = parser.parse_args()

    recovery_context = recovery_probe.child_boot("web")
    fake_meta.install()  # before app.main is imported by uvicorn's factory-free import below
    clock.install()  # drill 6: `.scratch/drill/today` overrides today_for_org
    import app.main

    site.install()  # drill 9: AI prefill reads the frozen site copy
    recovery_probe.install_provider(recovery_context, "web")
    print(f"[drill] 時鐘已掛上 {clock.patch_modules()} 處 date/datetime")

    print(f"[drill] Meta 替身已掛上，狀態檔 {fake_meta.STATE_PATH}")
    application = (
        recovery_probe.ResponseBoundary(app.main.app, recovery_context)
        if recovery_context
        else app.main.app
    )
    uvicorn.run(application, host="127.0.0.1", port=args.port)
