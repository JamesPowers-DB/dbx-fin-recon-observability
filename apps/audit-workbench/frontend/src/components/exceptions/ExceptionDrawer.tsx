// One exception, end to end: what the control found, the AI triage, the source
// records behind it, the evidence pack, the review trail, the working paper and
// the four-eyes review actions. Review actions are written to Lakebase and
// applied to control results by the next run_controls run.
import React, { useState } from "react";
import { ApiError, actOnException, evidenceDocumentUrl, getException, saveWorkingPaper } from "../../api";
import type { ExceptionDetail, ExceptionRow, MeResponse, Row } from "../../types";
import type { NavOpts, PageId } from "../../App";
import {
  AiBadge, Async, DataTable, Drawer, EmptyNote, KV, Mono, Notice, RowsTable, Section, Select, Stack, StatusBadge, Tabs, TextArea,
  linkBtn, monoCaption, useApi,
} from "../ui";
import { PrimaryBtn, SecondaryBtn, Pill } from "../Buttons";
import { Icon } from "../Icon";
import { Markdown } from "../Markdown";
import { fmtDate, fmtInt, fmtUSD } from "../../format";
import {
  ACTION_LABEL, DISPOSITIONS, DISPOSITION_LABEL, MODULE_LABEL, ROOT_CAUSE_LABEL, SOURCE_LABEL, SOURCE_TABLE_LABEL, shortId,
} from "./labels";

type TabId = "overview" | "source" | "evidence" | "trail" | "paper";

export function ExceptionDrawer({ exceptionId, onClose, user, onNavigate, onChanged }: {
  exceptionId: string | null; onClose: () => void; user: MeResponse | null;
  onNavigate: (p: PageId, o?: NavOpts) => void; onChanged: () => void;
}) {
  if (!exceptionId) return null;
  return <DrawerBody key={exceptionId} id={exceptionId} onClose={onClose} user={user} onNavigate={onNavigate} onChanged={onChanged} />;
}

function DrawerBody({ id, onClose, user, onNavigate, onChanged }: {
  id: string; onClose: () => void; user: MeResponse | null; onNavigate: (p: PageId, o?: NavOpts) => void; onChanged: () => void;
}) {
  const st = useApi(() => getException(id), [id]);
  const [tab, setTab] = useState<TabId>("overview");
  const x = st.data?.exception;
  const title = x ? <span><Mono style={{ fontSize: "var(--fs-h4)" }}>{x.control_id}</Mono> {x.control_title}</span> : `Exception ${shortId(id)}`;
  const subtitle = x ? (
    <span>
      {MODULE_LABEL[x.module] ?? x.module} · {x.entity_code} · {x.period} · <Mono dim>{x.record_key}</Mono>
    </span>
  ) : "Loading the exception, its source records and its evidence.";
  return (
    <Drawer open onClose={onClose} title={title} subtitle={subtitle} width={860}
            right={x && (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <StatusBadge status={x.disposition_status} />
                <SecondaryBtn onClick={() => onNavigate("assistant", { context: { exception_id: x.exception_id } })}>
                  <Icon name="bot" size={14} /> Investigate with the assistant
                </SecondaryBtn>
              </div>
            )}>
      <Async state={st}>
        {(d) => (
          <Stack gap="var(--space-5)">
            <ReviewPanel d={d} user={user} onDone={() => { st.reload(); onChanged(); }} onNavigate={onNavigate} />
            <div>
              <Tabs<TabId>
                value={tab} onChange={setTab}
                tabs={[
                  { id: "overview", label: "Overview" },
                  { id: "source", label: "Source records", badge: <Mono dim>{Object.values(d.source_records).reduce((n, r) => n + r.length, 0)}</Mono> },
                  { id: "evidence", label: "Evidence", badge: <Mono dim>{d.evidence.length}</Mono> },
                  { id: "trail", label: "Review trail", badge: <Mono dim>{d.timeline.length}</Mono> },
                  { id: "paper", label: "Working paper", badge: d.working_paper ? <Icon name="doc" size={12} /> : undefined },
                ]} />
              {tab === "overview" && <Overview d={d} onNavigate={onNavigate} />}
              {tab === "source" && <SourceRecords d={d} />}
              {tab === "evidence" && <Evidence d={d} />}
              {tab === "trail" && <Trail d={d} />}
              {tab === "paper" && <WorkingPaper d={d} onSaved={st.reload} />}
            </div>
          </Stack>
        )}
      </Async>
    </Drawer>
  );
}

