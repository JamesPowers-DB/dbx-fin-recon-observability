// Platform map: three bands (business lifecycle, deployed assets, Databricks
// features) laid out in HTML, with an SVG overlay that traces the hovered or
// selected node to its lifecycle stage and the features it uses.
import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { ASSETS, FEATURES, FEATURE_GROUPS, STAGES, TIER_LABEL, type MapNode, type Stage, type Tier } from "./platformMap";
import { monoCaption } from "../components/ui";

export type NodeState = "ok" | "warn" | "error" | "static";
export interface NodeStatus { state: NodeState; summary: string[]; error?: string; }

export const STATE_COLOR: Record<NodeState, string> = {
  ok: "var(--success)", warn: "var(--warning)", error: "var(--danger)", static: "var(--border-strong)",
};
export const STATE_LABEL: Record<NodeState, string> = {
  ok: "live", warn: "attention", error: "probe failed", static: "no live probe",
};

const key = (n: MapNode) => `${n.kind}:${n.id}`;

export function TierBadge({ tier, small }: { tier: Tier; small?: boolean }) {
  const border = tier === "live" ? "1px solid var(--db-navy-400)" : "1px dashed var(--border-strong)";
  const color = tier === "live" ? "var(--db-navy-700)" : tier === "config" ? "var(--fg-2)" : "var(--fg-3)";
  return (
    <span style={{ display: "inline-block", padding: small ? "0 5px" : "1px 7px", borderRadius: "var(--radius-pill)", border, color,
                   fontFamily: "var(--font-mono)", fontSize: small ? 9 : 10, textTransform: "uppercase", letterSpacing: "0.04em",
                   whiteSpace: "nowrap", background: "var(--bg-canvas)" }}>
      {TIER_LABEL[tier]}
    </span>
  );
}

function Dot({ state }: { state: NodeState }) {
  return <span title={STATE_LABEL[state]} style={{ width: 8, height: 8, borderRadius: "50%", background: STATE_COLOR[state], flexShrink: 0,
                                                   display: "inline-block", border: state === "static" ? "1px solid var(--fg-3)" : "none" }} />;
}

interface Props {
  status: (n: MapNode) => NodeStatus;
  selected: string | null;
  onSelect: (k: string) => void;
}

