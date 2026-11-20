// Bank-to-book waterfall for one bank account, drawn as the difference from the
// book balance (balances are hundreds of millions, reconciling items thousands,
// so a zero-based bar would hide every step). Navy = reconciling items within
// policy, Lava = the unexplained difference CASH-03 tests.
import React from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import type { Row } from "../types";

function fmtCcy(v: number, ccy: string): string {
  const abs = Math.abs(v);
  const s = abs >= 1e9 ? `${(abs / 1e9).toFixed(2)}B` : abs >= 1e6 ? `${(abs / 1e6).toFixed(2)}M` : abs >= 1e3 ? `${(abs / 1e3).toFixed(1)}k` : abs.toFixed(0);
  return `${v < 0 ? "-" : ""}${s} ${ccy}`;
}

interface Step { label: string; sub: string; start: number; end: number; kind: "total" | "item" | "problem"; value: number }

export function CashWaterfall({ account, width = 640, height = 280 }: { account: Row; width?: number; height?: number }) {
  const ccy = String(account.currency_code ?? "");
  const book = Number(account.book_balance ?? 0);
  const bank = account.external_balance == null ? null : Number(account.external_balance);
  const pending = Number(account.pending_items_net ?? 0);
  const unexplained = Number(account.unexplained_amount ?? 0);
  const other = Number(account.other_reconciling ?? 0);

  if (bank == null) {
    return <div style={{ padding: 16, color: "var(--fg-3)", fontSize: "var(--fs-body-sm)" }}>No bank statement received for this account in the period.</div>;
  }
  const steps: Step[] = [];
  let run = 0;
  steps.push({ label: "Book balance", sub: fmtCcy(book, ccy), start: 0, end: 0, kind: "total", value: book });
  steps.push({ label: "Pending items", sub: "within aging window", start: run, end: (run += pending), kind: "item", value: pending });
  steps.push({ label: "Timing / other", sub: "derived", start: run, end: (run += other), kind: "item", value: other });
  steps.push({ label: "Unexplained", sub: "CASH-03 tests this", start: run, end: (run += unexplained), kind: "problem", value: unexplained });
  steps.push({ label: "Bank balance", sub: fmtCcy(bank, ccy), start: run, end: run, kind: "total", value: bank });

  const m = { top: 24, right: 16, bottom: 52, left: 72 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const vals = steps.flatMap((s) => [s.start, s.end]);
  let lo = Math.min(0, ...vals);
  let hi = Math.max(0, ...vals);
  if (hi - lo < 1) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.12;
  const y = scaleLinear().domain([lo - pad, hi + pad]).range([ih, 0]).nice();
  const x = scaleBand<string>().domain(steps.map((s) => s.label)).range([0, iw]).padding(0.35);
  const ticks = y.ticks(5);

  return (
    <svg width={width} height={height} role="img" aria-label={`Bank reconciliation waterfall for ${account.bank_account}`}>
      <g transform={`translate(${m.left},${m.top})`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={0} x2={iw} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray={t === 0 ? undefined : "2 3"} />
            <text x={-8} y={y(t)} dy="0.32em" textAnchor="end" fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">
              {fmtCcy(t, "")}
            </text>
          </g>
        ))}
        <text x={-m.left + 4} y={-10} fontFamily="var(--font-mono)" fontSize={10} fill="var(--fg-3)">difference from book ({ccy})</text>
        {steps.map((s, i) => {
          const bx = x(s.label) ?? 0;
          const bw = x.bandwidth();
          const isTotal = s.kind === "total";
          const y0 = isTotal ? y(s.start) - 2 : y(Math.max(s.start, s.end));
          const h = isTotal ? 4 : Math.max(1, Math.abs(y(s.start) - y(s.end)));
          const fill = s.kind === "problem" ? (Math.abs(s.value) >= 1 ? "var(--db-lava-600)" : "var(--border-strong)")
                     : isTotal ? "var(--db-navy-800)" : "var(--db-navy-400)";
          const next = steps[i + 1];
          return (
            <g key={s.label}>
              <rect x={bx} y={y0} width={bw} height={h} fill={fill} rx={2} />
              {next && (
                <line x1={bx + bw} x2={(x(next.label) ?? 0)} y1={y(s.end)} y2={y(s.end)} stroke="var(--fg-3)" strokeDasharray="2 2" />
              )}
              {!isTotal && (
                <text x={bx + bw / 2} y={y(Math.max(s.start, s.end)) - 6} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={10}
                      fill={s.kind === "problem" && Math.abs(s.value) >= 1 ? "var(--db-lava-700)" : "var(--fg-2)"}>
                  {s.value >= 0 ? "+" : ""}{fmtCcy(s.value, "")}
                </text>
              )}
              <text x={bx + bw / 2} y={ih + 16} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--fg-1)">{s.label}</text>
              <text x={bx + bw / 2} y={ih + 30} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={9.5} fill="var(--fg-3)">{s.sub}</text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
