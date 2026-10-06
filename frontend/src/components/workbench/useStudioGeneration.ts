import { useEffect, useRef, useState } from "react";
import { runProduct, type ProductPart, type SetDetail } from "@/lib/workbenchApi";
import { PART_LABEL } from "./regenerateLabel";

/** Mounted inside the brand/pack/set-keyed studio. Pending requests survive part navigation,
 * while an old studio's completion can update only that old studio. The server exposes no job
 * part, so named running labels refer only to an operation started by this studio. */
export function useStudioGeneration({
  brandId,
  setId,
  serverGenerating,
  onUpdated,
}: {
  brandId: string;
  setId: string;
  serverGenerating: boolean;
  onUpdated: (set: SetDetail) => void;
}) {
  const [startedPart, setStartedPart] = useState<ProductPart | null>(null);
  const [pendingPart, setPendingPart] = useState<ProductPart | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const requestPending = useRef(false);
  const generating = pendingPart !== null || serverGenerating;

  useEffect(() => {
    if (!generating) setStartedPart(null);
  }, [generating]);

  async function handleRun(part: ProductPart, count?: number) {
    if (requestPending.current) return;
    requestPending.current = true;
    setPendingPart(part);
    setStartedPart(part);
    setRunError(null);
    try {
      onUpdated(await runProduct(brandId, setId, part, count));
    } catch (err) {
      setStartedPart(null);
      setRunError(`${PART_LABEL[part]}：${err instanceof Error ? err.message : "請稍後再試。"}`);
    } finally {
      requestPending.current = false;
      setPendingPart(null);
    }
  }

  return { startedPart, pendingPart, runError, generating, handleRun };
}
