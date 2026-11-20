// Segregation-of-duties matrix: Oracle roles involved in a conflict rule on both
// axes; a cell is the number of users holding both roles. Lava = conflict held.
import React from "react";
import { scaleBand } from "d3-scale";
import type { Row } from "../types";

export function SodMatrix({ pairs, width = 520 }: { pairs: Row[]; width?: number }) {
  const parsed = pairs.map((p) => {
    const [a, b] = String(p.conflict).split("+");
    return { a, b: b ?? "", users: Number(p.users ?? 0) };
  });
  const roles = Array.from(new Set(parsed.flatMap((p) => [p.a, p.b]).filter(Boolean))).sort();
  const cell = (r: string, c: string) => parsed.find((p) => (p.a === r && p.b === c) || (p.a === c && p.b === r));
  const left = 168;
  const top = 128;
  const size = Math.min(56, Math.max(32, Math.floor((width - left - 8) / Math.max(1, roles.length))));
  const x = scaleBand<string>().domain(roles).range([0, size * roles.length]);
  const height = top + size * roles.length + 8;
  if (!roles.length) return null;
  return (
    <svg width={Math.max(width, left + size * roles.length + 8)} height={height} role="img" aria-label="Segregation of duties conflict matrix">
      <g transform={`translate(${left},${top})`}>
        {roles.map((r) => (
          <g key={`c-${r}`} transform={`translate(${(x(r) ?? 0) + size / 2},-8) rotate(-40)`}>
            <text fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-2)">{r}</text>
          </g>
        ))}
        {roles.map((r) => (
          <g key={`r-${r}`}>
            <text x={-8} y={(x(r) ?? 0) + size / 2} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-2)">{r}</text>
            {roles.map((c) => {
              const hit = r !== c ? cell(r, c) : undefined;
              return (
                <g key={c}>
                  <rect x={x(c)} y={x(r)} width={size - 3} height={size - 3} rx={3}
                        fill={r === c ? "var(--bg-subtle)" : hit && hit.users > 0 ? "var(--db-lava-600)" : "var(--bg-canvas)"}
                        stroke="var(--border)">
                    {hit && <title>{`${hit.a} + ${hit.b}: ${hit.users} user${hit.users === 1 ? "" : "s"} hold both roles`}</title>}
                  </rect>
                  {hit && hit.users > 0 && (
                    <text x={(x(c) ?? 0) + (size - 3) / 2} y={(x(r) ?? 0) + (size - 3) / 2} dy="0.32em" textAnchor="middle"
                          fontFamily="var(--font-mono)" fontSize={12} fontWeight={600} fill="var(--fg-on-dark)">{hit.users}</text>
                  )}
                </g>
              );
            })}
          </g>
        ))}
      </g>
    </svg>
  );
}
