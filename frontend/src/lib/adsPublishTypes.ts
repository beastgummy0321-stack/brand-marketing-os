export type AdapterKey = "manual" | "auto_meta" | "simulated";

export interface AdapterOption {
  key: AdapterKey;
  label: string;
}

/** 逐節點清單的一列——campaign 節點打頭，然後每個投放組，再來是它底下每支廣告。 */
export interface PublishChecklistField {
  label: string;
  value: string | number;
  reason: string;
}

export interface PublishChecklistNode {
  level: "campaign" | "group" | "ad";
  id: string;
  name: string;
  fields: PublishChecklistField[];
}

/** `describe`：`message` 非 `null` 時（例如 `auto_meta` 的「自動發布未接上」）沒有清單可看。 */
export interface PublishDescribe {
  adapter: AdapterKey;
  message: string | null;
  checklist: PublishChecklistNode[];
  content_hash?: string;
}

export interface PublishGetResponse {
  adapters: AdapterOption[];
  adapter: AdapterKey;
  describe: PublishDescribe;
}

