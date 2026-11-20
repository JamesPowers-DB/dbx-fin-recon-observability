// Subledger-to-GL tie-out heatmap: entity x recon type (AP, AR, Payroll). A cell
// is the difference in USD; out of tolerance cells are Lava, shaded by how far
// past tolerance they are. In-tolerance cells stay neutral.
import React from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import type { Row } from "../types";
import { fmtUSD } from "../format";

const TYPES = ["AP", "AR", "PAYROLL"];
const TYPE_LABEL: Record<string, string> = { AP: "AP (Oracle)", AR: "AR (Salesforce)", PAYROLL: "Payroll (Workday)" };

export function TieoutHeatmap({ cells, onCell, width = 560 }: { cells: Row[]; onCell?: (c: Row) => void; width?: number }) {
  const entities = Array.from(new Set(cells.map((c) => String(c.entity_code)))).sort();
  const rowH = 30;
  const m = { top: 30, left: 64, right: 8, bottom: 8 };
  const height = m.top + entities.length * rowH + m.bottom;
  const x = scaleBand<string>().domain(TYPES).range([0, width - m.left - m.right]).padding(0.06);
  const y = scaleBand<string>().domain(entities).range([0, entities.length * rowH]).padding(0.08);
  const ratio = (c: Row) => {
    const tol = Math.abs(Number(c.tolerance_amount ?? 0)) || 1;
    return Math.abs(Number(c.difference ?? 0)) / tol;
  };
  const maxR = Math.max(2, ...cells.filter((c) => !c.in_tolerance).map(ratio));
  const shade = scaleLinear().domain([1, maxR]).range([0.45, 1]).clamp(true);
  const by = new Map(cells.map((c) => [`${c.entity_code}|${c.recon_type}`, c]));

  return (
    <svg width={width} height={height} role="img" aria-label="Subledger tie-out heatmap">
      <g transform={`translate(${m.left},${m.top})`}>
        {TYPES.map((t) => (
          <text key={t} x={(x(t) ?? 0) + x.bandwidth() / 2} y={-10} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10.5}
                fill="var(--fg-2)" style={{ textTransform: "uppercase" }}>{TYPE_LABEL[t]}</text>
        ))}
        {entities.map((e) => (
          <g key={e}>
            <text x={-10} y={(y(e) ?? 0) + y.bandwidth() / 2} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={11} fill="var(--fg-1)">{e}</text>
            {TYPES.map((t) => {
              const c = by.get(`${e}|${t}`);
              const bx = x(t) ?? 0;
              const byy = y(e) ?? 0;
              if (!c) {
                return <rect key={t} x={bx} y={byy} width={x.bandwidth()} height={y.bandwidth()} fill="var(--bg-subtle)" rx={3} />;
              }
              const out = !c.in_tolerance;
              const zero = Math.abs(Number(c.difference_usd ?? 0)) < 0.005;
              return (
                <g key={t} onClick={onCell ? () => onCell(c) : undefined} style={{ cursor: onCell ? "pointer" : "default" }}>
                  <title>{`${e} ${t}: book ${fmtUSD(Number(c.book_balance), true)} ${c.currency_code}, subledger ${fmtUSD(Number(c.external_balance), true)}, difference ${fmtUSD(Number(c.difference_usd))} USD, tolerance ${fmtUSD(Number(c.tolerance_amount), true)} ${c.currency_code} (${c.control_id})`}</title>
                  <rect x={bx} y={byy} width={x.bandwidth()} height={y.bandwidth()} rx={3}
                        fill={out ? "var(--db-lava-600)" : "var(--bg-subtle)"} fillOpacity={out ? shade(ratio(c)) : 1}
                        stroke={out ? "var(--db-lava-700)" : "var(--border)"} />
                  <text x={bx + x.bandwidth() / 2} y={byy + y.bandwidth() / 2} dy="0.32em" textAnchor="middle" fontFamily="var(--font-mono)"
                        fontSize={10.5} fill={out ? "var(--fg-on-dark)" : zero ? "var(--fg-3)" : "var(--fg-1)"}>
                    {zero ? "tied" : `${Number(c.difference_usd) > 0 ? "+" : ""}${fmtUSD(Number(c.difference_usd), true)}`}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </g>
    </svg>
  );
}

/** Breaks per month and recon type (small grouped bars). */
export function TieoutTrend({ trend, width = 560, height = 140 }: { trend: Row[]; width?: number; height?: number }) {
  const periods = Array.from(new Set(trend.map((t) => String(t.period)))).sort();
  const m = { top: 12, right: 8, bottom: 22, left: 28 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const x = scaleBand<string>().domain(periods).range([0, iw]).padding(0.25);
  const xi = scaleBand<string>().domain(TYPES).range([0, x.bandwidth()]).padding(0.1);
  const maxB = Math.max(1, ...trend.map((t) => Number(t.breaks ?? 0)));
  const y = scaleLinear().domain([0, maxB]).range([ih, 0]).nice();
  const fill: Record<string, string> = { AP: "var(--db-navy-800)", AR: "var(--db-navy-400)", PAYROLL: "var(--db-navy-300)" };
  return (
    <svg width={width} height={height} role="img" aria-label="Tie-out breaks by month">
      <g transform={`translate(${m.left},${m.top})`}>
        {y.ticks(Math.min(4, maxB)).map((t) => (
          <g key={t}>
            <line x1={0} x2={iw} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="2 3" />
            <text x={-6} y={y(t)} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={9.5} fill="var(--fg-3)">{t}</text>
          </g>
        ))}
        {trend.map((t, i) => {
          const v = Number(t.breaks ?? 0);
          const bx = (x(String(t.period)) ?? 0) + (xi(String(t.recon_type)) ?? 0);
          return (
            <rect key={i} x={bx} y={y(v)} width={xi.bandwidth()} height={Math.max(0, ih - y(v))}
                  fill={v > 0 ? fill[String(t.recon_type)] ?? "var(--db-navy-400)" : "transparent"}>
              <title>{`${t.period} ${t.recon_type}: ${v} breaks, ${fmtUSD(Number(t.abs_difference_usd), true)} absolute difference`}</title>
            </rect>
          );
        })}
        {periods.map((p) => (
          <text key={p} x={(x(p) ?? 0) + x.bandwidth() / 2} y={ih + 14} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={9.5} fill="var(--fg-3)">{p}</text>
        ))}
      </g>
      <g transform={`translate(${width - 220},${4})`}>
        {TYPES.map((t, i) => (
          <g key={t} transform={`translate(${i * 72},0)`}>
            <rect width={9} height={9} fill={fill[t]} rx={2} />
            <text x={13} y={8} fontFamily="var(--font-mono)" fontSize={9.5} fill="var(--fg-2)">{t}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}
