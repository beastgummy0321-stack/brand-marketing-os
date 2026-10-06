"""scripts/drill/worker.py — the real worker with the Meta stand-in and the drill clock.

    .venv/Scripts/python.exe -m scripts.drill.worker

Same as `python -m app.worker`, except `app.meta.graph.fetch_page` reads the stand-in state
and `today_for_org` reads `.scratch/drill/today` (see `clock.py`). Drill only."""

from scripts.drill import clock, fake_meta, recovery_probe, site

if __name__ == "__main__":
    recovery_context = recovery_probe.child_boot("worker")
    fake_meta.install()
    clock.install()
    import app.worker

    site.install()  # drill 9: AI prefill reads the frozen site copy
    recovery_probe.install_provider(recovery_context, "worker")
    print(f"[drill] 時鐘已掛上 {clock.patch_modules()} 處 date/datetime")

    try:
        app.worker.main()
    except KeyboardInterrupt:
        pass
