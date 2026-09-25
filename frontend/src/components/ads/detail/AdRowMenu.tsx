import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cancelMaterialTask, createReplaceRequest, listMaterialTasks, type MaterialTask } from "@/lib/adsMaterialApi";
import { readErrorMessage, useApiRead, type ApiRead } from "@/lib/useApiRead";
import { RowMenu } from "../patterns";

/** F29-I13: an ad row's 「⋯」 menu (prototype v10 `tabPerf()` `menu()`): 換掉這一則／取消換掉這一則 and 看紀錄.
 * 換掉這一則 opens a material request bound to the ad (Contract H, `createReplaceRequest`; the server returns the open
 * one when it already exists); a request is found again through the campaign's material list (`replaces.entity_id`,
 * cancelled tasks are not listed). Nothing here touches the platform. */

export interface ReplaceRequests {
  /** The campaign's material list read; while it is not `ready` no row can say whether a request is open. */
  read: ApiRead<{ tasks: MaterialTask[] }>;
  /** The open request replacing this ad; `null` = none; `undefined` = unknown (the list is not read). */
  requestOf: (entityId: string) => MaterialTask | null | undefined;
  busy: (entityId: string) => boolean;
  /** The last create/cancel failure for this ad (cleared by the next attempt). */
  errorOf: (entityId: string) => string | null;
  replace: (entityId: string) => Promise<void>;
  cancel: (entityId: string) => Promise<void>;
}

export function useReplaceRequests(brandId: string, campaignId: string): ReplaceRequests {
  const read = useApiRead((signal) => listMaterialTasks(brandId, campaignId, signal), [brandId, campaignId]);
  // What this visit changed on top of the list: an entity's request just opened (task) or withdrawn (null).
  const [changed, setChanged] = useState<Record<string, MaterialTask | null>>({});
  const [pending, setPending] = useState<Set<string>>(() => new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});

  const requestOf = useCallback((entityId: string) => {
    if (entityId in changed) return changed[entityId];
    if (read.status !== "ready") return undefined;
    return read.data.tasks.find((t) => t.replaces?.entity_id === entityId && t.cancelled_at === null) ?? null;
  }, [changed, read]);

  const run = useCallback(async (entityId: string, failure: string, work: () => Promise<MaterialTask | null>) => {
    setPending((prev) => new Set(prev).add(entityId));
    setErrors((prev) => { const next = { ...prev }; delete next[entityId]; return next; });
    try {
      const result = await work();
      setChanged((prev) => ({ ...prev, [entityId]: result }));
    } catch (err) {
      setErrors((prev) => ({ ...prev, [entityId]: `${failure}：${readErrorMessage(err)}` }));
    } finally {
      setPending((prev) => { const next = new Set(prev); next.delete(entityId); return next; });
    }
  }, []);

  const replace = useCallback((entityId: string) => run(entityId, "換掉這一則沒送出", async () => {
    const { task } = await createReplaceRequest(brandId, campaignId, entityId);
    return task;
  }), [brandId, campaignId, run]);

  const cancel = useCallback((entityId: string) => {
    const task = requestOf(entityId);
    if (!task) return Promise.resolve();
    return run(entityId, "取消換掉這一則沒成功", async () => {
      await cancelMaterialTask(brandId, campaignId, task.id);
      return null;
    });
  }, [brandId, campaignId, requestOf, run]);

  return {
    read, requestOf, replace, cancel,
    busy: (entityId) => pending.has(entityId),
    errorOf: (entityId) => errors[entityId] ?? null,
  };
}

export function AdRowMenu({ name, entityId, recordHref, requests }: {
  name: string; entityId: string; recordHref: string; requests: ReplaceRequests;
}) {
  const navigate = useNavigate();
  const request = requests.requestOf(entityId);
  const busy = requests.busy(entityId);
  return (
    <RowMenu
      label={`更多：${name}`}
      items={[
        request
          ? { label: "取消換掉這一則", onSelect: () => void requests.cancel(entityId), disabled: busy }
          : { label: "換掉這一則", onSelect: () => void requests.replace(entityId), disabled: busy },
        { label: "看紀錄", onSelect: () => navigate(recordHref) },
      ]}
    />
  );
}
