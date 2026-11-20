// One mark per control run (oldest -> newest): result color, height = exceptions.
import React from "react";
import type { SparkPoint } from "../types";

const COLOR = ["var(--danger)", "var(--info)", "var(--success)", "var(--db-navy-300)", "var(--border-strong)"];
const LABEL = ["FAIL", "RESOLVED", "PASS", "INFO", "NO POPULATION"];

export function RunSparkline({ points, width = 96, height = 22 }: { points: SparkPoint[]; width?: number; height?: number }) {
  if (!points.length) return <span style={{ color: "var(--fg-3)", fontFamily: "var(--font-mono)", fontSize: 10 }}>no runs</span>;
  const pts = points.slice(-16);
  const max = Math.max(1, ...pts.map((p) => p.exceptions || 0));
  const w = width / 16;
  return (
    <svg width={width} height={height} role="img" aria-label="Result per control run">
      {pts.map((p, i) => {
        const h = 4 + ((p.exceptions || 0) / max) * (height - 6);
        return (
          <rect key={p.run} x={i * w + 1} y={height - h} width={Math.max(2, w - 2)} height={h} rx={1.5} fill={COLOR[p.r] ?? COLOR[4]}>
            <title>{`run ${p.run}: ${LABEL[p.r] ?? "?"}, ${p.exceptions ?? 0} exceptions`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