// ── Four-eyes review actions ────────────────────────────────────────────────
function ReviewPanel({ d, user, onDone, onNavigate }: {
  d: ExceptionDetail; user: MeResponse | null; onDone: () => void; onNavigate: (p: PageId, o?: NavOpts) => void;
}) {
  const s = d.state as Row;
  const status: string = s.disposition_status ?? "open";
  const [disp, setDisp] = useState(DISPOSITIONS[0].value);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ status: number; message: string } | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const me = (user?.email ?? "").toLowerCase();
  const iProposed = status === "proposed" && (s.proposed_by ?? "").toLowerCase() === me && me !== "";

  const run = async (action: "propose" | "approve" | "reject" | "reopen") => {
    setBusy(true); setErr(null); setOk(null);
    try {
      await actOnException(d.exception.exception_id, {
        action, disposition: action === "propose" ? disp : undefined, comment,
        role: action === "propose" ? "preparer" : "reviewer",
      });
      setOk(`${ACTION_LABEL[action] ?? action} recorded in the review store.`);
      setComment("");
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? { status: e.status, message: e.message } : { status: 0, message: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section eyebrow="Human review · four-eyes" title={reviewTitle(status)}
             right={d.exception.pending_sync || d.timeline.some((t) => t.pending_sync)
               ? <StatusBadge status="RUNNING" label="Pending sync" small /> : undefined}>
      <Stack gap="var(--space-3)">
        {status === "proposed" && (
          <div style={{ fontSize: "var(--fs-body-sm)" }}>
            <b>{s.proposed_by}</b> proposed <StatusBadge status="proposed" label={DISPOSITION_LABEL[s.disposition] ?? s.disposition ?? "a disposition"} small />
            {s.proposed_at && <Mono dim> · {fmtTime(s.proposed_at)}</Mono>}
            {s.comment && <div style={{ marginTop: 6, color: "var(--fg-2)" }}>“{s.comment}”</div>}
          </div>
        )}
        {status === "approved" && (
          <div style={{ fontSize: "var(--fs-body-sm)" }}>
            Disposition <b>{DISPOSITION_LABEL[s.disposition] ?? s.disposition ?? "—"}</b> proposed by {s.proposed_by ?? "—"},
            approved by <b>{s.approved_by ?? "—"}</b>{s.approved_at && <Mono dim> · {fmtTime(s.approved_at)}</Mono>}.
          </div>
        )}
        {status === "rejected" && (
          <div style={{ fontSize: "var(--fs-body-sm)" }}>
            Rejected by <b>{s.rejected_by ?? "—"}</b>{s.comment && <>: “{s.comment}”</>}. A new disposition can be proposed.
          </div>
        )}

        {(status === "open" || status === "rejected") && (
          <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 10, alignItems: "start" }}>
            <div>
              <Select label="Disposition" value={disp} onChange={setDisp} options={DISPOSITIONS.map((o) => ({ value: o.value, label: o.label }))} />
              <div style={{ ...monoCaption, marginTop: 6 }}>{DISPOSITIONS.find((o) => o.value === disp)?.hint}</div>
            </div>
            <TextArea value={comment} onChange={setComment} rows={2} placeholder="Basis for the disposition (what you checked, what evidence supports it)" />
          </div>
        )}
        {status === "proposed" && (
          <TextArea value={comment} onChange={setComment} rows={2} placeholder="Reviewer comment (optional for approval, expected for rejection)" />
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {(status === "open" || status === "rejected") && (
            <PrimaryBtn disabled={busy} onClick={() => run("propose")}><Icon name="send" size={14} /> Propose disposition</PrimaryBtn>
          )}
          {status === "proposed" && (
            <>
              <PrimaryBtn disabled={busy} onClick={() => run("approve")}><Icon name="check" size={14} /> Approve</PrimaryBtn>
              <SecondaryBtn disabled={busy} onClick={() => run("reject")}><Icon name="x" size={14} /> Reject</SecondaryBtn>
            </>
          )}
          {status === "approved" && <SecondaryBtn disabled={busy} onClick={() => run("reopen")}>Reopen</SecondaryBtn>}
          <span style={monoCaption}>
            {iProposed ? "You proposed this disposition. An independent reviewer must approve it."
              : status === "proposed" ? "The proposer cannot approve their own disposition (enforced server-side)."
              : "A preparer proposes; a different person approves."}
          </span>
        </div>

        {err && (
          <Notice kind="danger" onClose={() => setErr(null)}>
            {err.status ? <Mono dim>HTTP {err.status} · </Mono> : null}{err.message}
          </Notice>
        )}
        {ok && (
          <Notice kind="success" onClose={() => setOk(null)}>
            {ok} Applied to control results on the next control run.{" "}
            <button style={linkBtn} onClick={() => onNavigate("close")}>Re-run controls on the Close Cockpit</button>
          </Notice>
        )}
      </Stack>
    </Section>
  );
}

function reviewTitle(status: string): string {
  switch (status) {
    case "proposed": return "Disposition awaiting independent approval";
    case "approved": return "Dispositioned";
    case "rejected": return "Proposal rejected";
    default: return "No disposition yet";
  }
}

// ── Overview: facts, AI triage, control ─────────────────────────────────────
function Overview({ d, onNavigate }: { d: ExceptionDetail; onNavigate: (p: PageId, o?: NavOpts) => void }) {
  const x = d.exception;
  const c = d.control ?? {};
  return (
    <Stack gap="var(--space-5)">
      <Section eyebrow="What the control found" title={x.detected_value}>
        <KV cols={2} items={[
          ["Amount (USD)", fmtUSD(x.amount_usd)],
          ["Entity", `${x.entity_code} · ${x.region}`],
          ["Period", x.period],
          ["Item date", fmtDate(x.item_date)],
          ["Age", x.age_bd == null ? "—" : x.age_bd < 0 ? `${Math.abs(x.age_bd)} business days before month end` : `${x.age_bd} business days`],
          ["Record type", x.record_type.replace(/_/g, " ")],
          ["Record key", <Mono key="k">{x.record_key}</Mono>],
          ["Rule severity", <StatusBadge key="s" status={x.rule_severity} small />],
          ["Key control", x.key_control ? "yes" : "no"],
          ["Lane", x.lane === "assurance" ? "Independent assurance" : "Management monitoring"],
          ["Lineage keys", <Mono key="l">{x.lineage ? Object.entries(x.lineage).map(([k, v]) => `${k}=${v}`).join("  ") : "—"}</Mono>],
          ["Exception id", <Mono key="i" dim>{x.exception_id}</Mono>],
        ]} />
        {x.is_info && <div style={{ ...monoCaption, marginTop: 10 }}>INFO control: a KRI-style signal with no tolerance. It does not fail the control.</div>}
      </Section>

      <TriageCard x={x} />

      <Section eyebrow="Control" title={<span><Mono>{String(c.control_id ?? x.control_id)}</Mono> v{String(c.version ?? "")} · {String(c.title ?? x.control_title)}</span>}
               right={<button style={linkBtn} onClick={() => onNavigate("checklist", { focusId: x.control_id })}>Open in the checklist</button>}>
        <Stack gap="var(--space-3)">
          <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-2)" }}>{String(c.objective ?? "")}</div>
          <KV cols={2} items={[
            ["Owner", c.owner_role],
            ["Frequency", c.frequency],
            ["Tolerance", c.max_exceptions == null ? "INFO (no tolerance)" : `≤ ${fmtInt(c.max_exceptions)} exceptions${c.max_amount_usd != null ? ` and ≤ ${fmtUSD(c.max_amount_usd)}` : ""}`],
            ["Executed by", [c.executed_by_kind, c.executed_by_expectation || c.executed_by_dataset || c.executed_by_task].filter(Boolean).join(" · ")],
            ["Assertions", Array.isArray(c.assertions) ? c.assertions.join(", ") : c.assertions],
            ["Risks", Array.isArray(c.risk_ids) ? c.risk_ids.join(", ") : c.risk_ids],
          ]} />
          {c.clause_text && (
            <div style={{ borderLeft: "3px solid var(--db-navy-400)", padding: "4px 12px", fontSize: "var(--fs-body-sm)", color: "var(--fg-2)" }}>
              <Mono dim>{String(c.policy_ref ?? x.policy_ref ?? "")}</Mono>
              <div style={{ marginTop: 4 }}>{String(c.clause_text)}</div>
            </div>
          )}
        </Stack>
      </Section>
    </Stack>
  );
}

