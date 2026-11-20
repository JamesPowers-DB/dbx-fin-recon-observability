// Days to close by period: FY2025 traditional close, the move to continuous
// monitoring in 2026, and the active close's projection. Target and north-star
// reference lines. Hand-drawn SVG; d3 for scales only.
import React, { useState } from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import type { CloseTrendPoint } from "../types";

export function DaysToCloseChart({ points, target = 3, northStar = 1, traditional, width = 860, height = 230 }: {
  points: CloseTrendPoint[]; target?: number; northStar?: number; traditional?: number | null; width?: number; height?: number;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const m = { top: 18, right: 120, bottom: 30, left: 36 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const max = Math.max(10, ...points.map((p) => p.days_to_close ?? 0));
  const x = scaleBand<string>().domain(points.map((p) => p.period)).range([0, iw]).padding(0.25);
  const y = scaleLinear().domain([0, max]).range([ih, 0]);
  const ref = (v: number, label: string, color: string, dash?: string) => (
    <g>
      <line x1={0} x2={iw} y1={y(v)} y2={y(v)} stroke={color} strokeDasharray={dash} strokeWidth={1.2} />
      <text x={iw + 6} y={y(v)} dy="0.32em" fontFamily="var(--font-mono)" fontSize={10} fill={color}>{label}</text>
    </g>
  );
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Days to close by period">
      <g transform={`translate(${m.left},${m.top})`}>
        {[0, 2, 4, 6, 8, 10].filter((v) => v <= max).map((v) => (
          <g key={v}>
            <line x1={0} x2={iw} y1={y(v)} y2={y(v)} stroke="var(--border)" />
            <text x={-6} y={y(v)} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">T+{v}</text>
          </g>
        ))}
        {traditional != null && ref(traditional, `FY2025 avg T+${traditional.toFixed(1)}`, "var(--db-navy-400)", "2 4")}
        {ref(target, `Target T+${target}`, "var(--db-navy-700)", "4 3")}
        {ref(northStar, `North star T+${northStar}`, "var(--db-green-700)", "4 3")}
        {points.map((p) => {
          const v = p.days_to_close ?? 0;
          const active = p.period_status === "ACTIVE";
          const fy25 = p.period.startsWith("2025");
          const bx = x(p.period) ?? 0;
          const fill = active ? "none" : fy25 ? "var(--db-navy-300)" : "var(--db-navy-700)";
          return (
            <g key={p.period} onMouseEnter={() => setHover(p.period)} onMouseLeave={() => setHover(null)}>
              <rect x={bx} y={y(v)} width={x.bandwidth()} height={Math.max(1, ih - y(v))} rx={3} fill={fill}
                    stroke={active ? "var(--db-lava-600)" : "none"} strokeWidth={active ? 2 : 0} strokeDasharray={active ? "4 3" : undefined}
                    opacity={hover && hover !== p.period ? 0.55 : 1} />
              {(hover === p.period || active || p.period.endsWith("-01") || p.period.endsWith("-07")) && (
                <text x={bx + x.bandwidth() / 2} y={y(v) - 5} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10}
                      fill={active ? "var(--db-lava-700)" : "var(--fg-1)"}>{active ? `T+${v} proj.` : `T+${v}`}</text>
              )}
              {(p.period.endsWith("-01") || p.period.endsWith("-07") || active) && (
                <text x={bx + x.bandwidth() / 2} y={ih + 16} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">
                  {p.period}
                </text>
              )}
            </g>
          );
        })}
        <line x1={0} x2={iw} y1={ih} y2={ih} stroke="var(--border-strong)" />
      </g>
    </svg>
  );
}
