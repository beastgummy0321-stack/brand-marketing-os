"""scripts/drill/worker.py — the real worker with the Meta stand-in and the drill clock.

    .venv/Scripts/python.exe -m scripts.drill.worker

Same as `python -m app.worker`, except `app.meta.graph.fetch_page` reads the stand-in state
and `today_for_org` reads `.scratch/drill/today` (see `clock.py`). Drill only."""

from scripts.drill import clock, fake_meta

if __name__ == "__main__":
    fake_meta.install()
    clock.install()
    import app.worker
    print(f"[drill] 時鐘已掛上 {clock.patch_modules()} 處 date/datetime")

    try:
        app.worker.main()
    except KeyboardInterrupt:
        pass
