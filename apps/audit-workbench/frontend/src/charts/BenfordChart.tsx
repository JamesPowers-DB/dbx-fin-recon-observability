// First-digit (Benford) test for manual journal amounts: observed share per
// leading digit (bars) against the expected Benford share (line). Digits whose
// observed share departs from expected by more than `flagGap` are Lava.
import React from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import { line } from "d3-shape";

export interface DigitRow { digit: number; expected_pct: number; observed_pct: number }

export function BenfordChart({ digits, width = 560, height = 240, flagGap = 0.03 }: { digits: DigitRow[]; width?: number; height?: number; flagGap?: number }) {
  const m = { top: 16, right: 12, bottom: 30, left: 40 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const x = scaleBand<number>().domain(digits.map((d) => d.digit)).range([0, iw]).padding(0.28);
  const maxV = Math.max(0.35, ...digits.map((d) => Math.max(d.expected_pct, d.observed_pct)));
  const y = scaleLinear().domain([0, maxV]).range([ih, 0]).nice();
  const path = line<DigitRow>().x((d) => (x(d.digit) ?? 0) + x.bandwidth() / 2).y((d) => y(d.expected_pct))(digits) ?? "";
  return (
    <svg width={width} height={height} role="img" aria-label="Benford first-digit distribution">
      <g transform={`translate(${m.left},${m.top})`}>
        {y.ticks(4).map((t) => (
          <g key={t}>
            <line x1={0} x2={iw} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="2 3" />
            <text x={-6} y={y(t)} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">{Math.round(t * 100)}%</text>
          </g>
        ))}
        {digits.map((d) => {
          const off = Math.abs(d.observed_pct - d.expected_pct) > flagGap;
          return (
            <g key={d.digit}>
              <rect x={x(d.digit)} y={y(d.observed_pct)} width={x.bandwidth()} height={Math.max(0, ih - y(d.observed_pct))} rx={2}
                    fill={off ? "var(--db-lava-600)" : "var(--db-navy-800)"}>
                <title>{`Digit ${d.digit}: observed ${(d.observed_pct * 100).toFixed(1)}%, expected ${(d.expected_pct * 100).toFixed(1)}%`}</title>
              </rect>
              <text x={(x(d.digit) ?? 0) + x.bandwidth() / 2} y={ih + 16} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={11} fill="var(--fg-1)">{d.digit}</text>
            </g>
          );
        })}
        <path d={path} fill="none" stroke="var(--db-navy-400)" strokeWidth={2} strokeDasharray="4 3" />
        {digits.map((d) => (
          <circle key={d.digit} cx={(x(d.digit) ?? 0) + x.bandwidth() / 2} cy={y(d.expected_pct)} r={3} fill="var(--bg-canvas)" stroke="var(--db-navy-400)" strokeWidth={2} />
        ))}
      </g>
      <g transform={`translate(${width - 250},${2})`} fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-2)">
        <rect width={10} height={10} fill="var(--db-navy-800)" rx={2} /><text x={14} y={9}>observed</text>
        <line x1={78} x2={96} y1={5} y2={5} stroke="var(--db-navy-400)" strokeWidth={2} strokeDasharray="4 3" /><text x={100} y={9}>Benford</text>
        <rect x={154} width={10} height={10} fill="var(--db-lava-600)" rx={2} /><text x={168} y={9}>off by &gt;{Math.round(flagGap * 100)} pts</text>
      </g>
    </svg>
  );
}
