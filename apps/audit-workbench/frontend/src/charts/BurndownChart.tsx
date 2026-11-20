// Close burndown: close tasks remaining by close day (T-n .. T+n).
// Plan (calendar due days), traditional close (FY2025 average completion),
// actual (completions from control runs and sign-offs, up to today) and the
// projection from today. Ahead/behind shading between plan and actual, a
// pre-close region before month end, and target / north-star markers.
// Hand-drawn SVG; d3 for scales and paths only.
import React, { useMemo, useState } from "react";
import { scaleLinear } from "d3-scale";
import { line, area, curveStepAfter } from "d3-shape";
import type { BurndownPoint } from "../types";

export interface BurndownProps {
  points: BurndownPoint[];
  total: number;
  todayT: number | null;
  targetT: number;
  northStarT?: number;
  projectedT: number | null;
  width?: number;
  height?: number;
}

const tLabel = (t: number) => (t === 0 ? "T" : t > 0 ? `T+${t}` : `T${t}`);

export function BurndownChart({ points, total, todayT, targetT, northStarT = 1, projectedT, width = 860, height = 340 }: BurndownProps) {
  const [hover, setHover] = useState<BurndownPoint | null>(null);
  const m = { top: 26, right: 24, bottom: 86, left: 44 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const tMin = points[0]?.t ?? -10;
  const tMax = points[points.length - 1]?.t ?? 9;
  const x = scaleLinear().domain([tMin, tMax]).range([0, iw]);
  const y = scaleLinear().domain([0, Math.max(total, 1)]).range([ih, 0]).nice();
  const barsH = 44;

  const actualPts = points.filter((p) => p.actual != null);
  const projPts = points.filter((p) => p.projected != null);
  const step = line<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t));
  const plannedPath = step.y((p) => y(p.planned))(points) ?? "";
  const tradPath = line<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t)).y((p) => y(p.traditional))(points) ?? "";
  const actualPath = line<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t)).y((p) => y(p.actual as number))(actualPts) ?? "";
  const projPath = line<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t)).y((p) => y(p.projected as number))(projPts) ?? "";

  // Ahead (below plan) / behind (above plan) bands: actual up to today, then the projection.
  const bands = useMemo(() => {
    const pts = points.filter((p) => p.actual != null || p.projected != null);
    const v = (p: BurndownPoint) => (p.actual ?? p.projected) as number;
    const ahead = area<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t))
      .y0((p) => y(p.planned)).y1((p) => y(Math.min(p.planned, v(p))));
    const behind = area<BurndownPoint>().curve(curveStepAfter).x((p) => x(p.t))
      .y0((p) => y(p.planned)).y1((p) => y(Math.max(p.planned, v(p))));
    return { ahead: ahead(pts) ?? "", behind: behind(pts) ?? "" };
  }, [points, x, y]);

  // Burn rate: tasks completed per close day (actual where known, else projected).
  const burn = points.map((p, i) => {
    if (i === 0) return { t: p.t, n: 0, kind: "actual" as const };
    const prev = points[i - 1];
    const cur = p.actual ?? p.projected;
    const before = prev.actual ?? prev.projected;
    const n = cur != null && before != null ? Math.max(0, before - cur) : 0;
    return { t: p.t, n, kind: p.actual != null && prev.actual != null ? ("actual" as const) : ("projected" as const) };
  });
  const maxBurn = Math.max(1, ...burn.map((b) => b.n));
  const bw = Math.max(4, iw / points.length - 6);

  const yTicks = y.ticks(Math.min(6, total));
  const showTicks = points.filter((p) => p.t % 2 === 0 || p.t === tMax);

  return (
    <div style={{ position: "relative" }}>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Close burndown: tasks remaining by close day">
        <g transform={`translate(${m.left},${m.top})`}>
          {/* pre-close region */}
          <rect x={0} y={0} width={Math.max(0, x(0) - x(tMin))} height={ih} fill="var(--db-oat-medium)" opacity={0.55} />
          <text x={6} y={ih - 8} fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)" letterSpacing="0.06em">PRE-CLOSE (BEFORE MONTH END)</text>
          {/* grid */}
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={0} x2={iw} y1={y(v)} y2={y(v)} stroke="var(--border)" />
              <text x={-8} y={y(v)} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">{v}</text>
            </g>
          ))}
          <text transform={`translate(-32,${ih / 2}) rotate(-90)`} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">TASKS REMAINING</text>

          {/* month end, target, north star */}
          <Marker x={x(0)} h={ih} label="Month end" color="var(--fg-2)" />
          <Marker x={x(northStarT)} h={ih} label={`North star ${tLabel(northStarT)}`} color="var(--db-green-700)" dashed top={28} />
          <Marker x={x(targetT)} h={ih} label={`Target ${tLabel(targetT)}`} color="var(--db-navy-700)" dashed top={14} />

          {/* ahead / behind */}
          <path d={bands.ahead} fill="var(--success)" opacity={0.16} />
          <path d={bands.behind} fill="var(--danger)" opacity={0.16} />

          {/* traditional, plan, actual, projected */}
          <path d={tradPath} fill="none" stroke="var(--db-navy-300)" strokeWidth={2} strokeDasharray="2 4" />
          <path d={plannedPath} fill="none" stroke="var(--db-navy-700)" strokeWidth={2} />
          <path d={projPath} fill="none" stroke="var(--db-lava-600)" strokeWidth={2.5} strokeDasharray="6 4" />
          <path d={actualPath} fill="none" stroke="var(--db-lava-600)" strokeWidth={3.5} />

          {/* today */}
          {todayT != null && todayT >= tMin && todayT <= tMax && (
            <g>
              <line x1={x(todayT)} x2={x(todayT)} y1={-4} y2={ih} stroke="var(--fg-2)" strokeWidth={1} strokeDasharray="1 3" />
              <rect x={x(todayT) - 34} y={-22} width={68} height={16} rx={8} fill="var(--db-lava-600)" />
              <text x={x(todayT)} y={-11} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-on-dark)">
                TODAY {tLabel(todayT)}
              </text>
              {actualPts.length > 0 && (
                <circle cx={x(todayT)} cy={y(actualPts[actualPts.length - 1].actual as number)} r={5} fill="var(--db-lava-600)" stroke="var(--bg-canvas)" strokeWidth={2} />
              )}
            </g>
          )}
          {projectedT != null && (
            <circle cx={x(Math.min(tMax, projectedT))} cy={y(0)} r={5} fill="var(--bg-canvas)" stroke="var(--db-lava-600)" strokeWidth={2.5} />
          )}

          {/* x axis */}
          <line x1={0} x2={iw} y1={ih} y2={ih} stroke="var(--border-strong)" />
          {showTicks.map((p) => (
            <text key={p.t} x={x(p.t)} y={ih + 14} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10}
                  fill={p.t === 0 ? "var(--fg-1)" : "var(--fg-3)"}>{tLabel(p.t)}</text>
          ))}

          {/* burn-rate bars */}
          <g transform={`translate(0,${ih + 26})`}>
            <text x={-8} y={10} textAnchor="end" fontFamily="var(--font-mono)" fontSize={9} fill="var(--fg-3)">BURN</text>
            {burn.map((b) => b.n > 0 && (
              <rect key={b.t} x={x(b.t) - bw / 2} y={barsH - (b.n / maxBurn) * barsH} width={bw} height={(b.n / maxBurn) * barsH} rx={2}
                    fill={b.kind === "actual" ? "var(--db-lava-600)" : "var(--db-lava-300)"} opacity={b.kind === "actual" ? 1 : 0.7} />
            ))}
            {burn.map((b) => b.n > 0 && (
              <text key={`l${b.t}`} x={x(b.t)} y={barsH - (b.n / maxBurn) * barsH - 3} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={9} fill="var(--fg-2)">{b.n}</text>
            ))}
            <line x1={0} x2={iw} y1={barsH} y2={barsH} stroke="var(--border)" />
          </g>

          {/* hover targets */}
          {points.map((p) => (
            <rect key={`h${p.t}`} x={x(p.t) - iw / points.length / 2} y={0} width={iw / points.length} height={ih} fill="transparent"
                  onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)} />
          ))}
          {hover && <line x1={x(hover.t)} x2={x(hover.t)} y1={0} y2={ih} stroke="var(--fg-3)" strokeDasharray="2 2" pointerEvents="none" />}
        </g>
      </svg>
      <Legend />
      {hover && (
        <div style={{ position: "absolute", top: 8, right: 8, background: "var(--bg-inverse-deep)", color: "var(--fg-on-dark)",
                      borderRadius: "var(--radius-sm)", padding: "8px 10px", fontFamily: "var(--font-mono)", fontSize: 11, lineHeight: 1.6,
                      pointerEvents: "none" }}>
          <div style={{ fontWeight: 600 }}>{tLabel(hover.t)} · {hover.date}</div>
          <div>plan {hover.planned} · traditional {hover.traditional}</div>
          <div>{hover.actual != null ? `actual ${hover.actual}` : hover.projected != null ? `projected ${hover.projected}` : ""}</div>
        </div>
      )}
    </div>
  );
}

