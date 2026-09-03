import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";
import { echarts } from "@/lib/echarts";

/** 掛一顆 ECharts 圖到 DOM。殼是流體的，寬到 1920px、堪用到 1024px（ADR 0051），
 * 但這裡仍不掛 resize 監聽——掛載當下量到的容器大小就是圖表大小，視窗掛載後再變寬
 * 不會讓圖表跟著重畫。這個限制本身不在本票範圍內（本票只改殼寬，不改圖表元件）。 */
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
