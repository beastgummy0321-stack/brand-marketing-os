/* Side-by-side evidence for a UI issue (design-system §1.7): prototype screen | built screen, at 1024 and 1920.
 *
 * Run it FIRST with only --proto/--hash: it shoots the prototype in its default state and writes the screen's
 * facts (container max-widths, fold states, every control's target, and "pieces": which kit component and variant
 * each prototype button/chip maps to — build with exactly those, do not re-decide emphasis) — read them before building.
 * Run it again with --app once the page renders: built shots, built facts, side-by-side images and diff-<name>.txt.
 *
 *   node scripts/ui-evidence.cjs --proto ../docs/design/ads/prototype-v7-ads-center.html --hash camp/sales \
 *     --name with-target --out ../.harness/scratch/F21/I01 \
 *     [--settle 1500] wait longer before shooting (prototype async demo states, e.g. 「AI 正在整理證據」)
 *     [--demos home:syncing,tgt:none]  prototype-only: on first load (no hash) click these `[data-demo="<k>"]` buttons of the
 *                               prototype-note box in order, THEN apply --hash; the demo state is in-memory, so it survives
 *                               the hash change (a state that exists only through the demo box, e.g. `stale`, `over`)
 *     [--acts approve,report]   prototype-only: click these data-act buttons first (a step reachable only through earlier steps)
 *                               — runs after --demos and --hash
 *     [--app brands/brd_bughunt/ads/campaigns/cmp_x/detail --base http://127.0.0.1:8732 --mocks mocks.json]
 *
 * --mocks: JSON object { "<url glob>": <response json> }, e.g. { "**" + "/api/ads/brands/*" + "/queue": {...} }.
 * The app side needs a backend serving this worktree's build on --base (own port, §1.7 item 8) and `supabase start`.
 * Never expand, scroll or click before shooting: a fold mismatch must stay visible in the evidence.
 */
