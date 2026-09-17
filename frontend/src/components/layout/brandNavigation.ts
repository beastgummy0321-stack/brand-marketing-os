/** Resource IDs and filters never survive a change of brand. */
export function brandDestination(id: string, pathname: string, search: string): string {
  const section = pathname.match(/^\/brands\/[^/]+\/([^/]+)/)?.[1];
  const allowed = ["ads", "workbench", "orders", "products", "library", "report"];
  const suffix = section && allowed.includes(section) ? `/${section}` : "";
  const tab = new URLSearchParams(search).get("tab");
  const query = section === "library" && tab ? `?tab=${encodeURIComponent(tab)}` : "";
  return `/brands/${encodeURIComponent(id)}${suffix}${query}`;
}
