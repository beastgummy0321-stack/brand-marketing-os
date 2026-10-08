import {expect, test, type Page} from "@playwright/test";
import {mkdir,writeFile} from "node:fs/promises";
import path from "node:path";
import {SETTLE_BRAND, SETTLE_MONTH, settleEvidence, nextPeriodEvidence} from "../src/components/ads/settle/settleEvidence.fixtures";
import {MONTH_RULES} from "../src/components/ads/month/monthEvidence.fixtures";
import {wizardRecoveryOptions, wizardRecoveryUploads, wizardRecoveryCampaign} from "../src/components/ads/wizard/wizardRecovery.fixtures";
import type {CampaignPicks} from "../src/lib/adsWizardApi";

test.use({viewport:{width:Number(process.env.F54_I12_WIDTH)||1024,height:1080}});

async function setup(page: Page, options: {written?: boolean; failedSource?: boolean; empty?: boolean; notEnded?: boolean; long?: boolean; failedSave?: boolean} = {}) {
  const user = {id: "settle-ui-user", email: "settle-ui@example.com", aud: "authenticated", role: "authenticated"};
  const org = {id: "settle-ui-org", name: "來源接續測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-23"};
  let failed = options.failedSource, failedSave = options.failedSave;
  let view = settleEvidence(options.written ? "written" : options.notEnded ? "not_ended" : "open");
  const source = nextPeriodEvidence();
  if (options.empty) {view.rows = []; view.campaigns = []; view.results = view.cost_per_result = view.spent = null; source.source_campaigns = []; source.eligible_learning_refs = [];}
  if (options.notEnded) {view.month = "2026-09"; view.start = "2026-09-01"; view.end = "2026-09-30"; view.days = 30;}
  if (options.written) view.rows[0] = {...view.rows[0], fate: "skip", grade: "insufficient", skip_reason: "目前原來源尚未核實"};
  if (options.long) {const name = "LongSourceCampaignNameWithoutSpaces".repeat(6); source.source_campaigns[1].name = name; view.campaigns[1].name = name; view.rows[1].campaign_name = name;}
  const writes: string[] = [];
  await page.clock.setFixedTime(new Date("2026-09-23T02:00:00Z"));
  await page.route("**/auth/v1/**", route => route.fulfill({json: {access_token: "local-ui-fixture-token", refresh_token: "local-ui-fixture-refresh", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now()/1000)+3600, user}}));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), key = url.pathname;
    if (route.request().method() !== "GET") {
      writes.push(key);
      if (key.endsWith("/settle")) {
        if (failedSave) {failedSave = false; return route.fulfill({status: 503, json: {detail: "Fixture write failed"}});}
        view = settleEvidence("written"); return route.fulfill({json: view});
      }
      return route.fulfill({status: 503, json: {detail: "Fixture: unexpected write blocked"}});
    }
    if (key.endsWith("/next-period")) {
      if (failed) {failed = false; return route.fulfill({status: 502, json: {detail: "Fixture source unavailable"}});}
      expect(url.searchParams.get("month")).toBe(SETTLE_MONTH); return route.fulfill({json: source});
    }
    const bodies: Record<string, unknown> = {
      "/api/identity/me": {user, org, orgs: [org]},
      "/api/dashboard/overview": {data: [{brand_id: SETTLE_BRAND, brand_name: "既有活動接續證據品牌", health: "yellow", revenue_this_month: null, revenue_mom_pct: null, next_step: null}]},
      "/api/jobs/active": {data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, worker_alive: null, stalled: false, worker_health: {state: "unknown", checked_at: null, last_heartbeat_at: null, reason_code: "test_queue"}},
      [`/api/ads/brands/${SETTLE_BRAND}/rules`]: MONTH_RULES,
      [`/api/ads/brands/${SETTLE_BRAND}/settle`]: view,
      [`/api/ads/brands/${SETTLE_BRAND}/queue`]: {items: [], counts: {}, total_ads: 2, kinds_available: [], kinds_pending: [], settle: null},
      "/api/figures": {bases: {}}, "/api/interrupts": {data: [], total: 0},
    };
    return route.fulfill(key in bodies ? {json: bodies[key]} : {status: 503, json: {detail: "Fixture: optional read unavailable"}});
  });
  await page.goto("/app/login"); await page.getByLabel("Email").fill(user.email); await page.getByLabel("密碼").fill("local-ui-fixture-password");
  await page.getByRole("button", {name: "登入", exact: true}).click(); await page.waitForURL(url => !url.pathname.includes("/login"));
  await page.goto(`/app/brands/${SETTLE_BRAND}/ads/settle/${view.month}?step=${options.written ? "note" : "result"}`);
  return writes;
}
async function capture(page: Page, name: string) {
  const out = process.env.F54_I11_EVIDENCE_DIR;
  if (!out) return;
  await mkdir(out, {recursive: true}); await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({path: path.join(out, `${name}-${page.viewportSize()!.width}.png`), fullPage: true});
}

