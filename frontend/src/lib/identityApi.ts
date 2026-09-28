import { apiFetch, errorMessageFrom } from "./http";
import { setOrgId } from "./auth";
export interface OrgOut {
  id: string;
  name: string;
  kind: string;
  role: string;
  /** F36-I08 (Contract U): IANA name of the org's timezone, from `settings.org_timezone`.
   * Read it through `useOrgClock()` in `@/lib/orgClock`, not directly. */
  timezone: string;
  /** F36-I08 (Contract U): YYYY-MM-DD in `timezone` at response time. Boot value only; the
   * hook recomputes from the timezone so a long-open tab does not freeze on the load date. */
  today: string;
}
export interface Identity {
  user: { id: string; email: string };
  org: OrgOut;
  orgs: OrgOut[];
}
export async function fetchIdentity(): Promise<Identity> {
  const res = await apiFetch("/api/identity/me");
  const body = await res.json();
  if (!res.ok)
    throw new Error(errorMessageFrom(body, "無法讀取工作區，請重新載入。"));
  const identity = body as Identity;
  // HTTP may recover from forbidden_org. Only server-resolved identity can scope preferences.
  setOrgId(identity.org.id);
  return identity;
}