export function PlatformMapView({ status, selected, onSelect }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const refs = useRef(new Map<string, HTMLElement>());
  const [hover, setHover] = useState<string | null>(null);
  const [paths, setPaths] = useState<{ d: string; tone: "stage" | "feature" }[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const active = hover ?? selected;

  const setRef = useCallback((k: string) => (el: HTMLElement | null) => {
    if (el) refs.current.set(k, el); else refs.current.delete(k);
  }, []);

  // Which nodes the active node connects to.
  const related = React.useMemo(() => {
    const out = new Set<string>();
    if (!active) return out;
    const [kind, id] = active.split(":");
    if (kind === "asset") {
      const a = ASSETS.find((x) => x.id === id);
      if (a?.stage) out.add(`stage:${a.stage}`);
      (a?.uses ?? []).forEach((f) => out.add(`feature:${f}`));
    } else if (kind === "feature") {
      ASSETS.filter((a) => a.uses?.includes(id)).forEach((a) => out.add(`asset:${a.id}`));
    } else if (kind === "stage") {
      ASSETS.filter((a) => a.stage === id).forEach((a) => out.add(`asset:${a.id}`));
    }
    return out;
  }, [active]);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const compute = () => {
      const box = el.getBoundingClientRect();
      setSize({ w: box.width, h: box.height });
      if (!active) { setPaths([]); return; }
      const pt = (k: string, edge: "top" | "bottom") => {
        const r = refs.current.get(k)?.getBoundingClientRect();
        if (!r) return null;
        return { x: r.left - box.left + r.width / 2, y: (edge === "top" ? r.top : r.bottom) - box.top };
      };
      const curve = (a: { x: number; y: number }, b: { x: number; y: number }) => {
        const my = (a.y + b.y) / 2;
        return `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
      };
      const out: { d: string; tone: "stage" | "feature" }[] = [];
      const [kind] = active.split(":");
      related.forEach((r) => {
        const rk = r.split(":")[0];
        if (kind === "asset" && rk === "stage") { const a = pt(r, "bottom"), b = pt(active, "top"); if (a && b) out.push({ d: curve(a, b), tone: "stage" }); }
        if (kind === "asset" && rk === "feature") { const a = pt(active, "bottom"), b = pt(r, "top"); if (a && b) out.push({ d: curve(a, b), tone: "feature" }); }
        if (kind === "feature" && rk === "asset") { const a = pt(r, "bottom"), b = pt(active, "top"); if (a && b) out.push({ d: curve(a, b), tone: "feature" }); }
        if (kind === "stage" && rk === "asset") { const a = pt(active, "bottom"), b = pt(r, "top"); if (a && b) out.push({ d: curve(a, b), tone: "stage" }); }
      });
      setPaths(out);
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [active, related]);

  const dim = (k: string) => active != null && k !== active && !related.has(k);

  const bandLabel = (text: string) => (
    <div style={{ ...monoCaption, textTransform: "uppercase", letterSpacing: "var(--tracking-eyebrow)", margin: "0 0 8px 2px" }}>{text}</div>
  );

  return (
    <div ref={wrap} style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
      {/* Connectors sit behind the boxes: visible in the gaps, hidden under opaque cards. */}
      <svg width={size.w} height={size.h} style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "visible", zIndex: 0 }}>
        {paths.map((p, i) => (
          <path key={i} d={p.d} fill="none" stroke={p.tone === "stage" ? "var(--db-navy-400)" : "var(--db-lava-600)"}
                strokeWidth={1.6} strokeDasharray={p.tone === "stage" ? "4 3" : undefined} opacity={0.85} />
        ))}
      </svg>
      <div style={{ position: "relative", zIndex: 1 }}>
      {/* Band 1: business lifecycle */}
      {bandLabel("Business lifecycle")}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${STAGES.length}, minmax(0, 1fr))`, gap: 10, marginBottom: 28 }}>
        {STAGES.map((s) => <StageBox key={s.id} s={s} r={setRef(`stage:${s.id}`)} dim={dim(`stage:${s.id}`)} on={active === `stage:${s.id}`}
                                     onHover={() => setHover(`stage:${s.id}`)} onClick={() => onSelect(`stage:${s.id}`)} />)}
      </div>

      {/* Band 2: deployed assets, one column per stage */}
      {bandLabel("Deployed in this demo")}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${STAGES.length}, minmax(0, 1fr))`, gap: 10, marginBottom: 36, alignItems: "start" }}>
        {STAGES.map((s) => (
          <div key={s.id} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {ASSETS.filter((a) => a.stage === s.id).map((a) => (
              <NodeCard key={a.id} n={a} st={status(a)} r={setRef(key(a))} dim={dim(key(a))} on={active === key(a)}
                        onHover={() => setHover(key(a))} onClick={() => onSelect(key(a))} />
            ))}
          </div>
        ))}
      </div>

      {/* Band 3: Databricks features */}
      {bandLabel("Databricks features underneath")}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${FEATURE_GROUPS.length}, minmax(0, 1fr))`, gap: 10 }}>
        {FEATURE_GROUPS.map((g) => (
          <div key={g.id} style={{ background: "transparent", borderRadius: "var(--radius-md)",
                                   padding: 8, border: g.id === "next" ? "1px dashed var(--border-strong)" : "1px solid var(--border)" }}>
            <div style={{ ...monoCaption, fontSize: 10, textTransform: "uppercase", marginBottom: 6 }}>{g.label}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {FEATURES.filter((f) => f.group === g.id).map((f) => (
                <FeatureChip key={f.id} n={f} st={status(f)} r={setRef(key(f))} dim={dim(key(f))} on={active === key(f)}
                             onHover={() => setHover(key(f))} onClick={() => onSelect(key(f))} />
              ))}
            </div>
          </div>
        ))}
      </div>
      </div>
    </div>
  );
}

