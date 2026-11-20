// Data-quality and lineage Sankey: the pipeline's own flow graph for one update
// (meta_pipeline_update_metrics, copied from the published event log).
// d3-sankey supplies layout math only (node positions, band widths, link paths);
// every mark is drawn here as SVG. Columns follow graph depth, so every band
// flows left to right; exception nodes are pinned to the right edge.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { sankey as d3sankey, sankeyLinkHorizontal } from "d3-sankey";
import type { FlowStatus, SankeyLink as FlowLink, SankeyNode as FlowNode } from "../types";

export const FLOW_COLOR: Record<FlowStatus, string> = {
  ok: "var(--db-navy-400)",
  warn: "var(--db-yellow-600)",
  drift: "var(--warning)",
  fail: "var(--db-lava-600)",
};
const NODE_COLOR: Record<FlowStatus, string> = {
  ok: "var(--db-navy-700)",
  warn: "var(--db-yellow-600)",
  drift: "var(--warning)",
  fail: "var(--db-lava-600)",
};
export const FLOW_LABEL: Record<FlowStatus, string> = {
  ok: "Flowing, no issues",
  warn: "Expectation warnings (rows kept, flagged)",
  drift: "Schema drift (rescued data)",
  fail: "Open exceptions or failed flow",
};
export const STAGE_LABEL: Record<string, string> = {
  source: "Source system", bronze: "Bronze", silver: "Silver", gold: "Gold", tests: "Control tests", exceptions: "Exceptions",
};

type LNode = FlowNode & { x0?: number; x1?: number; y0?: number; y1?: number; layer?: number; depth?: number; value?: number };
type LLink = Omit<FlowLink, "source" | "target"> & { source: LNode | string; target: LNode | string; value: number; width?: number; y0?: number; y1?: number; index?: number };

/** Band value: square root of rows, so a 10-row control test stays visible next to a 300k-row ledger. */
export const bandValue = (rows: number) => Math.max(1, Math.sqrt(Math.max(0, rows)));

export interface SankeySelection { kind: "node" | "link"; id: string; }

