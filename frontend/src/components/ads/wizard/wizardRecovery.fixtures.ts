import type {CampaignPicks, WizardOptions} from "@/lib/adsWizardApi";
import type {AssetUpload} from "@/lib/adsUserAssetsApi";
import {strategyFixture} from "../strategy/strategyEvidence.fixtures";
import {nextPeriodEvidence} from "../settle/settleEvidence.fixtures";

/** Synthetic wire receipts for browser recovery proofs; never a live planner or platform receipt. */
export function wizardRecoveryOptions(): WizardOptions {
  return {products: [{id:"prd_fixture",name:"晨光隨行杯 · 單杯",display_name:"單杯",kind:"single",
    knowledge_product_id:"kp-cup",knowledge_product_name:"晨光隨行杯",price:1580,currency:"TWD",thumbnail_url:null,
    has_cost:true,break_even:520,cap_per_sale:450,derived_fields:[],offer_labels:[],
    customer_groups:[{id:"pcg_run",who:"通勤族"}],landing_url:null,learned:null,
    previous:{campaign_id:"unselected-old",campaign_name:"晨光隨行杯・07/01～07/31",platform:"meta",cap:450,budget:30000,spend:0}},
    {id:"prd_unknown",name:"新色隨行杯 · 單杯",display_name:"單杯",kind:"single",knowledge_product_id:"kp-new",
      knowledge_product_name:"新色隨行杯",price:null,currency:null,thumbnail_url:null,has_cost:false,break_even:null,
      cap_per_sale:null,derived_fields:[],offer_labels:[],customer_groups:[],landing_url:null,learned:null,previous:null}],
    objectives:[{key:"購買",label:"購買",description:"看每賣一筆花多少",available:true,platforms:{meta:"銷售業績"}},
      {key:"名單",label:"名單",description:"看每筆名單成本",available:true,platforms:{meta:"潛在顧客"}}],
    default_objective:null,default_platform:"meta"};
}
export function wizardRecoveryUploads(): AssetUpload[] {
  return ["u1","u2"].map(id=>({id,batch_id:"batch-fixture",filename:`${id}.png`,expected_size:10,status:"complete",error:null,
    asset_id:`asset-${id}`,copy_fields:{headline:`${id} 原文`}}));
}
export function wizardRecoveryCampaign(payload?: CampaignPicks) {
  const campaign=strategyFixture();
  campaign.id="cmp_recovered"; campaign.name="晨光隨行杯・下一期測試";campaign.objective=payload?.objective ?? "購買";
  campaign.start_date=payload?.start_date ?? "2026-09-01";campaign.end_date=payload?.end_date ?? "2026-10-01";
  campaign.constraints_json={budget:payload?.budget ?? 30000,platform:"meta"};campaign.cap.own_value=450;campaign.cap.value=450;
  const source=nextPeriodEvidence();source.source_campaigns=source.source_campaigns.filter(c=>c.campaign_id==="native");source.eligible_learning_refs=[];
  campaign.context_json={product_ids:payload?.product_ids ?? ["prd_fixture"],customer_group_ids:["pcg_run"],
    field_sources:{dates:"user",product:"user",objective:"user",budget:"user",platform:"brand",audience:"sell_way",cap:"copied"},
    next_period_source:{...source,product_id:"prd_fixture",product_mapping_confirmed:payload?.continuation?.product_mapping_confirmed ?? false,
      payload_digest:"fixture-payload-digest",native_entities:[{id:"ad_native",campaign_id:"native",platform:"meta",source_account:"fixture-account",native_kind:"ad",native_id:"fixture-native-ad"}],
      campaign_ids:["native"],request_id:payload?.continuation?.request_id ?? "b7ac6be2-fda5-4f58-9dd4-43b33b9d8dc6"}};
  const basis=campaign.budget_basis_json!.basis!;
  basis.planner_context={product_id:"prd_fixture",forbidden_count:0,offers:[],previous_campaign_id:null,continuation:source};
  basis.learnings=[];basis.evidence_context={schema_version:1,revision:"selected-source-evidence",scope_product_id:"prd_fixture",
    scope_label:"晨光隨行杯 · 單杯",eligible_count:0,items:[],omitted:0};
  const strategy=campaign.budget_basis_json!.strategy!;
  const decision=strategy.decision!;decision.facts!.continuation=source;
  decision.slots=[{...decision.slots[1],customer_group_id:"pcg_run",test_intent:"通勤飲水的新測試",evidence_refs:[],
    display:{customer_group_label:"通勤族",offer_label:"不使用優惠",carried_ad_label:null,evidence:[],evidence_omitted:0}}];
  decision.facts!.available={customer_groups:1,customer_group_names:["通勤族"]};
  decision.facts!.proposed={customer_groups:1,delivery_groups:1,ads:1,customer_group_names:["通勤族"],unknown_audience_ads:0};
  strategy.allocation=[{role:"explore",label:"探索",pct:100,amount:payload?.budget ?? 30000,rationale:"選定來源超過上限，這次只提出新測試。"}];
  return campaign;
}