const interactive = (on: boolean, dim: boolean): React.CSSProperties => ({
  opacity: dim ? 0.35 : 1,
  transition: "opacity var(--dur-base) var(--ease-out), border-color var(--dur-fast), box-shadow var(--dur-fast)",
  cursor: "pointer", textAlign: "left", fontFamily: "var(--font-sans)",
  boxShadow: on ? "var(--shadow-md)" : "none",
});

function StageBox({ s, r, dim, on, onHover, onClick }: { s: Stage; r: (el: HTMLElement | null) => void; dim: boolean; on: boolean; onHover: () => void; onClick: () => void }) {
  return (
    <button ref={r} onMouseEnter={onHover} onFocus={onHover} onClick={onClick}
            style={{ ...interactive(on, dim), background: "var(--bg-inverse-deep)", color: "var(--fg-on-dark)", border: on ? "1px solid var(--db-lava-600)" : "1px solid var(--border-dark)",
                     borderRadius: "var(--radius-md)", padding: "10px 12px", minHeight: 74, position: "relative" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--db-lava-300)", marginBottom: 4 }}>{String(s.n).padStart(2, "0")}</div>
      <div style={{ fontSize: "var(--fs-body-sm)", fontWeight: 700, lineHeight: 1.2 }}>{s.label}</div>
      <div style={{ fontSize: 11, color: "var(--db-navy-300)", marginTop: 4, lineHeight: 1.3 }}>{s.caption}</div>
    </button>
  );
}

function NodeCard({ n, st, r, dim, on, onHover, onClick }: { n: MapNode; st: NodeStatus; r: (el: HTMLElement | null) => void; dim: boolean; on: boolean; onHover: () => void; onClick: () => void }) {
  return (
    <button ref={r} onMouseEnter={onHover} onFocus={onHover} onClick={onClick}
            style={{ ...interactive(on, dim), background: "var(--bg-canvas)", border: `1px solid ${on ? "var(--db-lava-600)" : "var(--border)"}`,
                     borderRadius: "var(--radius-md)", padding: "9px 10px", display: "flex", flexDirection: "column", gap: 4, width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Dot state={st.state} />
        <span style={{ fontSize: "var(--fs-body-sm)", fontWeight: 700, color: "var(--fg-1)", lineHeight: 1.2 }}>{n.label}</span>
      </div>
      <div style={{ fontSize: 11, color: "var(--fg-2)", lineHeight: 1.3 }}>{n.sub}</div>
      {st.summary.slice(0, 2).map((t, i) => (
        <div key={i} style={{ ...monoCaption, fontSize: 10, color: "var(--fg-1)", lineHeight: 1.35, wordBreak: "break-word" }}>{t}</div>
      ))}
      {st.error && <div style={{ ...monoCaption, fontSize: 10, color: "var(--danger)", lineHeight: 1.35, wordBreak: "break-word" }}>{st.error.slice(0, 90)}</div>}
    </button>
  );
}

function FeatureChip({ n, st, r, dim, on, onHover, onClick }: { n: MapNode; st: NodeStatus; r: (el: HTMLElement | null) => void; dim: boolean; on: boolean; onHover: () => void; onClick: () => void }) {
  return (
    <button ref={r} onMouseEnter={onHover} onFocus={onHover} onClick={onClick}
            style={{ ...interactive(on, dim), background: "var(--bg-canvas)", borderRadius: "var(--radius-sm)", padding: "6px 8px", width: "100%",
                     border: `1px ${n.tier === "live" ? "solid" : "dashed"} ${on ? "var(--db-lava-600)" : "var(--border-strong)"}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {n.tier === "live" ? <Dot state={st.state} /> : <TierBadge tier={n.tier} small />}
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg-1)", lineHeight: 1.2 }}>{n.label}</span>
      </div>
      <div style={{ fontSize: 10.5, color: "var(--fg-2)", marginTop: 2, lineHeight: 1.3 }}>{n.sub}</div>
    </button>
  );
}