test("completed native sources survive keyboard selection, back and reload; navigation creates nothing", async ({page}) => {
  const writes = await setup(page);
  await expect(page.getByRole("heading", {name: "這期成績", exact: true})).toBeVisible();
  const bad = page.getByRole("region", {name: "舊平台活動・相對最好仍超標"});
  await expect(bad.getByText("記成無效", {exact: true})).toBeVisible(); await expect(bad.getByText("每筆 500 TWD", {exact: true})).toBeVisible();
  const fold = page.getByRole("button", {name: "從這期來源規劃下一期"});
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await fold.focus(); await page.keyboard.press("Enter"); await expect(fold).toBeFocused();
  const pick = page.getByRole("checkbox", {name: /舊平台活動/}); await pick.focus(); await page.keyboard.press("Space");
  await expect(pick).toBeChecked(); await expect(page.getByText(/可沿用參考 0 筆/)).toBeVisible();
  await expect(page.getByRole("link", {name: "用選定來源規劃下一期 →"})).toHaveAttribute("href", `/app/brands/${SETTLE_BRAND}/ads/new?source_month=2026-08&source_campaign=native&source_revision=source-revision-1`);
  await page.getByRole("link", {name: "下一步：確認主打什麼 →"}).click();
  await expect(page).toHaveURL(/step=angle.*source_campaign=native/);
  await page.getByRole("link", {name: "← 這期成績"}).click(); await page.reload();
  await page.getByRole("button", {name: "從這期來源規劃下一期"}).click(); await expect(pick).toBeChecked();
  await page.getByRole("button", {name: "查看來源資格與排除原因"}).click(); await expect(page.getByText(/成本超過上限，不能當作成功沿用/)).toBeVisible();
  await capture(page, "built-selected-source"); expect(writes).toEqual([]);
});
test("source failure retries independently without a draft or close operation", async ({page}) => {
  const writes = await setup(page, {failedSource: true}); await page.getByRole("button", {name: "從這期來源規劃下一期"}).click();
  await expect(page.getByText(/下一期來源讀不到/)).toBeVisible(); await expect(page.getByRole("region", {name: "這期數字"})).toBeVisible();
  await capture(page, "built-source-failed"); await page.getByRole("button", {name: "重試", exact: true}).click();
  await expect(page.getByRole("checkbox", {name: /日常推廣/})).toBeVisible(); expect(writes).toEqual([]);
});
test("written legacy unknown and currently unavailable rows stay visible", async ({page}) => {
  const writes = await setup(page, {written: true}); await expect(page.getByText("已寫 3 條：留存分類有效 1、無效 1、未核實 1")).toBeVisible();
  await expect(page.getByText("「通勤帶著走」・目前待核實")).toBeVisible(); await expect(page.getByText(/另有 1 條已寫紀錄/)).toBeVisible();
  await capture(page, "built-written"); expect(writes).toEqual([]);
});
test("not-ended and empty source keep explicit blocked states", async ({page}) => {
  const writes = await setup(page, {notEnded: true}); await expect(page.getByText("這個月還沒結束", {exact: true})).toBeVisible();
  await expect(page.getByRole("button", {name: "從這期來源規劃下一期"})).toHaveCount(0); await capture(page, "built-not-ended"); expect(writes).toEqual([]);
});
test("empty completed source cannot fallback to a generic draft", async ({page}) => {
  const writes = await setup(page, {empty: true}); await page.getByRole("button", {name: "從這期來源規劃下一期"}).click();
  await expect(page.getByText("這個完成期沒有可選的活動來源。")).toBeVisible(); await expect(page.getByRole("link", {name: "用選定來源規劃下一期 →"})).toHaveCount(0);
  await capture(page, "built-empty"); expect(writes).toEqual([]);
});
test("manual angle confirmation is the only write; failed save preserves selections for retry", async ({page}) => {
  const writes = await setup(page, {failedSave: true}); await page.getByRole("link", {name: "下一步：確認主打什麼 →"}).click();
  await page.getByRole("group", {name: "通勤喝咖啡主打什麼"}).getByRole("button", {name: "保溫到公司", exact: true}).click();
  await page.getByRole("link", {name: "都對，下一步 →"}).click(); await expect(page.getByText("「保溫到公司」・本期成本達標")).toBeVisible();
  const write = page.getByRole("button", {name: "寫進筆記本（2 條）→"}); await write.click(); await expect(page.getByText("還沒寫進筆記本", {exact: true})).toBeVisible();
  await expect(page.getByText("「保溫到公司」・本期成本達標")).toBeVisible(); await capture(page, "built-save-failed"); await write.click();
  await expect(page.getByText(/已寫 3 條/)).toBeVisible(); expect(writes).toEqual([`/api/ads/brands/${SETTLE_BRAND}/settle`, `/api/ads/brands/${SETTLE_BRAND}/settle`]);
});

