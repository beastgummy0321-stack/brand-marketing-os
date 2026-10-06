# Drill 12 — audit-chain acceptance

Authorized continuation of F48–F51. Reuse `../drill-10/plan.md` for the nine dimensions, thresholds, control inventory,
fault scenarios and independent blind judging, and `../drill-11/plan.md` for setup. No product repair during the run except
a proven common stop-condition blocker under `../README.md`; any such repair requires an explicit before/after build record.

- Code baseline: F51's fully integrated head, recorded in operator evidence before the first persona action.
- New local accounts: beast.drill12@example.com (B), beast.drill12f@example.com (faults), and a separate controls-A account.
- Local server: http://localhost:8737/app/login. Fresh backend and worker; provider remains `codex_cli`.
- Isolated fake Meta state: `.harness/scratch/drill12/operator/meta_state.json` via `DRILL_META_STATE`; reset only this file.
- Fixed drill dates: P1 2026-10-03–09, P2 10–16, P3 17–23, closeout 24. The existing clock tool uses Taipei local time.
- Frozen A evidence stays unchanged; B uses the same simulation/judging contract. Report default per-ad audience and the
  secondary group-audience result separately. Simulation does not establish advertising performance.
- Browser tool: the host's `cua_repl`; old playwright-cli instructions in historical dispatches are superseded.
- Persona sees only its character/rules, brand facts, dispatch and account. Operator handles platform simulation and exports.
  Control and fault checks run on spare objects or separate accounts after B's three periods and exports.
- Threshold: each of nine dimensions >= 7 and zero blocking defects. Untested controls and missing evidence are not passes.
- F51 retains the active-AI-queue W14 exception, user confirmed 2026-10-06; backend outcome redesign is outside this run.
- F48–F51 remain open until the user sees combined screenshots and drill results and explicitly accepts them. No push.

Status: preparation only; no persona run or score yet.
