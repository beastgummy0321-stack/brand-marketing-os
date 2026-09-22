import { ManualHandoffPanel } from "../ManualHandoffPanel";

/** F27-I15 Screens「Flow pages, new-ad and multi-item」: 「handoff = the existing
 * ManualHandoffPanel steps for that item」— reuses the existing new-ad handoff/binding UI
 * (`ManualHandoffPanel.tsx`'s `mode="items"`, candidate selection + report/check against
 * `ads_handoff_item`, contract note: a `new_ad` change item's own readback goes through THAT
 * mechanism, never the generic `actOnChangeItem` report/check `HandoffPage.tsx` uses for
 * pause/copy/budget — `app/ads/handoff_check.py::_finish` is what folds the result back into the
 * change item's own `verification_state`). `mode="items"` skips the panel's own "新增另一則廣告"
 * form (`NewAdForm`), which would duplicate the very change set this page is already showing. */
export function NewAdHandoffPanel({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  return <ManualHandoffPanel brandId={brandId} campaignId={campaignId} mode="items" />;
}