const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, "")] = process.argv[i + 1];
for (const k of ["proto", "hash", "name", "out"]) if (!args[k]) { console.error(`missing --${k}`); process.exit(2); }
const OUT = path.resolve(args.out);
const BASE = args.base || "http://127.0.0.1:8710";
// Git Bash rewrites arguments that start with "/" (and "#/…") into Windows paths, so both are given bare.
const HASH = "#/" + args.hash.replace(/^#?\/?/, "");
const APP = args.app && "/" + args.app.replace(/^\//, "");
const WIDTHS = [1024, 1920];
fs.mkdirSync(OUT, { recursive: true });

function facts() {
  const vis = (e) => e.getClientRects().length > 0;
  const label = (e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (typeof e.className === "string" && e.className ? "." + e.className.trim().split(/\s+/).slice(0, 3).join(".") : "");
  const out = ["## containers (max-width, rendered width)"];
  for (const e of document.querySelectorAll("body *")) {
    const mw = getComputedStyle(e).maxWidth;
    if (mw !== "none" && vis(e) && e.getBoundingClientRect().width >= 400) out.push(`${label(e)}  max-width:${mw}  width:${Math.round(e.getBoundingClientRect().width)}`);
  }
  // Screen content only: the app's <main>, or the prototype's #app (its crumb and back bar are shell). The shell is not part of a screen issue.
  const roots = document.querySelector("#main-content") ? [document.querySelector("#main-content")] : [...document.querySelectorAll("#app")];
  const within = (sel) => roots.flatMap((r) => [...r.querySelectorAll(sel)]);
  out.push("", "## folds (default state)");
  for (const d of within("details")) if (vis(d)) out.push(`${d.open ? "OPEN  " : "CLOSED"} ${(d.querySelector("summary")?.innerText || "").replace(/\s+/g, " ").slice(0, 100)}`);
  for (const e of within("[aria-expanded]")) if (vis(e)) out.push(`${e.getAttribute("aria-expanded") === "true" ? "OPEN  " : "CLOSED"} ${e.innerText.replace(/\s+/g, " ").slice(0, 100)}`);
  out.push("", "## controls (text -> target)");
  for (const e of document.querySelectorAll("a, button")) {
    if (!vis(e)) continue;
    const target = e.getAttribute("href") || e.dataset.go || (e.dataset.act && "act:" + e.dataset.act) || (e.dataset.toast && "toast:" + e.dataset.toast) || "";
    out.push(`${e.innerText.replace(/\s+/g, " ").slice(0, 60)} -> ${target}${e.disabled ? " (disabled)" : ""}`);
  }
  // Prototype vocabulary -> kit piece. The reference side prints what to build with; the built side prints what was used.
  out.push("", "## pieces (kit component to use | text)");
  for (const e of within("button, a, .chip, [data-slot=chip], [data-slot=badge]")) {
    if (!vis(e) || e.closest("nav") || e.closest(".dots, [data-slot=flow-header]")) continue; // step dots belong to FlowHeader // the app breadcrumb stands in for the prototype's crumb/back bar, which live outside #app
    if (e.closest(".rl, .sc, [data-slot=target-ruler], [data-slot=scenario-bars]") && !e.matches(".chip, [data-slot=chip]")) continue; // ruler dots and scenario rows are part of their piece
    const c = e.classList;
    let piece = null;
    if (e.dataset.slot === "button") piece = `Button ${e.dataset.variant}`;
    else if (e.dataset.slot === "chip") piece = `Chip ${e.dataset.tone}`;
    else if (e.dataset.slot === "badge") piece = `Badge ${e.dataset.variant}`;
    else if (c.contains("btn")) piece = `Button ${c.contains("pri") ? "default" : c.contains("warnp") ? "warn" : c.contains("ghost") ? "ghost" : "outline"}`; // warnp -> patterns/ConfirmSheet WarnButton
    else if (c.contains("lnk")) piece = "Button link";
    else if (c.contains("chip")) piece = `Chip ${c.contains("over") ? "over" : c.contains("stop") ? "stop" : c.contains("ok") ? "ok" : c.contains("warn") ? "warn" : c.contains("bad") ? "bad" : c.contains("v") ? "accent" : "neutral"}`; // v9 grade chips: patterns/Chip GradeChip
    else if (e.tagName === "A" || e.tagName === "BUTTON") piece = "(hand-rolled control)";
    if (piece) out.push(`${piece} | ${e.innerText.replace(/\s+/g, " ").slice(0, 50)}`);
  }
  // Non-control pieces (components/ads/patterns/FlowPieces): prototype class -> piece, built side by data-slot.
  const BLOCKS = { camp: "CampaignChip", tag: "TagToggle", learn: "LearnCard", rec: "RecoverSteps", tiles: "ThumbTiles", days: "DayTiles", ev: "EvidenceRow", ladder: "Ladder", opt: "OptionCard", old: "CopyBlock", new: "CopyBlock", dots: "FlowHeader", kind: "KindMark", meter: "Meter", todo: "TodoRow", hero: "ResultHero", rail: "StatusRail", seg: "Segmented", sheet: "DecisionSheet" };
  const SLOTS = { "campaign-chip": "CampaignChip", "tag-toggle": "TagToggle", "learn-card": "LearnCard", "recover-steps": "RecoverSteps", "thumb-tiles": "ThumbTiles", "day-tiles": "DayTiles", "evidence-row": "EvidenceRow", ladder: "Ladder", "option-card": "OptionCard", "copy-block": "CopyBlock", "flow-header": "FlowHeader", "kind-mark": "KindMark", meter: "Meter", "todo-row": "TodoRow", "result-hero": "ResultHero", "status-rail": "StatusRail", segmented: "Segmented", "decision-sheet": "DecisionSheet",
    "target-ruler": "TargetRuler", "grade-band": "GradeBand", "money-meter": "MoneyMeter", "pace-chart": "PaceChart", "next-up-strip": "NextUpStrip", "scenario-bars": "ScenarioBars", "allocation-bar": "AllocationBar", "confirm-sheet": "ConfirmSheet", "diff-row": "DiffRow", "cap-dots": "CapDots", "progress-segments": "ProgressSegments" };
  const VARIANT = { kind: ["stop", "worse", "up", "fresh", "cut"], todo: ["ok"], hero: ["ok", "warn", "bad"], opt: ["pick"], old: ["old"], new: ["new"] };
  const NOVARIANT = new Set(["campaign-chip", "tag-toggle", "learn-card", "recover-steps", "thumb-tiles", "day-tiles", "meter", "evidence-row", "ladder", "option-card",
    "grade-band", "pace-chart", "next-up-strip", "scenario-bars", "allocation-bar", "diff-row", "cap-dots", "progress-segments"]); // colour/state comes from data or a decision, not a prototype class
  // v9 pieces (F28): prototype selector -> "<piece> <variant>", one line per piece; the built side reports them by data-slot above.
  const V9 = [
    [".rl", (e) => `TargetRuler ${["mini", "mid", "full"].find((s) => e.classList.contains(`rl-${s}`)) || "empty"}`], // ruler(); its tray sits beside it
    [".band", () => "GradeBand"], // homeBand()
    [".cpm", () => "MoneyMeter lg"], [".hb", () => "MoneyMeter sm"], // cost meter with the cap line
    [".moneyg svg", () => "PaceChart"], [".nextup", () => "NextUpStrip"], // homeMoney() pace chart, homeNext()
    ["[role=radiogroup]:has(> .sc)", () => "ScenarioBars"], [".alloc", () => "AllocationBar"], // budgetBlock(), allocBlock()
    [".confirm", () => "ConfirmSheet over-cap"], [".sheet:has(.warnp)", () => "ConfirmSheet revert"], // over-cap confirm, act.revertOpen
    [".diff", () => "DiffRow"], [".capdots", () => "CapDots"], [".prog", () => "ProgressSegments"],
  ];
  for (const e of within("[class], [data-slot], svg[role=img]")) { // the pace chart is a bare <svg>
    if (!vis(e)) continue;
    if (SLOTS[e.dataset.slot]) { out.push(`${SLOTS[e.dataset.slot]} ${NOVARIANT.has(e.dataset.slot) ? "" : e.dataset.variant || ""}`.trim() + " |"); continue; } // the prototype meter carries its colour inline, not as a class
    if (document.querySelector("#main-content")) continue;
    for (const [sel, piece] of V9) if (e.matches(sel)) out.push(`${piece(e)} |`);
    if (e.closest(".tray") || e.matches(".sheet:has(.warnp)")) continue; // the ruler tray's meters belong to TargetRuler; a warn sheet is ConfirmSheet
    for (const [cls, piece] of Object.entries(BLOCKS)) if (e.classList.contains(cls)) {
      let v = (VARIANT[cls] || []).find((x) => e.classList.contains(x)) || "";
      if (cls === "todo") v = v ? "done" : "open";
      if (["opt", "ev", "ladder", "days", "camp", "tag", "learn", "rec", "tiles"].includes(cls)) v = "";
      if (cls === "old" || cls === "new") v = cls;
      out.push(`${piece} ${v}`.trim() + " |");
    }
  }
  // Prototype side only: classes on this screen that map to no kit piece. At carve time the lead decides for each:
  // layout only (the worker builds it with tokens) or a missing piece (add it to components/ads/patterns first).
  if (!document.querySelector("#main-content")) {
    const known = new Set(["btn", "pri", "ghost", "sm", "lnk", "chip", "ok", "warn", "bad", "v", "sh", "dots", "d", "dl", "done", "on", "qpos", "row", "purpose", "kind", "stop", "worse", "up", "fresh", "meter", "cap", "todo", "no", "hero", "big", "rail", "seg", "sheet", "fld", "ev", "l", "bars", "c", "n", "dd", "q", "unk", "ladder", "opt", "pick", "ic", "old", "new", "rv", "grid2", "grid4", "days", "x", "strip", "tiles", "cols3", "camp", "tag", "learn", "rec", "o-sales", "o-engage", "o-traffic", "o-mid", "o-old"]);
    // Parts of the v9 pieces above (ruler, band, meters, scenario bars, confirm, diff, capacity dots, progress) and their states.
    for (const c of ["rl", "rl-mini", "rl-mid", "rl-full", "rl-empty", "ax", "fd", "trk", "mk", "be", "r", "zl", "sb", "dt", "bx", "k", "tip", "tl", "tr", "hl", "cx", "dim", "na", "tray", "ti", "watch", "over", "gr",
      "band", "sl", "hatch", "cpm", "hb", "nextup", "tlg", "dot", "sc", "lab", "bw", "amt", "o", "caprow", "capline", "alloc", "confirm", "bb", "warnp", "diff", "w", "capdots", "prog", "chg", "bt", "dev", "lock", "cut", "dn", "s", "b"]) known.add(c);
    // Layout and type only — no piece: the worker builds these with tokens (cards, grids, rows, text styles, thumbnails, folds, inputs).
    const LAYOUT = new Set(["hstack", "titlerow", "wrap", "card", "hd", "grow", "mut", "num", "xs", "nm", "th", "stack", "g2", "g3", "lg", "f", "in", "money", "qi", "val", "tabs", "grp", "sw", "adrow",
      "moneyg", "paceh", "left", "bandc", "decg", "dcard", "dr", "skel", "empty", "ct", "hd0", "act", "tgt"]);
    const seen = {}, layout = {};
    for (const e of within("[class]")) if (vis(e)) for (const c of e.classList) if (LAYOUT.has(c)) layout[c] = (layout[c] || 0) + 1; else if (!known.has(c)) seen[c] = (seen[c] || 0) + 1;
    out.push("", "## prototype layout classes (no piece: build with tokens)", Object.entries(layout).map(([c, n]) => `${c} x${n}`).join(", "));
    out.push("", "## prototype classes with no kit mapping (class x count)", Object.entries(seen).map(([c, n]) => `${c} x${n}`).join(", "));
  }
  out.push("", "## visible text, in reading order", document.body.innerText.replace(/\n{2,}/g, "\n"));
  return out.join("\n");
}

async function shoot(context, url, kind, setup, acts = [], demos = []) {
  let text = "";
  for (const width of WIDTHS) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 1200 });
    page.on("pageerror", (e) => console.log(`[pageerror ${kind} ${width}]`, e.message));
    if (setup) await setup(page);
    if (demos.length) {
      // --demos: load the prototype without the hash, click the demo buttons in order, then route to --hash in place
      // (a reload would reset the prototype's in-memory state the demos just set).
      await page.goto(url.split("#")[0]);
      await page.waitForLoadState("networkidle");
      for (const demo of demos) {
        const button = page.locator(`[data-demo="${demo}"]`);
        if (!(await button.count())) throw new Error(`--demos: no [data-demo="${demo}"] in the prototype`);
        await button.first().click();
        await page.waitForTimeout(200);
      }
      await page.evaluate((hash) => { if (location.hash !== hash) location.hash = hash; }, HASH);
    } else {
      await page.goto(url);
    }
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(Number(args.settle) || 400); // --settle <ms>: a prototype screen that finishes an async demo state
    // --acts: prototype `data-act` names clicked in order to REACH a screen that only exists after earlier steps.
    for (const act of acts) { await page.locator(`[data-act="${act}"]`).first().click(); await page.waitForTimeout(300); }
    await page.screenshot({ path: `${OUT}/${kind}-${args.name}-${width}.png`, fullPage: true });
    text += `# ${kind} ${args.name} @${width}\n${await page.evaluate(facts)}\n\n`;
    await page.close();
  }
  fs.writeFileSync(`${OUT}/facts-${kind}-${args.name}.txt`, text, "utf-8");
  console.log(`saved ${kind}-${args.name}-{1024,1920}.png, facts-${kind}-${args.name}.txt`);
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const list = (v) => (v || "").split(",").filter(Boolean);
  await shoot(context, "file:///" + path.resolve(args.proto).replace(/\\/g, "/") + HASH, "reference", null, list(args.acts), list(args.demos));

  if (args.app) {
    const mocks = args.mocks ? JSON.parse(fs.readFileSync(args.mocks, "utf-8")) : {};
    const page = await context.newPage();
    await page.goto(`${BASE}/app/login`);
    await page.getByLabel("Email").fill("123@example.com");
    await page.getByLabel("密碼").fill("123456");
    await page.getByRole("button", { name: "登入", exact: true }).click();
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 15000 });
    await page.close();
    await shoot(context, `${BASE}/app${APP}`, "built", async (p) => {
      for (const [glob, json] of Object.entries(mocks)) await p.route(glob, (route) => route.fulfill({ json }));
    });

    const page2 = await context.newPage();
    for (const width of WIDTHS) {
      const img = (kind) => "data:image/png;base64," + fs.readFileSync(`${OUT}/${kind}-${args.name}-${width}.png`).toString("base64");
      await page2.setViewportSize({ width: 2200, height: 1200 });
      await page2.setContent(`<body style="margin:0;background:#e5e7eb;font:13px sans-serif">
        <h2 style="margin:0;padding:10px 16px;background:#111827;color:#fff;font-size:15px">${args.name}・${width}px</h2>
        <div style="display:flex;align-items:flex-start;gap:4px">
          <div style="flex:1;min-width:0"><div style="padding:6px 12px;background:#374151;color:#fff">reference (prototype, default state)</div><img style="display:block;width:100%" src="${img("reference")}"></div>
          <div style="flex:1;min-width:0"><div style="padding:6px 12px;background:#374151;color:#fff">built</div><img style="display:block;width:100%" src="${img("built")}"></div>
        </div></body>`);
      await page2.screenshot({ path: `${OUT}/side-by-side-${args.name}-${width}.png`, fullPage: true });
    }
    console.log(`saved side-by-side-${args.name}-{1024,1920}.png`);

    // Mechanical comparison at 1920: content max-width, fold states, and how many of each kit piece.
    const section = (kind, title) => {
      const text = fs.readFileSync(`${OUT}/facts-${kind}-${args.name}.txt`, "utf-8").split(`# ${kind} ${args.name} @1920`)[1] || "";
      return (text.split(`## ${title}`)[1] || "").split("\n## ")[0].split("\n").slice(1).filter(Boolean);
    };
    const count = (lines, key) => lines.reduce((m, l) => { const k = key(l); m[k] = (m[k] || 0) + 1; return m; }, {});
    const report = [];
    const widths = (kind) => section(kind, "containers").map((l) => (l.match(/max-width:(\S+)/) || [])[1]).filter((w) => w !== "1920px").join(",");
    if (widths("reference") !== widths("built")) report.push(`content max-width: reference ${widths("reference")} | built ${widths("built")}`);
    for (const [title, key] of [["pieces", (l) => l.split(" | ")[0]], ["folds", (l) => l.slice(0, 6).trim()]]) {
      const a = count(section("reference", title), key), b = count(section("built", title), key);
      for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) if ((a[k] || 0) !== (b[k] || 0)) report.push(`${title}: ${k} — reference ${a[k] || 0} | built ${b[k] || 0}`);
    }
    const body = report.length ? report.join("\n") : "no differences in content width, fold states or kit pieces";
    const note = "(counts differ legitimately when the fixture has more or fewer rows than the prototype; a piece TYPE that exists on one side only is a real mismatch)";
    fs.writeFileSync(`${OUT}/diff-${args.name}.txt`, `${body}\n${note}\n`, "utf-8");
    console.log(`--- diff-${args.name}.txt ---\n${body}`);
  }
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
