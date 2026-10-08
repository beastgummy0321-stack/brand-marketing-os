import {useCallback, useEffect, useRef, useState} from "react";
import {getWizardOptions, type WizardProduct} from "@/lib/adsWizardApi";
import {getCoordinateLearnings, type CoordinateLearnings} from "@/lib/adsLearningsApi";

/** The selection belongs to the user; refreshed history never chooses another product. */
export function useLearningScope(brandId: string, initial: CoordinateLearnings | null) {
  const [products, setProducts] = useState<WizardProduct[] | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [optionsBusy, setOptionsBusy] = useState(true);
  const [selection, setSelection] = useState("");
  const [round, setRound] = useState(0);
  const initialized = useRef(false);
  const lastGood = useRef<{id: string; data: CoordinateLearnings} | null>(null);
  const [read, setRead] = useState<{id: string; data: CoordinateLearnings | null; busy: boolean; error: string | null}>({id: "", data: null, busy: false, error: null});
  useEffect(() => {
    let active = true;
    setOptionsBusy(true);
    setOptionsError(null);
    getWizardOptions(brandId).then(data => {
      if (active) { setProducts(data.products); setOptionsBusy(false); }
    }).catch((error: unknown) => {
      if (active) { setOptionsError(error instanceof Error ? error.message : "商品讀取失敗。"); setOptionsBusy(false); }
    });
    return () => { active = false; };
  }, [brandId, round]);
  useEffect(() => {
    if (initialized.current || products === null || initial === null) return;
    initialized.current = true;
    const id = initial.next?.sell_way_id;
    if (id && products.some(product => product.id === id)) setSelection(id);
  }, [initial, products]);
  const product = products?.find(row => row.id === selection) ?? null;
  const productId = product?.id ?? null;
  useEffect(() => {
    if (!productId || optionsError) return;
    const ctrl = new AbortController();
    const id = productId;
    const retained = lastGood.current?.id === id ? lastGood.current.data : null;
    setRead({id, data: retained, busy: true, error: null});
    getCoordinateLearnings(brandId, {sellWayId: id}, ctrl.signal).then(data => {
      if (ctrl.signal.aborted) return;
      if (data.evidence_context?.scope_product_id !== id) {
        setRead({id, data: retained, busy: false, error: "商品範圍尚未核實，請重新讀取。"});
        return;
      }
      lastGood.current = {id, data};
      setRead({id, data, busy: false, error: null});
    }).catch((error: unknown) => {
      if (ctrl.signal.aborted) return;
      setRead({id, data: retained, busy: false, error: error instanceof Error ? error.message : "歷史讀取失敗。"});
    });
    return () => ctrl.abort();
  }, [brandId, productId, optionsError, round]);
  const current = product && read.id === product.id ? read : {id: selection, data: null, busy: Boolean(product), error: null};
  const reload = useCallback(() => setRound(value => value + 1), []);
  return {products, product, selection, setSelection, optionsError, ...current, busy: current.busy || optionsBusy, reload};
}