function TriageCard({ x }: { x: ExceptionRow }) {
  if (!x.ai_severity && !x.ai_root_cause) {
    return (
      <Section eyebrow="AI investigation" title="Not triaged yet" right={<AiBadge />}>
        <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-2)" }}>
          The triage_exceptions task of run_controls triages new exceptions on every control run (capped per run). This one is queued for the next run.
        </div>
      </Section>
    );
  }
  return (
    <Section eyebrow="AI investigation" title="AI triage" right={<AiBadge model={x.ai_model} text={`AI-generated · ${x.ai_model ?? "model"}`} />}
             style={{ borderColor: "var(--db-navy-400)" }}>
      <Stack gap="var(--space-3)">
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <StatusBadge status={x.ai_severity} label={`Severity: ${x.ai_severity ?? "—"}`} />
          <Pill>{ROOT_CAUSE_LABEL[x.ai_root_cause ?? ""] ?? x.ai_root_cause ?? "—"}</Pill>
          <Mono dim>confidence {x.ai_confidence == null ? "—" : `${Math.round(x.ai_confidence * 100)}%`}</Mono>
          {x.needs_human && <Mono dim>· human decision required</Mono>}
        </div>
        {x.ai_rationale && <Field label="Rationale">{x.ai_rationale}</Field>}
        {x.ai_recommended_action && <Field label="Recommended action">{x.ai_recommended_action}</Field>}
        {x.ai_draft_finding && <Field label="Draft finding">{x.ai_draft_finding}</Field>}
        <div style={monoCaption}>
          {x.ai_triaged_at ? `Triaged ${fmtTime(x.ai_triaged_at)}` : ""}{x.ai_prompt_version ? ` · prompt ${x.ai_prompt_version}` : ""} · ai_query in run_controls. A human disposition is still required.
        </div>
      </Stack>
    </Section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: "var(--fs-body-sm)", lineHeight: 1.5 }}>{children}</div>
    </div>
  );
}

