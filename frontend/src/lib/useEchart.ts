import { useEffect, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { echarts } from "@/lib/echarts";

/** Attach when a populated chart becomes visible; resize with its container and sidebar. */
export function useEchart(option: EChartsOption) {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  useEffect(() => {
    if (!node) return;
    const chart = echarts.init(node);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(node);
    return () => { observer.disconnect(); chart.dispose(); chartRef.current = null; };
  }, [node]);
  useEffect(() => { chartRef.current?.setOption(option, true); }, [option, node]);
  return setNode;
}
