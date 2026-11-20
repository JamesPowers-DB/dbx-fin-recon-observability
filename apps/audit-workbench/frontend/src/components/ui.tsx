// Shared UI kit for every page: data loading states, sections, status badges,
// tables, drawer, tabs, code blocks, deep links. Tokens only (no hex).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import type { LinkTemplates, Row } from "../types";

// ── Data loading ────────────────────────────────────────────────────────────
export interface ApiState<T> { data: T | null; error: string | null; loading: boolean; reload: () => void; }

/** Run `fn` on mount and whenever `deps` change. Keeps the last data while reloading. */
export function useApi<T>(fn: () => Promise<T>, deps: React.DependencyList = []): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let live = true;
    setLoading(true);
    fnRef.current()
      .then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e: unknown) => {
        console.error(e);
        if (live) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Loading / error / empty wrapper. Children render only with data. */
export function Async<T>({ state, empty, emptyText, height, children }: {
  state: ApiState<T>; empty?: (d: T) => boolean; emptyText?: React.ReactNode; height?: number;
  children: (d: T) => React.ReactNode;
}) {
  if (state.error && !state.data) return <ErrorNote message={state.error} onRetry={state.reload} />;
  if (!state.data) return <LoadingNote height={height} />;
  if (empty && empty(state.data)) return <EmptyNote>{emptyText ?? "Nothing to show for this selection."}</EmptyNote>;
  return <>{children(state.data)}</>;
}

export function LoadingNote({ height, text = "loading…" }: { height?: number; text?: string }) {
  return (
    <div style={{ minHeight: height ?? 60, display: "flex", alignItems: "center", justifyContent: "center",
                  fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", color: "var(--fg-3)" }}>
      {text}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div style={{ padding: "var(--space-4)", borderRadius: "var(--radius-md)", background: "var(--danger-bg)",
                  border: "1px solid var(--danger)", color: "var(--fg-1)", fontSize: "var(--fs-body-sm)",
                  display: "flex", gap: "var(--space-3)", alignItems: "flex-start" }}>
      <Icon name="warn" size={16} color="var(--danger)" />
      <div style={{ flex: 1, wordBreak: "break-word" }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>Could not load this panel</div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", color: "var(--fg-2)" }}>{message.slice(0, 600)}</div>
      </div>
      {onRetry && <button onClick={onRetry} style={linkBtn}>Retry</button>}
    </div>
  );
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: "var(--space-5)", textAlign: "center", color: "var(--fg-3)", fontSize: "var(--fs-body-sm)",
                  border: "1px dashed var(--border)", borderRadius: "var(--radius-md)" }}>
      {children}
    </div>
  );
}

export function Notice({ kind = "info", children, onClose }: { kind?: "info" | "success" | "warning" | "danger"; children: React.ReactNode; onClose?: () => void }) {
  return (
    <div style={{ padding: "var(--space-3) var(--space-4)", borderRadius: "var(--radius-md)", background: `var(--${kind}-bg)`,
                  border: `1px solid var(--${kind})`, fontSize: "var(--fs-body-sm)", display: "flex", gap: "var(--space-3)",
                  alignItems: "flex-start" }}>
      <div style={{ flex: 1 }}>{children}</div>
      {onClose && <button onClick={onClose} style={{ ...linkBtn, color: "var(--fg-2)" }} aria-label="Dismiss"><Icon name="x" size={14} /></button>}
    </div>
  );
}

// ── Layout ──────────────────────────────────────────────────────────────────
export function Page({ children }: { children: React.ReactNode }) {
  return <div style={{ padding: "var(--space-8) var(--space-8) var(--space-10)", maxWidth: 1480, width: "100%", boxSizing: "border-box" }}>{children}</div>;
}

export function Section({ title, eyebrow, right, children, style, padding }: {
  title?: React.ReactNode; eyebrow?: string; right?: React.ReactNode; children: React.ReactNode; style?: React.CSSProperties; padding?: string | number;
}) {
  return (
    <section style={{ background: "var(--bg-canvas)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)",
                      padding: padding ?? "var(--space-5)", ...style }}>
      {(title || right || eyebrow) && (
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
          <div>
            {eyebrow && <div style={eyebrowStyle}>{eyebrow}</div>}
            {title && <h3 style={{ margin: 0, fontSize: "var(--fs-h4)", fontWeight: 700, color: "var(--fg-1)" }}>{title}</h3>}
          </div>
          {right && <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>{right}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Grid({ cols = 2, gap = "var(--space-5)", children, style }: { cols?: number | string; gap?: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ display: "grid", gridTemplateColumns: typeof cols === "number" ? `repeat(${cols}, minmax(0, 1fr))` : cols, gap, ...style }}>{children}</div>;
}

export function Stack({ gap = "var(--space-5)", children, style }: { gap?: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ display: "flex", flexDirection: "column", gap, ...style }}>{children}</div>;
}

export const eyebrowStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: "var(--fs-eyebrow)", textTransform: "uppercase",
  letterSpacing: "var(--tracking-eyebrow)", color: "var(--fg-3)", marginBottom: 4,
};
export const monoCaption: React.CSSProperties = { fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", color: "var(--fg-3)" };
export const linkBtn: React.CSSProperties = {
  background: "none", border: "none", padding: 0, color: "var(--fg-link)", cursor: "pointer",
  fontSize: "var(--fs-body-sm)", fontFamily: "var(--font-sans)",
};

export function Mono({ children, dim, style }: { children: React.ReactNode; dim?: boolean; style?: React.CSSProperties }) {
  return <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", color: dim ? "var(--fg-3)" : "var(--fg-1)", ...style }}>{children}</span>;
}

// ── Status ──────────────────────────────────────────────────────────────────
type Tone = "success" | "danger" | "warning" | "info" | "neutral" | "accent";
const STATUS_TONE: Record<string, Tone> = {
  PASS: "success", RESOLVED: "info", FAIL: "danger", INFO: "neutral", STALE: "warning", NOT_RUN: "neutral", NO_POPULATION: "neutral",
  COMPLETE: "success", READY_FOR_SIGNOFF: "info", BLOCKED: "danger", WAITING: "neutral", NOT_STARTED: "neutral", REOPENED: "warning",
  open: "danger", proposed: "warning", approved: "success", rejected: "danger",
  critical: "danger", high: "danger", medium: "warning", low: "neutral",
  FINAL: "success", DRAFT: "warning", SUCCESS: "success", SUCCEEDED: "success", FAILED: "danger", RUNNING: "info", PENDING: "neutral", QUEUED: "neutral",
  BLOCKED_RUN: "neutral", TERMINATED: "neutral", SKIPPED: "neutral", ok: "success", warn: "warning", drift: "warning", fail: "danger",
  NEW: "danger", RECURRING: "warning", BASELINE: "neutral", "Within appetite": "success", Monitor: "warning", Elevated: "danger",
};
const TONE_STYLE: Record<Tone, { bg: string; fg: string; bd: string }> = {
  success: { bg: "var(--success-bg)", fg: "var(--success)", bd: "var(--success)" },
  danger: { bg: "var(--danger-bg)", fg: "var(--danger)", bd: "var(--danger)" },
  warning: { bg: "var(--warning-bg)", fg: "var(--fg-1)", bd: "var(--warning)" },
  info: { bg: "var(--info-bg)", fg: "var(--info)", bd: "var(--info)" },
  neutral: { bg: "var(--bg-subtle)", fg: "var(--fg-2)", bd: "var(--border-strong)" },
  accent: { bg: "var(--bg-subtle)", fg: "var(--fg-accent)", bd: "var(--db-lava-600)" },
};
export const STATUS_LABEL: Record<string, string> = {
  READY_FOR_SIGNOFF: "Ready for sign-off", NOT_STARTED: "Not started", NO_POPULATION: "No population", NOT_RUN: "Not run",
};

export function toneOf(status: string | null | undefined): Tone { return STATUS_TONE[status ?? ""] ?? "neutral"; }
export function toneColor(status: string | null | undefined): string { return TONE_STYLE[toneOf(status)].bd; }

export function StatusBadge({ status, label, small }: { status: string | null | undefined; label?: string; small?: boolean }) {
  const t = TONE_STYLE[toneOf(status)];
  const text = label ?? STATUS_LABEL[status ?? ""] ?? (status ?? "—");
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: small ? "1px 6px" : "2px 8px",
                   borderRadius: "var(--radius-pill)", background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
                   fontFamily: "var(--font-mono)", fontSize: small ? 10 : "var(--fs-caption)", fontWeight: 500,
                   textTransform: text.length <= 18 ? "uppercase" : "none", letterSpacing: "0.02em", whiteSpace: "nowrap" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.bd }} />
      {text}
    </span>
  );
}

/** Mandatory label on every AI-generated artifact. */
export function AiBadge({ model, text = "AI-generated" }: { model?: string | null; text?: string }) {
  return (
    <span title={model ? `Model: ${model}` : undefined}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "1px 7px", borderRadius: "var(--radius-pill)",
                   border: "1px solid var(--db-navy-400)", color: "var(--db-navy-700)", background: "var(--bg-subtle)",
                   fontFamily: "var(--font-mono)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
      <Icon name="spark" size={11} /> {text}
    </span>
  );
}

// ── Table ───────────────────────────────────────────────────────────────────
export interface Column<T> {
  key: string; label: React.ReactNode; align?: "left" | "right" | "center"; width?: number | string; mono?: boolean;
  render?: (row: T) => React.ReactNode;
}

export function DataTable<T extends Row>({ columns, rows, onRowClick, activeKey, rowKey, maxHeight, empty, dense }: {
  columns: Column<T>[]; rows: T[]; onRowClick?: (r: T) => void; activeKey?: string | null; rowKey?: (r: T) => string;
  maxHeight?: number; empty?: React.ReactNode; dense?: boolean;
}) {
  if (!rows.length) return <EmptyNote>{empty ?? "No rows."}</EmptyNote>;
  const pad = dense ? "6px 10px" : "9px 12px";
  return (
    <div style={{ overflow: "auto", maxHeight, border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
      <table style={{ minWidth: "100%", borderCollapse: "collapse", fontSize: "var(--fs-body-sm)" }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{ position: "sticky", top: 0, background: "var(--bg-subtle)", textAlign: c.align ?? "left",
                                       padding: pad, borderBottom: "1px solid var(--border)", fontFamily: "var(--font-mono)",
                                       fontSize: "var(--fs-caption)", fontWeight: 500, color: "var(--fg-2)", textTransform: "uppercase",
                                       letterSpacing: "0.03em", whiteSpace: "nowrap", width: c.width, zIndex: 1 }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const k = rowKey ? rowKey(r) : String(i);
            const active = activeKey != null && k === activeKey;
            return (
              <tr key={k} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  style={{ cursor: onRowClick ? "pointer" : "default", background: active ? "var(--bg-subtle)" : undefined,
                           boxShadow: active ? "inset 3px 0 0 var(--db-lava-600)" : undefined }}
                  onMouseEnter={(e) => { if (onRowClick && !active) e.currentTarget.style.background = "var(--bg-subtle)"; }}
                  onMouseLeave={(e) => { if (onRowClick && !active) e.currentTarget.style.background = ""; }}>
                {columns.map((c) => (
                  <td key={c.key} style={{ padding: pad, borderBottom: "1px solid var(--border)", textAlign: c.align ?? "left",
                                           fontFamily: c.mono || c.align === "right" ? "var(--font-mono)" : undefined,
                                           fontSize: c.mono || c.align === "right" ? "var(--fs-caption)" : undefined,
                                           verticalAlign: "top", whiteSpace: c.align === "right" || c.mono ? "nowrap" : undefined }}>
                    {c.render ? c.render(r) : fmtCell(r[c.key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Generic cell rendering for pass-through rows (source records, failing records). */
export function fmtCell(v: unknown): React.ReactNode {
  if (v === null || v === undefined || v === "") return <span style={{ color: "var(--fg-3)" }}>—</span>;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (typeof v === "object") return <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>{JSON.stringify(v)}</span>;
  const s = String(v);
  return s.length > 140 ? `${s.slice(0, 140)}…` : s;
}

/** Table over arbitrary rows: columns from the first row (or `keys`). */
export function RowsTable({ rows, keys, maxHeight = 320, empty }: { rows: Row[]; keys?: string[]; maxHeight?: number; empty?: React.ReactNode }) {
  const cols = (keys ?? (rows[0] ? Object.keys(rows[0]) : [])).map((k) => ({ key: k, label: k.replace(/_/g, " "),
    align: (rows.some((r) => typeof r[k] === "number") ? "right" : "left") as "right" | "left" }));
  return <DataTable columns={cols} rows={rows} maxHeight={maxHeight} empty={empty} dense />;
}

// ── Key/value, code, links ──────────────────────────────────────────────────
export function KV({ items, cols = 2 }: { items: [React.ReactNode, React.ReactNode][]; cols?: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, max-content minmax(0, 1fr))`, gap: "6px 14px", fontSize: "var(--fs-body-sm)" }}>
      {items.map(([k, v], i) => (
        <React.Fragment key={i}>
          <div style={{ ...monoCaption, textTransform: "uppercase", paddingTop: 2 }}>{k}</div>
          <div style={{ color: "var(--fg-1)", wordBreak: "break-word" }}>{v ?? <span style={{ color: "var(--fg-3)" }}>—</span>}</div>
        </React.Fragment>
      ))}
    </div>
  );
}

export function CodeBlock({ code, maxHeight = 320, label }: { code: string; maxHeight?: number; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: "relative", border: "1px solid var(--border-dark)", borderRadius: "var(--radius-md)", background: "var(--bg-inverse-deep)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px",
                    borderBottom: "1px solid var(--border-dark)" }}>
        <span style={{ ...monoCaption, color: "var(--db-navy-300)" }}>{label ?? "code"}</span>
        <button onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
                style={{ ...linkBtn, color: "var(--db-navy-300)", fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>
          {copied ? "copied" : "copy"}
        </button>
      </div>
      <pre style={{ margin: 0, padding: "10px 12px", maxHeight, overflow: "auto", color: "var(--fg-on-dark)",
                    fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.5, whiteSpace: "pre" }}>{code}</pre>
    </div>
  );
}

export function fillLink(tpl: string | undefined, vars: Record<string, string | number | null | undefined>): string | null {
  if (!tpl) return null;
  let out = tpl;
  for (const [k, v] of Object.entries(vars)) {
    if (v === null || v === undefined || v === "") return null;
    out = out.replace(`{${k}}`, encodeURIComponent(String(v)).replace(/%2F/g, "/"));
  }
  return /\{[a-z_]+\}/.test(out) ? null : out;
}

/** Deep links into the workspace for the things that executed a control. */
export function runLinks(links: LinkTemplates | undefined, x: { job_id?: number | null; job_run_id?: number | null; test_update_id?: string | null; dataset?: string | null }) {
  return {
    run: fillLink(links?.job_run, { job_id: x.job_id, run_id: x.job_run_id }),
    update: fillLink(links?.pipeline_update, { update_id: x.test_update_id }),
    table: fillLink(links?.table, { table: x.dataset }),
  };
}

export function DeepLink({ href, children, title }: { href: string | null | undefined; children: React.ReactNode; title?: string }) {
  if (!href) return <span style={{ color: "var(--fg-3)" }}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" title={title}
       style={{ color: "var(--fg-link)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}>
      {children}<Icon name="external" size={12} />
    </a>
  );
}

// ── Tabs ────────────────────────────────────────────────────────────────────
export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: { id: K; label: React.ReactNode; badge?: React.ReactNode }[]; value: K; onChange: (k: K) => void }) {
  return (
    <div style={{ display: "flex", gap: "var(--space-1)", borderBottom: "1px solid var(--border)", marginBottom: "var(--space-5)" }}>
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button key={t.id} onClick={() => onChange(t.id)}
                  style={{ background: "none", border: "none", padding: "10px 14px", cursor: "pointer", fontSize: "var(--fs-body-sm)",
                           fontWeight: on ? 700 : 500, color: on ? "var(--fg-1)" : "var(--fg-2)", fontFamily: "var(--font-sans)",
                           borderBottom: on ? "2px solid var(--db-lava-600)" : "2px solid transparent", marginBottom: -1,
                           display: "inline-flex", alignItems: "center", gap: 6 }}>
            {t.label}{t.badge}
          </button>
        );
      })}
    </div>
  );
}

// ── Drawer ──────────────────────────────────────────────────────────────────
export function Drawer({ open, onClose, title, subtitle, width = 760, children, right }: {
  open: boolean; onClose: () => void; title: React.ReactNode; subtitle?: React.ReactNode; width?: number; children: React.ReactNode; right?: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(11, 32, 38, 0.32)" }} />
      <aside style={{ position: "relative", width: `min(${width}px, 96vw)`, height: "100%", background: "var(--db-oat-light)",
                      boxShadow: "var(--shadow-xl)", display: "flex", flexDirection: "column" }}>
        <header style={{ padding: "var(--space-5) var(--space-6)", borderBottom: "1px solid var(--border)", background: "var(--bg-canvas)",
                         display: "flex", gap: "var(--space-4)", alignItems: "flex-start" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: "var(--fs-h3)", fontWeight: 700 }}>{title}</div>
            {subtitle && <div style={{ marginTop: 4, color: "var(--fg-2)", fontSize: "var(--fs-body-sm)" }}>{subtitle}</div>}
          </div>
          {right}
          <button onClick={onClose} aria-label="Close" style={{ ...linkBtn, color: "var(--fg-2)" }}><Icon name="x" size={18} /></button>
        </header>
        <div style={{ flex: 1, overflow: "auto", padding: "var(--space-5) var(--space-6) var(--space-8)" }}>{children}</div>
      </aside>
    </div>,
    document.body,
  );
}

// ── Inputs ──────────────────────────────────────────────────────────────────
export function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; label?: string }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, ...monoCaption, textTransform: "uppercase" }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
              style={{ fontFamily: "var(--font-sans)", fontSize: "var(--fs-body-sm)", padding: "5px 8px", borderRadius: "var(--radius-sm)",
                       border: "1px solid var(--border-strong)", background: "var(--bg-canvas)", color: "var(--fg-1)", textTransform: "none" }}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function TextArea({ value, onChange, rows = 4, placeholder }: { value: string; onChange: (v: string) => void; rows?: number; placeholder?: string }) {
  return (
    <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={rows} placeholder={placeholder}
              style={{ width: "100%", boxSizing: "border-box", fontFamily: "var(--font-sans)", fontSize: "var(--fs-body-sm)",
                       padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-strong)",
                       background: "var(--bg-canvas)", color: "var(--fg-1)", resize: "vertical", lineHeight: 1.5 }} />
  );
}

/** Period options: active period first, then the previous 11 months. */
export function periodOptions(active: string, n = 12): { value: string; label: string }[] {
  const [y, m] = active.split("-").map(Number);
  const out = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.UTC(y, m - 1 - i, 1));
    const v = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
    out.push({ value: v, label: i === 0 ? `${v} (active close)` : v });
  }
  return out;
}

export function activePeriod(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