// ── Source records ──────────────────────────────────────────────────────────
function SourceRecords({ d }: { d: ExceptionDetail }) {
  const keys = Object.keys(d.source_records);
  const [k, setK] = useState(keys[0] ?? "");
  if (!keys.length) {
    return (
      <EmptyNote>
        No source table is linked for record type “{d.exception.record_type.replace(/_/g, " ")}”. Lineage keys on the exception:{" "}
        <Mono>{JSON.stringify(d.exception.lineage ?? {})}</Mono>
      </EmptyNote>
    );
  }
  return (
    <Stack gap="var(--space-3)">
      <div style={{ ...monoCaption }}>Followed from the exception's lineage keys back to the rows the control tested.</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {keys.map((key) => (
          <Pill key={key} active={key === k} onClick={() => setK(key)}>
            {SOURCE_TABLE_LABEL[key] ?? key} · {d.source_records[key].length}
          </Pill>
        ))}
      </div>
      <RowsTable rows={d.source_records[k] ?? []} maxHeight={420} empty="No rows resolved for this lineage key." />
    </Stack>
  );
}

// ── Evidence pack ───────────────────────────────────────────────────────────
function Evidence({ d }: { d: ExceptionDetail }) {
  const x = d.exception;
  const docs = d.evidence.filter((e) => e.evidence_type === "document");
  const pols = d.evidence.filter((e) => e.evidence_type !== "document");
  return (
    <Stack gap="var(--space-4)">
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <StatusBadge status={x.requires_evidence ? (x.has_document_evidence ? "PASS" : "FAIL") : "INFO"}
                     label={x.requires_evidence ? (x.has_document_evidence ? "Required document on file" : "Required document missing") : "No document required"} />
        <span style={monoCaption}>Documents parsed in the pipeline with ai_parse_document and matched to the record by reference, party and amount.</span>
      </div>
      {docs.length === 0 && <EmptyNote>No parsed document is linked to this exception.</EmptyNote>}
      {docs.map((e, i) => <DocCard key={i} e={e} />)}
      {pols.map((e, i) => (
        <Section key={`p${i}`} eyebrow={`Policy · ${e.evidence_subtype ?? ""}`} title={<Mono>{String(e.evidence_ref ?? "")}</Mono>}>
          <div style={{ fontSize: "var(--fs-body-sm)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{String(e.evidence_text ?? "")}</div>
        </Section>
      ))}
    </Stack>
  );
}

function DocCard({ e }: { e: Row }) {
  const [full, setFull] = useState(false);
  const text = String(e.evidence_text ?? "");
  const kind = e.evidence_subtype === "invoices" ? "Supplier invoice" : e.evidence_subtype === "bank_advices" ? "Bank advice" : String(e.evidence_subtype ?? "Document");
  return (
    <Section eyebrow={`${kind} · parsed`} title={<Mono>{String(e.evidence_ref ?? "")}</Mono>}
             right={e.evidence_path ? (
               <a href={evidenceDocumentUrl(String(e.evidence_path))} target="_blank" rel="noreferrer"
                  style={{ ...linkBtn, display: "inline-flex", alignItems: "center", gap: 4, textDecoration: "none" }}>
                 <Icon name="doc" size={14} /> Open PDF
               </a>
             ) : undefined}>
      <Stack gap="var(--space-3)">
        <KV cols={2} items={[["Party", e.evidence_party], ["Amount", e.evidence_amount == null ? "—" : fmtUSD(Number(e.evidence_amount))]]} />
        <pre style={{ margin: 0, padding: 10, background: "var(--bg-subtle)", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-mono)",
                      fontSize: 12, whiteSpace: "pre-wrap", maxHeight: full ? undefined : 160, overflow: "hidden" }}>{text}</pre>
        {text.length > 400 && <button style={linkBtn} onClick={() => setFull(!full)}>{full ? "Show less" : "Show full extracted text"}</button>}
      </Stack>
    </Section>
  );
}

// ── Review trail ────────────────────────────────────────────────────────────
function Trail({ d }: { d: ExceptionDetail }) {
  return (
    <Stack gap="var(--space-5)">
      <Section eyebrow="Review timeline" title="Who did what, when">
        {d.timeline.length === 0 ? <EmptyNote>No review actions yet.</EmptyNote> : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {d.timeline.map((t, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "14px 1fr", gap: 10, paddingBottom: 12 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%", marginTop: 4,
                                 background: t.action === "approve" ? "var(--success)" : t.action === "reject" ? "var(--danger)" : "var(--db-navy-400)" }} />
                  {i < d.timeline.length - 1 && <span style={{ flex: 1, width: 1, background: "var(--border)", marginTop: 2 }} />}
                </div>
                <div>
                  <div style={{ fontSize: "var(--fs-body-sm)" }}>
                    <b>{ACTION_LABEL[t.action] ?? t.action}</b>
                    {t.disposition && <> · {DISPOSITION_LABEL[t.disposition] ?? t.disposition}</>} by {t.actor_email}
                    <Mono dim> ({t.actor_role})</Mono>
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 2 }}>
                    <Mono dim>{fmtTime(t.acted_at)}</Mono>
                    <Mono dim>· {SOURCE_LABEL[t.source] ?? t.source}</Mono>
                    {t.pending_sync && <StatusBadge status="RUNNING" label="Pending sync" small />}
                  </div>
                  {t.comment && <div style={{ marginTop: 4, fontSize: "var(--fs-body-sm)", color: "var(--fg-2)" }}>{t.comment}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section eyebrow="Run log" title="Status in each control run">
        <DataTable dense rows={d.run_log} rowKey={(r) => String(r.job_run_id)}
                   empty="Not logged by a control run yet."
                   columns={[
                     { key: "job_run_id", label: "Job run", mono: true },
                     { key: "change", label: "Change", render: (r) => <StatusBadge status={String(r.change)} small /> },
                     { key: "logged_at", label: "Logged", mono: true, render: (r) => fmtTime(r.logged_at) },
                   ]} />
        <div style={{ ...monoCaption, marginTop: 8 }}>
          NEW: first seen in that run. RECURRING: still present. RESOLVED: no longer produced by the control test. BASELINE: present at the first run.
        </div>
      </Section>
    </Stack>
  );
}

// ── Working paper ───────────────────────────────────────────────────────────
function WorkingPaper({ d, onSaved }: { d: ExceptionDetail; onSaved: () => void }) {
  const x = d.exception;
  const wp = d.working_paper;
  const [title, setTitle] = useState(wp?.title ?? `${x.control_id} · ${x.entity_code} · ${x.period}: working paper`);
  const [body, setBody] = useState(wp?.body_md ?? "");
  const [aiDraft, setAiDraft] = useState<string | null>(wp?.ai_draft_md ?? null);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "success" | "danger"; text: string } | null>(null);

  const insertDraft = () => {
    const md = [
      "## Finding (AI draft, review before use)",
      x.ai_draft_finding ?? "_No AI finding available for this exception._",
      "",
      "## Recommended action",
      x.ai_recommended_action ?? "_To be completed._",
      "",
      "## Facts",
      `- Control: ${x.control_id} ${x.control_title}`,
      `- Entity and period: ${x.entity_code}, ${x.period}`,
      `- Amount: ${fmtUSD(x.amount_usd)}`,
      `- Detected: ${x.detected_value}`,
      `- Record: ${x.record_key}`,
      "",
      "## Reviewer conclusion",
      "_To be completed by the reviewer._",
    ].join("\n");
    setAiDraft(md);
    setBody(body.trim() ? `${body}\n\n${md}` : md);
  };

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      await saveWorkingPaper(x.exception_id, { title, body_md: body, ai_draft_md: aiDraft });
      setMsg({ kind: "success", text: "Working paper saved to the review store." });
      onSaved();
    } catch (e) {
      setMsg({ kind: "danger", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section eyebrow="Working paper" title="Documentation of the review"
             right={<>
               {aiDraft && <AiBadge text="Includes AI draft" />}
               <SecondaryBtn onClick={insertDraft} disabled={!x.ai_draft_finding}><Icon name="spark" size={14} /> Insert AI draft</SecondaryBtn>
               <SecondaryBtn onClick={() => setPreview(!preview)}>{preview ? "Edit" : "Preview"}</SecondaryBtn>
             </>}>
      <Stack gap="var(--space-3)">
        {wp && <div style={monoCaption}>Last saved by {wp.author_email} · {fmtTime(wp.updated_at)}</div>}
        <input value={title} onChange={(e) => setTitle(e.target.value)}
               style={{ fontFamily: "var(--font-sans)", fontSize: "var(--fs-body-sm)", fontWeight: 600, padding: "8px 10px",
                        borderRadius: "var(--radius-sm)", border: "1px solid var(--border-strong)", background: "var(--bg-canvas)" }} />
        {preview
          ? <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: 12, minHeight: 200, background: "var(--bg-canvas)" }}>
              {body.trim() ? <Markdown text={body} /> : <span style={monoCaption}>Nothing written yet.</span>}
            </div>
          : <TextArea value={body} onChange={setBody} rows={14} placeholder="Procedures performed, evidence inspected, conclusion. Markdown supported." />}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <PrimaryBtn onClick={save} disabled={busy || !body.trim()}>Save working paper</PrimaryBtn>
          <span style={monoCaption}>Stored in Lakebase with the author. AI text stays labelled until a reviewer edits it.</span>
        </div>
        {msg && <Notice kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      </Stack>
    </Section>
  );
}

export function fmtTime(v: unknown): string {
  if (!v) return "—";
  const s = String(v).replace("T", " ");
  return s.slice(0, 16);
}