export function Sankey({ nodes, links, height, dense, selected, onSelect, minWidth = 640 }: {
  nodes: FlowNode[]; links: FlowLink[]; height: number; dense?: boolean; minWidth?: number;
  selected?: SankeySelection | null; onSelect?: (s: SankeySelection, node?: FlowNode, link?: FlowLink) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1100);
  const [hover, setHover] = useState<{ x: number; y: number; html: React.ReactNode } | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((es) => { for (const e of es) setWidth(Math.max(minWidth, Math.floor(e.contentRect.width))); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [minWidth]);

  const labelRoom = dense ? 210 : 250;      // right margin for the last column's labels
  const labelLeft = dense ? 150 : 160;      // left margin: source labels sit left of their nodes
  const layout = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    const ln: LNode[] = nodes.map((n) => ({ ...n }));
    const ll: LLink[] = links
      .filter((l) => ids.has(l.source) && ids.has(l.target) && l.source !== l.target)
      .map((l, i) => ({ ...l, value: bandValue(l.rows), index: i }));
    try {
      const gen = d3sankey<LNode, LLink>()
        .nodeId((n) => n.id)
        .nodeAlign((n, cols) => (n.stage === "exceptions" ? cols - 1 : n.depth ?? 0))
        .nodeWidth(dense ? 10 : 14)
        .nodePadding(dense ? 4 : 12)
        .extent([[labelLeft, 8], [Math.max(labelLeft + 300, width - labelRoom), height - 8]]);
      const g = gen({ nodes: ln, links: ll });
      return { nodes: g.nodes, links: g.links, error: null as string | null };
    } catch (e) {
      console.error("sankey layout failed", e);
      return { nodes: [] as LNode[], links: [] as LLink[], error: e instanceof Error ? e.message : String(e) };
    }
  }, [nodes, links, width, height, dense, labelRoom, labelLeft]);

  if (layout.error) {
    return <div ref={wrap} style={{ padding: 16, color: "var(--danger)", fontFamily: "var(--font-mono)", fontSize: 12 }}>Layout failed: {layout.error}</div>;
  }
  const path = sankeyLinkHorizontal<LNode, LLink>();
  const maxLayer = Math.max(0, ...layout.nodes.map((n) => n.layer ?? 0));
  const nodeOf = (x: LNode | string) => (typeof x === "string" ? undefined : x);
  const touches = (l: LLink, id: string) => nodeOf(l.source)?.id === id || nodeOf(l.target)?.id === id;
  const linkId = (l: LLink) => `${nodeOf(l.source)?.id}->${nodeOf(l.target)?.id}`;
  const focus = hoverId ?? (selected?.kind === "node" ? selected.id : null);
  const selLink = selected?.kind === "link" ? selected.id : null;

  // Label placement: each label goes on the side (right of the node, or left) with more free room
  // before the nearest node at the same height; names win over row counts when space is short.
  const charW = dense ? 6.0 : 6.4;
  const place = new Map<string, { right: boolean; chars: number }>();
  for (const n of layout.nodes) {
    if (n.x0 == null || n.x1 == null || n.y0 == null || n.y1 == null) continue;
    const cy = (n.y0 + n.y1) / 2;
    let rightLimit = width - 4;
    let leftLimit = 4;
    for (const m of layout.nodes) {
      if (m === n || m.x0 == null || m.x1 == null || m.y0 == null || m.y1 == null) continue;
      if (!(m.y0 - 7 <= cy && m.y1 + 7 >= cy)) continue;
      if (m.x0 > n.x1) rightLimit = Math.min(rightLimit, m.x0 - 6);
      if (m.x1 < n.x0) leftLimit = Math.max(leftLimit, m.x1 + 6);
    }
    const rightRoom = Math.floor((rightLimit - (n.x1 + 6)) / charW);
    const leftRoom = Math.floor(((n.x0 - 6) - leftLimit) / charW);
    if (n.stage === "source") place.set(n.id, { right: false, chars: leftRoom });
    else if (n.stage === "exceptions") place.set(n.id, { right: true, chars: rightRoom });
    else {
      const need = displayName(n, dense).length;
      const right = rightRoom >= need || rightRoom >= leftRoom;
      place.set(n.id, { right, chars: right ? rightRoom : leftRoom });
    }
  }

  const tip = (e: React.MouseEvent, html: React.ReactNode) => {
    const r = wrap.current?.getBoundingClientRect();
    if (!r) return;
    setHover({ x: e.clientX - r.left + 14, y: e.clientY - r.top + 10, html });
  };

  return (
    <div ref={wrap} style={{ position: "relative", width: "100%", minWidth }} onMouseLeave={() => { setHover(null); setHoverId(null); }}>
      <svg width={width} height={height} role="img" aria-label="Lineage and data-quality flow" style={{ display: "block" }}>
        <g fill="none">
          {layout.links.map((l) => {
            const id = linkId(l);
            const dim = (focus && !touches(l, focus)) || (selLink && selLink !== id);
            const on = selLink === id || (focus != null && touches(l, focus));
            return (
              <path key={id} d={path(l) ?? undefined} stroke={FLOW_COLOR[l.status]} strokeWidth={Math.max(1, l.width ?? 1)}
                    strokeOpacity={dim ? 0.08 : on ? 0.75 : l.status === "ok" ? 0.32 : 0.6}
                    style={{ cursor: onSelect ? "pointer" : "default", transition: "stroke-opacity 160ms ease-out" }}
                    onMouseMove={(e) => tip(e, (
                      <>
                        <b>{nodeOf(l.source)?.label}</b> to <b>{nodeOf(l.target)?.label}</b><br />
                        {l.rows.toLocaleString("en-US")} rows read{l.datasets.length ? ` into ${l.datasets.length} dataset${l.datasets.length > 1 ? "s" : ""}` : ""}<br />
                        <span style={{ color: "var(--db-navy-300)" }}>{FLOW_LABEL[l.status]}</span>
                      </>
                    ))}
                    onClick={() => onSelect?.({ kind: "link", id }, undefined, links.find((x) => `${x.source}->${x.target}` === id))} />
            );
          })}
        </g>
        <g>
          {layout.nodes.map((n) => {
            const x0 = n.x0 ?? 0, x1 = n.x1 ?? 0, y0 = n.y0 ?? 0, y1 = n.y1 ?? 0;
            const h = Math.max(2, y1 - y0);
            const dim = focus != null && focus !== n.id && !layout.links.some((l) => touches(l, focus) && touches(l, n.id));
            const sel = selected?.kind === "node" && selected.id === n.id;
            const pl = place.get(n.id) ?? { right: true, chars: 40 };
            const right = pl.right;
            const showLabel = !dense || h >= 6 || sel || hoverId === n.id || n.stage === "exceptions" || n.stage === "source";
            const rowsTag = dense ? "" : ` ${compactRows(n.rows)}`;
            let name = !dense && n.stage === "bronze" ? "" : displayName(n, dense);
            const cap = Math.min(dense ? 34 : 44, pl.chars);
            if (name.length > cap) name = cap >= 5 ? `${name.slice(0, cap - 1)}…` : "";
            const showRows = !dense && pl.chars >= name.length + rowsTag.length;
            const tone = n.status === "ok" ? "var(--fg-1)" : n.status === "fail" ? "var(--db-lava-600)" : "var(--warning)";
            return (
              <g key={n.id} opacity={dim ? 0.35 : 1} style={{ cursor: onSelect ? "pointer" : "default", transition: "opacity 160ms ease-out" }}
                 onMouseEnter={() => setHoverId(n.id)} onMouseLeave={() => setHoverId(null)}
                 onMouseMove={(e) => tip(e, (
                   <>
                     <span style={{ color: "var(--db-navy-300)" }}>{STAGE_LABEL[n.stage] ?? n.stage}</span><br />
                     <b>{n.label}</b><br />
                     {n.rows.toLocaleString("en-US")} rows{n.datasets.length > 1 ? ` in ${n.datasets.length} datasets` : ""}
                     {n.failed_records > 0 && <><br />{n.failed_records.toLocaleString("en-US")} rows failing an expectation</>}
                     {n.rescued_rows > 0 && <><br />{n.rescued_rows.toLocaleString("en-US")} rows with rescued data</>}
                   </>
                 ))}
                 onClick={() => onSelect?.({ kind: "node", id: n.id }, nodes.find((x) => x.id === n.id))}>
                <rect x={x0} y={y0} width={x1 - x0} height={h} rx={2} fill={NODE_COLOR[n.status]}
                      stroke={sel ? "var(--db-lava-600)" : "none"} strokeWidth={sel ? 2 : 0} />
                {showLabel && (
                  <text x={right ? x1 + 6 : x0 - 6} y={y0 + h / 2} dy="0.35em" textAnchor={right ? "start" : "end"}
                        style={{ fontFamily: dense ? "var(--font-mono)" : "var(--font-sans)", fontSize: dense ? 10 : 12, fill: tone,
                                 fontWeight: sel ? 700 : n.status === "ok" ? 500 : 600, pointerEvents: "none",
                                 paintOrder: "stroke", stroke: "var(--bg-canvas)", strokeWidth: 3, strokeLinejoin: "round" }}>
                    {name}
                    {showRows && <tspan style={{ fill: "var(--fg-3)", fontFamily: "var(--font-mono)", fontSize: 10 }}>{name ? " " : ""}{compactRows(n.rows)}</tspan>}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      {hover && (
        <div style={{ position: "absolute", left: Math.min(hover.x, width - 280), top: hover.y, maxWidth: 280, pointerEvents: "none",
                      background: "var(--bg-inverse-deep)", color: "var(--fg-on-dark)", padding: "8px 10px", borderRadius: "var(--radius-sm)",
                      fontSize: 12, lineHeight: 1.45, boxShadow: "var(--shadow-md)", zIndex: 5 }}>
          {hover.html}
        </div>
      )}
    </div>
  );
}

/** Dataset level: drop the layer prefix (the stage is in the tooltip). */
function displayName(n: { label: string; stage: string }, dense?: boolean): string {
  return dense ? n.label.replace(/^(bronze|silver|gold)_/, "") : n.label;
}

export function compactRows(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k`;
  return String(n);
}

export function SankeyLegend() {
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {(Object.keys(FLOW_LABEL) as FlowStatus[]).map((s) => (
        <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "var(--fs-caption)", color: "var(--fg-2)" }}>
          <span style={{ width: 18, height: 8, borderRadius: 2, background: FLOW_COLOR[s], opacity: s === "ok" ? 0.6 : 0.9 }} />
          {FLOW_LABEL[s]}
        </span>
      ))}
    </div>
  );
}
