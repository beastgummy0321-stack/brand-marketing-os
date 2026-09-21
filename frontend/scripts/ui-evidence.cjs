/* Side-by-side evidence for a UI issue (design-system §1.7): prototype screen | built screen, at 1024 and 1920.
 *
 * Run it FIRST with only --proto/--hash: it shoots the prototype in its default state and writes the screen's
 * facts (container max-widths, fold states, every control's target, and "pieces": which kit component and variant
 * each prototype button/chip maps to — build with exactly those, do not re-decide emphasis) — read them before building.
 * Run it again with --app once the page renders: built shots, built facts, side-by-side images and diff-<name>.txt.
 *
 *   node scripts/ui-evidence.cjs --proto ../docs/design/ads/prototype-v7-ads-center.html --hash camp/sales \
 *     --name with-target --out ../.harness/scratch/F21/I01 \
 *     [--acts approve,report]   prototype-only: click these data-act buttons first (a step reachable only through earlier steps)
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
    if (!vis(e) || e.closest("nav")) continue; // the app breadcrumb stands in for the prototype's crumb/back bar, which live outside #app
    const c = e.classList;
    let piece = null;
    if (e.dataset.slot === "button") piece = `Button ${e.dataset.variant}`;
    else if (e.dataset.slot === "chip") piece = `Chip ${e.dataset.tone}`;
    else if (e.dataset.slot === "badge") piece = `Badge ${e.dataset.variant}`;
    else if (c.contains("btn")) piece = `Button ${c.contains("pri") ? "default" : c.contains("ghost") ? "ghost" : "outline"}`;
    else if (c.contains("lnk")) piece = "Button link";
    else if (c.contains("chip")) piece = `Chip ${c.contains("ok") ? "ok" : c.contains("warn") ? "warn" : c.contains("bad") ? "bad" : c.contains("v") ? "accent" : "neutral"}`;
    else if (e.tagName === "A" || e.tagName === "BUTTON") piece = "(hand-rolled control)";
    if (piece) out.push(`${piece} | ${e.innerText.replace(/\s+/g, " ").slice(0, 50)}`);
  }
  // Prototype side only: classes on this screen that map to no kit piece. At carve time the lead decides for each:
  // layout only (the worker builds it with tokens) or a missing piece (add it to components/ads/patterns first).
  if (!document.querySelector("#main-content")) {
    const known = new Set(["btn", "pri", "ghost", "sm", "lnk", "chip", "ok", "warn", "bad", "v"]);
    const seen = {};
    for (const e of within("[class]")) if (vis(e)) for (const c of e.classList) if (!known.has(c)) seen[c] = (seen[c] || 0) + 1;
    out.push("", "## prototype classes with no kit mapping (class x count)", Object.entries(seen).map(([c, n]) => `${c} x${n}`).join(", "));
  }
  out.push("", "## visible text, in reading order", document.body.innerText.replace(/\n{2,}/g, "\n"));
  return out.join("\n");
}

async function shoot(context, url, kind, setup, acts = []) {
  let text = "";
  for (const width of WIDTHS) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 1200 });
    page.on("pageerror", (e) => console.log(`[pageerror ${kind} ${width}]`, e.message));
    if (setup) await setup(page);
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
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
  await shoot(context, "file:///" + path.resolve(args.proto).replace(/\\/g, "/") + HASH, "reference", null, (args.acts || "").split(",").filter(Boolean));

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