function Marker({ x, h, label, color, dashed, top = 0 }: { x: number; h: number; label: string; color: string; dashed?: boolean; top?: number }) {
  return (
    <g>
      <line x1={x} x2={x} y1={0} y2={h} stroke={color} strokeWidth={1.2} strokeDasharray={dashed ? "4 3" : undefined} />
      <text x={x + 4} y={top + 10} fontFamily="var(--font-mono)" fontSize={10} fill={color}>{label}</text>
    </g>
  );
}

function Legend() {
  const items: [string, React.ReactNode][] = [
    ["Actual", <line x1={0} x2={22} y1={5} y2={5} stroke="var(--db-lava-600)" strokeWidth={3.5} />],
    ["Projected", <line x1={0} x2={22} y1={5} y2={5} stroke="var(--db-lava-600)" strokeWidth={2.5} strokeDasharray="6 4" />],
    ["Plan (close calendar)", <line x1={0} x2={22} y1={5} y2={5} stroke="var(--db-navy-700)" strokeWidth={2} />],
    ["Traditional close (FY2025)", <line x1={0} x2={22} y1={5} y2={5} stroke="var(--db-navy-300)" strokeWidth={2} strokeDasharray="2 4" />],
    ["Ahead of plan", <rect width={22} height={10} fill="var(--success)" opacity={0.25} />],
    ["Behind plan", <rect width={22} height={10} fill="var(--danger)" opacity={0.25} />],
  ];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", marginTop: 4 }}>
      {items.map(([label, glyph]) => (
        <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-2)" }}>
          <svg width={22} height={10}>{glyph}</svg>{label}
        </span>
      ))}
    </div>
  );
}
