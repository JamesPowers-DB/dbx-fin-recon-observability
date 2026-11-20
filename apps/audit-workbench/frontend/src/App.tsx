import React, { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { getMe } from "./api";
import type { MeResponse } from "./types";
import { CloseCockpit } from "./pages/CloseCockpit";
import { AuditChecklist } from "./pages/AuditChecklist";
import { ExceptionsReview } from "./pages/ExceptionsReview";
import { ReconsTesting } from "./pages/ReconsTesting";
import { FinancialStatements } from "./pages/FinancialStatements";
import { AuditAssistant } from "./pages/AuditAssistant";
import { RiskReporting } from "./pages/RiskReporting";
import { DataQualityLineage } from "./pages/DataQualityLineage";
import { Architecture } from "./pages/Architecture";

// State-based router (no react-router). Order matches the sidebar sections.
export type PageId =
  | "close" | "checklist" | "exceptions"
  | "modules" | "statements"
  | "assistant" | "reporting"
  | "lineage" | "architecture";

export interface NavOpts {
  focusId?: string;   // deep-link payload: a control id, exception id, dataset, or line code
  tab?: string;       // sub-tab on pages with tabs (modules, statements, architecture, lineage)
  filter?: Record<string, string>;   // list filters, e.g. {module: "M3"} or {control: "JET-01"}
  context?: Record<string, unknown>; // assistant handoff, e.g. {exception_id}
}

/** Props every page receives. */
export interface PageProps {
  onNavigate: (p: PageId, opts?: NavOpts) => void;
  nav: NavOpts;
  user: MeResponse | null;
}

const PAGES: Record<PageId, (p: PageProps) => React.ReactElement> = {
  close: CloseCockpit, checklist: AuditChecklist, exceptions: ExceptionsReview, modules: ReconsTesting,
  statements: FinancialStatements, assistant: AuditAssistant, reporting: RiskReporting, lineage: DataQualityLineage,
  architecture: Architecture,
};

export default function App() {
  const [page, setPage] = useState<PageId>("close");
  const [user, setUser] = useState<MeResponse | null>(null);
  const [resolving, setResolving] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [nav, setNav] = useState<NavOpts>({});
  const [navKey, setNavKey] = useState(0);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch((e) => {
        console.error("getMe failed", e);
        setUser({ email: "user@example.com", display_name: "User", initials: "U" });
      })
      .finally(() => setResolving(false));
  }, []);

  if (resolving) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--font-mono)", fontSize: "var(--fs-body-sm)", color: "var(--fg-3)" }}>
        resolving identity…
      </div>
    );
  }

  const navigate = (p: PageId, opts?: NavOpts) => {
    setSearchQuery("");
    setNav(opts ?? {});
    setNavKey((k) => k + 1);   // remount the page so deep-link payloads apply
    setPage(p);
  };
  const Current = PAGES[page];

  return (
    <>
      <Sidebar page={page} onNavigate={(p) => navigate(p)} user={user} searchQuery={searchQuery} onSearch={setSearchQuery} />
      <main style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
        <Current key={`${page}-${navKey}`} onNavigate={navigate} nav={nav} user={user} />
      </main>
    </>
  );
}