const sourceWizard=`/app/brands/${SETTLE_BRAND}/ads/new?source_month=2026-08&source_campaign=native&source_revision=source-revision-1`;
async function recoverySetup(page: Page, options: {storageThrows?: boolean; historyThrows?: boolean; lostReply?: boolean; partial?: boolean; long?: boolean}={}) {
  if(options.storageThrows) await page.addInitScript(({historyThrows})=>{
    const set=Storage.prototype.setItem;
    Storage.prototype.setItem=function(key,value){if(this===window.sessionStorage)throw new Error("Fixture sessionStorage unavailable");return set.call(this,key,value);};
    if(historyThrows){const replace=history.replaceState.bind(history);history.replaceState=function(state,title,url){
      if(state?.usr?.campaignWizard)throw new Error("Fixture history receipt unavailable");return replace(state,title,url);
    };}
  },{historyThrows:options.historyThrows});
  const user={id:"wizard-ui-user",email:"wizard-ui@example.com",aud:"authenticated",role:"authenticated"};
  const org={id:"wizard-ui-org",name:"建檔恢復測試",kind:"personal",role:"owner",timezone:"Asia/Taipei",today:"2026-09-23"};
  const source=nextPeriodEvidence(), picks=wizardRecoveryOptions(),uploads=wizardRecoveryUploads();
  if(options.long){picks.products[0].name=picks.products[0].display_name="LongSelectedProductNameWithoutSpaces".repeat(6);source.source_campaigns[1].name="LongNativeSourceCampaignWithoutSpaces".repeat(6);}
  const state={sourceFailed:false,optionsFailed:false,revisionChanged:false,posts:[] as CampaignPicks[],patches:[] as unknown[],attachments:[] as string[],ids:new Set<string>(),campaign:wizardRecoveryCampaign()};
  let lost=options.lostReply,partial=options.partial;
  await page.clock.setFixedTime(new Date("2026-09-23T02:00:00Z"));
  await page.route("**/auth/v1/**",route=>route.fulfill({json:{access_token:"local-ui-fixture-token",refresh_token:"local-ui-fixture-refresh",token_type:"bearer",expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,user}}));
  await page.route("**/api/**",async route=>{
    const key=new URL(route.request().url()).pathname,method=route.request().method();
    const base=`/api/ads/brands/${SETTLE_BRAND}`;
    if(method==="POST"&&key===`${base}/campaigns`){
      const payload=route.request().postDataJSON() as CampaignPicks;state.posts.push(payload);
      const request=payload.continuation?.request_id;if(!request)return route.fulfill({status:422,json:{detail:"Fixture requires structured continuation"}});
      if(!state.ids.has(request)){state.ids.add(request);state.campaign=wizardRecoveryCampaign(payload);}
      else expect(payload).toEqual(state.posts[0]);
      if(lost){lost=false;return route.abort("failed");}return route.fulfill({json:{campaign:{...state.campaign,parsed:true}}});
    }
    if(method==="PATCH"&&key===`${base}/campaigns/cmp_recovered`){
      const patch=route.request().postDataJSON();state.patches.push(patch);
      state.campaign={...state.campaign,...patch};return route.fulfill({json:{campaign:state.campaign}});
    }
    if(method==="POST"&&key===`${base}/campaigns/cmp_recovered/placements`){
      const id=route.request().postDataJSON().upload_id;state.attachments.push(id);
      if(id==="u2"&&partial){partial=false;return route.fulfill({status:503,json:{detail:"Fixture partial attach failed"}});}
      return route.fulfill({json:{placement:{id:`placement-${id}`}}});
    }
    if(method==="POST"&&key===`${base}/campaigns/cmp_recovered/strategy`)return route.fulfill({json:{campaign:state.campaign}});
    if(method!=="GET")return route.fulfill({status:503,json:{detail:"Fixture unexpected write"}});
    if(key.endsWith("/next-period"))return route.fulfill(state.sourceFailed ? {status:503,json:{detail:"Fixture fresh source unavailable"}} : {json:{...source,revision:state.revisionChanged ? "source-late-revision" : source.revision}});
    if(key.endsWith("/new-campaign/options"))return route.fulfill(state.optionsFailed ? {status:503,json:{detail:"Fixture options unavailable"}} : {json:picks});
    const bodies:Record<string,unknown>={
      "/api/identity/me":{user,org,orgs:[org]},
      "/api/dashboard/overview":{data:[{brand_id:SETTLE_BRAND,brand_name:"既有活動接續證據品牌",health:"yellow",revenue_this_month:null,revenue_mom_pct:null,next_step:null}]},
      "/api/jobs/active":{data:[],total:0,other_count:0,done_today:0,failed_today:0,worker_alive:null,stalled:false,worker_health:{state:"unknown",checked_at:null,last_heartbeat_at:null,reason_code:"test_queue"}},
      [`${base}/rules`]:MONTH_RULES,[`${base}/settle`]:settleEvidence(),
      [`${base}/channels`]:{channels:[{key:"meta",label:"Meta",connected:true,state_text:"已接上"}]},
      [`${base}/campaigns/cmp_recovered`]:{campaign:state.campaign},
      [`${base}/campaigns`]:{campaigns:[]},[`${base}/user-assets`]:{assets:[],uploads,next_cursor:null,next_upload_cursor:null},
      [`${base}/user-assets/batches/batch-fixture`]:{batch:{id:"batch-fixture",uploads}},
      [`${base}/queue`]:{items:[],counts:{},total_ads:2,kinds_available:[],kinds_pending:[],settle:null},
      "/api/figures":{bases:{}},"/api/interrupts":{data:[],total:0},
    };
    return route.fulfill(key in bodies ? {json:bodies[key]} : {status:503,json:{detail:"Fixture optional read unavailable"}});
  });
  await page.goto("/app/login");await page.getByLabel("Email").fill(user.email);await page.getByLabel("密碼").fill("local-ui-fixture-password");
  await page.getByRole("button",{name:"登入",exact:true}).click();await page.waitForURL(url=>!url.pathname.includes("/login"));
  return state;
}
async function wizardPicks(page:Page){
  await page.getByRole("radio",{name:/單杯 1,580 TWD/}).click();await page.getByRole("radio",{name:/購買/}).click();
  await expect(page.getByLabel("開始",{exact:true})).toHaveValue("2026-09-01");
  await page.getByLabel("這個活動最多花",{exact:true}).fill("30000");
}
async function wizardCapture(page:Page,name:string){
  const out=process.env.F54_I12_EVIDENCE_DIR;if(!out)return;
  await mkdir(out,{recursive:true});await page.evaluate(()=>window.scrollTo(0,0));
  const interactive=page.viewportSize()!;
  await page.setViewportSize({...interactive,height:await page.evaluate(()=>document.documentElement.scrollHeight)});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,`${name}-${page.viewportSize()!.width}.png`),fullPage:true});
  const facts=await page.evaluate(()=>({path:location.pathname,viewport:{width:innerWidth,height:innerHeight},scrollY,
    documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,
    containers:[...document.querySelectorAll("main,[data-slot=flow-header],.surface")].filter(e=>e.getClientRects().length).map(e=>({
      label:e.getAttribute("aria-label")??e.querySelector("h2")?.textContent??e.getAttribute("data-slot")??e.tagName,
      width:Math.round(e.getBoundingClientRect().width),maxWidth:getComputedStyle(e).maxWidth})),
    folds:[...document.querySelectorAll("button[aria-expanded],details")].filter(e=>e.getClientRects().length).map(e=>({
      label:e.textContent?.trim().slice(0,90),open:e.getAttribute("aria-expanded")==="true"||e.hasAttribute("open")})),
    controls:[...document.querySelectorAll("main button,main a,main input")].filter(e=>e.getClientRects().length).map(e=>({
      role:e.tagName,label:e.getAttribute("aria-label")??e.textContent?.trim().slice(0,70),target:e.getAttribute("href"),disabled:e.hasAttribute("disabled")}))}));
  await writeFile(path.join(out,`facts-${name}-${page.viewportSize()!.width}.json`),JSON.stringify(facts,null,2));
  await page.setViewportSize(interactive);
}
test("imported source reaches a single draft and the selected planner context through explicit association",async({page})=>{
  const state=await recoverySetup(page);await page.goto(`/app/brands/${SETTLE_BRAND}/ads/settle/${SETTLE_MONTH}?step=result`);
  await page.getByRole("button",{name:"從這期來源規劃下一期"}).click();const source=page.getByRole("checkbox",{name:/舊平台活動/});
  await source.focus();await page.keyboard.press("Space");await page.getByRole("link",{name:"用選定來源規劃下一期 →"}).click();
  await wizardPicks(page);const association=page.getByRole("checkbox",{name:/我確認選定歷史活動/});await association.focus();await page.keyboard.press("Space");
  await expect(association).toBeChecked();await wizardCapture(page,"built-source-confirmed");
  await page.getByRole("button",{name:/下一步：系統理解/}).click();await expect(page.getByRole("heading",{name:"系統這樣理解"})).toBeVisible();
  expect(state.posts[0].continuation).toMatchObject({month:SETTLE_MONTH,campaign_ids:["native"],revision:"source-revision-1",product_mapping_confirmed:true});
  await page.getByRole("button",{name:"產生策略 →"}).click();await expect(page.getByText("選定的下一期來源・2026-08")).toBeVisible();
  await page.getByRole("button",{name:"下一期來源與限制"}).click();await expect(page.getByText("來源成本超過上限，不能當作成功沿用")).toBeVisible();
  expect(state.campaign.budget_basis_json?.basis?.planner_context?.continuation?.source_campaigns.map(c=>c.campaign_id)).toEqual(["native"]);
  expect(state.ids.size).toBe(1);await wizardCapture(page,"built-planner-selected-source");
});
test("sessionStorage throw and lost reply survive full reload, edits, failed fresh reads and partial attachment",async({page})=>{
  const state=await recoverySetup(page,{storageThrows:true,lostReply:true,partial:true});await page.goto(sourceWizard);await wizardPicks(page);
  await page.getByRole("button",{name:/進階：一句話建立/}).click();await page.getByRole("checkbox",{name:"選取 u1.png"}).check();await page.getByRole("checkbox",{name:"選取 u2.png"}).check();
  await page.getByRole("button",{name:/下一步：系統理解/}).click();await expect(page.getByRole("button",{name:"重試",exact:true})).toBeVisible();
  expect(state.ids.size).toBe(1);expect(state.posts).toHaveLength(1);await page.getByRole("button",{name:"← 上一步"}).click();
  await page.getByLabel("這個活動最多花",{exact:true}).fill("35000");
  await expect.poll(()=>page.evaluate(()=>history.state.usr?.campaignWizard && Object.values(history.state.usr.campaignWizard).some((v:any)=>v?.value?.budget===35000))).toBe(true);
  state.sourceFailed=true;state.optionsFailed=true;await page.reload();
  await expect(page.getByText(/賣法和目標清單讀不到/)).toBeVisible();await wizardCapture(page,"built-reload-pending-source-failed");
  await page.getByRole("button",{name:"確認上次送出結果"}).click();await expect(page.getByText(/已確認上次建立的活動/)).toBeVisible();
  expect(state.posts).toHaveLength(2);expect(state.posts[1]).toEqual(state.posts[0]);expect(state.ids.size).toBe(1);
  state.optionsFailed=false;state.sourceFailed=false;state.revisionChanged=true;
  await page.locator('[data-slot="read-failed"]').filter({hasText:"賣法和目標清單讀不到"}).getByRole("button",{name:"重試"}).click();
  await expect(page.getByRole("radio",{name:/單杯 1,580 TWD/})).toBeVisible();await expect(page.getByLabel("這個活動最多花",{exact:true})).toHaveValue("35000");
  await page.getByRole("button",{name:/重試加入未完成素材並繼續/}).click();await expect(page.getByText(/未完成素材仍可重試/)).toBeVisible();
  expect(state.attachments).toEqual(["u1","u2"]);expect(state.patches).toContainEqual(expect.objectContaining({constraints_json:{budget:35000,platform:"meta"}}));
  await wizardCapture(page,"built-partial-attachment");await page.reload();
  await expect(page.getByText(/修改與素材加入都會續接同一個活動/)).toBeVisible();
  await expect(page.getByText("已確認加入 1／2 檔；重試只處理未確認加入的素材。")).toBeVisible();
  await page.getByRole("button",{name:/進階：一句話建立/}).click();await expect(page.getByRole("checkbox",{name:"選取 u1.png"})).toBeChecked();await expect(page.getByRole("checkbox",{name:"選取 u2.png"})).toBeChecked();
  await expect(page.getByText(/來源月份、活動或版本已失效/)).toBeVisible();await page.getByRole("button",{name:/下一步：系統理解/}).click();
  await expect(page.getByRole("heading",{name:"系統這樣理解"})).toBeVisible();expect(state.attachments).toEqual(["u1","u2","u2"]);expect(state.ids.size).toBe(1);
  await page.getByRole("link",{name:"← 上一步",exact:true}).click();await page.reload();
  await expect(page.getByText(/修改與素材加入都會續接同一個活動/)).toBeVisible();expect(state.posts).toHaveLength(2);await wizardCapture(page,"built-known-created-back");
});
test("both durable stores unavailable block the first POST through a full reload",async({page})=>{
  const state=await recoverySetup(page,{storageThrows:true,historyThrows:true});await page.goto(sourceWizard);await wizardPicks(page);
  await page.getByRole("button",{name:/下一步：系統理解/}).click();await expect(page.getByText(/尚未送出/)).toBeVisible();
  await expect(page.getByLabel("這個活動最多花",{exact:true})).toHaveValue("30000");expect(state.posts).toEqual([]);await wizardCapture(page,"built-storage-blocked");
  await page.reload();await wizardPicks(page);await page.getByRole("button",{name:/下一步：系統理解/}).click();await expect(page.getByText(/尚未送出/)).toBeVisible();expect(state.posts).toEqual([]);
});
test("source retry, unknown and zero inputs, loading, and long names retain keyboard and layout",async({page})=>{
  const state=await recoverySetup(page,{long:true});await page.goto(sourceWizard);
  const product=page.getByRole("radio",{name:/LongSelectedProductName/});await product.focus();await page.keyboard.press("Space");
  await expect(product).toHaveAttribute("aria-checked","true");await page.getByRole("radio",{name:/購買/}).click();
  await expect(page.getByText(/花了 0（幣別未提供）/)).toBeVisible();await wizardCapture(page,"built-long-zero");
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('[role="radio"][data-value="prd_unknown"]').click();await page.getByLabel("這個活動最多花",{exact:true}).fill("0");
  await expect(page.getByRole("button",{name:/下一步：系統理解/})).toBeDisabled();await wizardCapture(page,"built-null-zero");
  await page.getByLabel("這個活動最多花",{exact:true}).fill("-12");await expect(page.getByRole("button",{name:/下一步：系統理解/})).toBeDisabled();
  state.sourceFailed=true;await page.reload();await expect(page.getByText(/Fixture fresh source unavailable/)).toBeVisible();
  await wizardCapture(page,"built-source-read-failed");state.sourceFailed=false;
  const retry=page.locator('[data-slot="read-failed"]').getByRole("button",{name:"重試"});await retry.focus();await page.keyboard.press("Enter");
  await expect(page.getByText(/LongNativeSourceCampaign/)).toBeVisible();await wizardCapture(page,"built-source-retry");
  let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route("**/next-period?*",async route=>{await gate;await route.fulfill({json:nextPeriodEvidence()});});
  await page.reload({waitUntil:"domcontentloaded"});await expect(page.getByText("核對完成期來源中…")).toBeVisible();
  await expect(page.getByRole("button",{name:/下一步：系統理解/})).toBeDisabled();await wizardCapture(page,"built-source-loading");release();
  await expect(page.getByText(/既有平台活動保持原狀/)).toBeVisible();expect(state.posts).toEqual([]);
});
