/** T2a 調研報告回顯 API。兩支讀取端點都拆既有 {data, generated_at} 信封。 */

export interface ResearchReportSummary {
  id: string;
  created_at: string;
  confirmed_count: number;
}

export interface ResearchReportSection {
  title: string;
  raw_text: string;
}

export interface ResearchReport extends ResearchReportSummary {
  paste_raw: string;
  leading_text: string;
  sections: ResearchReportSection[];
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這份調研報告。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

const base = (brandId: string) =>
  `/api/intake/brands/${encodeURIComponent(brandId)}/research-reports`;

export const fetchResearchReports = (brandId: string): Promise<ResearchReportSummary[]> => getJson(base(brandId));

export const fetchResearchReport = (brandId: string, draftId: string): Promise<ResearchReport> =>
  getJson(`${base(brandId)}/${encodeURIComponent(draftId)}`);
