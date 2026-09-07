export const METRICS = [
  "spend",
  "impressions",
  "clicks",
  "ctr",
  "roas",
] as const;
export type MetricId = (typeof METRICS)[number];
export const WIDGETS = [
  "spend",
  "performance",
  "campaigns",
  "inbox",
  "commerce",
] as const;
export type WidgetId = (typeof WIDGETS)[number];
export const WIDTHS = ["narrow", "half", "wide", "full"] as const;
export type WidgetWidth = (typeof WIDTHS)[number];
export interface DashboardView {
  id: string;
  name: string;
  metrics: MetricId[];
  widgets: { id: WidgetId; width: WidgetWidth }[];
}
export interface DashboardLayout {
  version: 1;
  activeId: string;
  views: DashboardView[];
}
export function defaultLayout(): DashboardLayout {
  return {
    version: 1,
    activeId: "ads",
    views: [
      {
        id: "ads",
        name: "廣告成效",
        metrics: [...METRICS],
        widgets: [
          { id: "spend", width: "half" },
          { id: "performance", width: "half" },
          { id: "campaigns", width: "wide" },
          { id: "inbox", width: "narrow" },
        ],
      },
    ],
  };
}
export function layoutKey(userId: string, orgId: string, brandId: string) {
  return `brand-os:dashboard:${JSON.stringify([userId, orgId, brandId])}`;
}
/** Local preferences are untrusted/versioned; stale widget IDs must never break the page. */
export function parseLayout(raw: string | null): DashboardLayout {
  try {
    const data: unknown = JSON.parse(raw ?? "null");
    if (
      !data ||
      typeof data !== "object" ||
      !("version" in data) ||
      data.version !== 1 ||
      !("views" in data) ||
      !Array.isArray(data.views)
    )
      return defaultLayout();
    const views: DashboardView[] = [];
    for (const item of data.views.slice(0, 8)) {
      if (
        !item ||
        typeof item.id !== "string" ||
        typeof item.name !== "string" ||
        !item.name.trim() ||
        views.some((v) => v.id === item.id)
      )
        continue;
      const metrics = METRICS.filter(
        (id) => Array.isArray(item.metrics) && item.metrics.includes(id),
      );
      const widgets: DashboardView["widgets"] = [];
      for (const widget of Array.isArray(item.widgets) ? item.widgets : []) {
        if (
          widget &&
          WIDGETS.includes(widget.id) &&
          WIDTHS.includes(widget.width) &&
          !widgets.some((w) => w.id === widget.id)
        )
          widgets.push({ id: widget.id, width: widget.width });
      }
      if (metrics.length || widgets.length)
        views.push({
          id: item.id,
          name: item.name.trim().slice(0, 24),
          metrics,
          widgets,
        });
    }
    if (!views.length) return defaultLayout();
    const activeId =
      "activeId" in data &&
      typeof data.activeId === "string" &&
      views.some((v) => v.id === data.activeId)
        ? data.activeId
        : views[0].id;
    return { version: 1, activeId, views };
  } catch {
    return defaultLayout();
  }
}
export function reorderWidgets(
  view: DashboardView,
  from: WidgetId,
  to: WidgetId,
): DashboardView {
  const widgets = [...view.widgets];
  const start = widgets.findIndex((w) => w.id === from);
  const end = widgets.findIndex((w) => w.id === to);
  if (start < 0 || end < 0 || start === end) return view;
  widgets.splice(end, 0, widgets.splice(start, 1)[0]);
  return { ...view, widgets };
}
