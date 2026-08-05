import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";
import { echarts } from "@/lib/echarts";

/** 掛一顆 ECharts 圖到 DOM。純桌機 1440px 固定版面（決策 0038／ADR 0003）不做
 * 響應式，所以不掛 resize 監聽——圖表容器大小不會變。 */
export function useEchart(option: EChartsOption) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chartRef.current = echarts.init(ref.current);
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return ref;
}
