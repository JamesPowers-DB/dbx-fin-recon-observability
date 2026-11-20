# Databricks notebook source
# MAGIC %md
# MAGIC # 10: evidence documents (PDF)
# MAGIC
# MAGIC | Folder | Documents | Control |
# MAGIC |---|---|---|
# MAGIC | `docs/invoices/` | Supplier invoices for AP invoices >= $750k in the rolling evidence window (prior + active period) | SLR-05 |
# MAGIC | `docs/bank_advices/` | Bank advices for bank-only reconciling items | CASH-04 |
# MAGIC | `docs/policies/` | POL-FC-01 Financial Close and Reconciliation Policy (one section per control family) | triage + agent |
# MAGIC
# MAGIC Planted (SLR-05):
# MAGIC * two large invoices with no document;
# MAGIC * two documents whose amount disagrees with the AP record (transposed digits);
# MAGIC * one document issued by a different supplier.
# MAGIC
# MAGIC The unidentified incoming wire gets no bank advice (CASH-04, planted by 07).

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
from fpdf import FPDF

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
DOCS = volume_dir(catalog, schema, raw_volume, "docs")
for sub in ("invoices", "bank_advices", "policies"):
    wipe_family(f"{DOCS}/{sub}", "")
planted = PlantedRegistry("10_documents_pdfs")
rng = rng_for("documents")
EVIDENCE_THRESHOLD_USD = 750_000
ap = read_scratch(catalog, schema, raw_volume, "ap_invoices")
suppliers = read_scratch(catalog, schema, raw_volume, "suppliers")
bank = read_scratch(catalog, schema, raw_volume, "bank_entries")


def pdf_doc(path, title, lines, footer=None):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    for ln in lines:
        if ln.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, ln[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=11)
        else:
            pdf.multi_cell(0, 6, ln, new_x="LMARGIN", new_y="NEXT")
    if footer:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, footer, new_x="LMARGIN", new_y="NEXT")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pdf.output(path)

# COMMAND ----------
# MAGIC %md ## Supplier invoices (SLR-05 evidence window)

# COMMAND ----------
win = (ap.filter(~pl.col("_opening"))
         .with_columns(pl.col("gl_date").dt.strftime("%Y-%m").alias("period"))
         .filter(pl.col("period").is_in([period_key(py, pm), ACTIVE])))
win = win.with_columns(pl.struct(["_entity", "gl_date", "invoice_amount"]).map_elements(
    lambda s: s["invoice_amount"] * entity_rate(s["_entity"], s["gl_date"]), return_dtype=pl.Float64).alias("usd"))
big = win.filter(pl.col("usd") >= EVIDENCE_THRESHOLD_USD).sort(["gl_date", "invoice_id"])
act_big = big.filter(pl.col("period") == ACTIVE)
ids = act_big["invoice_id"].to_list()
missing = set(ids[:2])
amount_mismatch = set(ids[2:4])
vendor_mismatch = set(ids[4:5])
other_vendor = suppliers.filter(pl.col("vendor_type_lookup_code") == "gna_services")["vendor_name"].to_list()
n_inv = 0
for r in big.iter_rows(named=True):
    iid = r["invoice_id"]
    if iid in missing:
        planted.add("M2", "SLR-05", str(iid), r["_entity"], r["period"], r["usd"],
                    f"No supplier invoice document on file for AP invoice {r['invoice_num']} (USD {r['usd']:,.0f})")
        continue
    amount = r["invoice_amount"]
    vendor = r["vendor_name"]
    if iid in amount_mismatch:
        s = f"{amount:.2f}"
        digits = s.replace(".", "")
        swapped = digits[:1] + digits[2] + digits[1] + digits[3:] if len(digits) > 3 and digits[1] != digits[2] else str(int(digits) + 9900)
        amount = float(swapped[:-2] + "." + swapped[-2:])
        planted.add("M2", "SLR-05", str(iid), r["_entity"], r["period"], abs(r["invoice_amount"] - amount) * entity_rate(r["_entity"], r["gl_date"]),
                    f"Document amount {amount:,.2f} disagrees with AP record {r['invoice_amount']:,.2f} for {r['invoice_num']}")
    if iid in vendor_mismatch:
        vendor = other_vendor[int(rng.integers(0, len(other_vendor)))]
        planted.add("M2", "SLR-05", str(iid), r["_entity"], r["period"], r["usd"],
                    f"Document for {r['invoice_num']} is issued by {vendor}, not the AP supplier {r['vendor_name']}")
    ent = ENTITY_BY_CODE[r["_entity"]]
    pdf_doc(f"{DOCS}/invoices/{r['invoice_num']}.pdf", "INVOICE", [
        vendor,
        f"Invoice number: {r['invoice_num']}",
        f"Invoice date: {r['invoice_date']}",
        f"Bill to: {ent['name']} ({r['_entity']})",
        f"Description: {r['description']}",
        f"Payment terms: {r['terms_name']}",
        f"Currency: {r['invoice_currency_code']}",
        f"Amount due: {r['invoice_currency_code']} {amount:,.2f}",
        f"Supplier reference: AP-{iid}",
    ], footer="Fictional document generated for a demo. Corvane Technologies is not a real company.")
    n_inv += 1
print(f"invoice documents={n_inv} (window rows={big.height}; missing={len(missing)})")

# COMMAND ----------
# MAGIC %md ## Bank advices for bank-only items

# COMMAND ----------
n_adv = 0
for r in bank.filter(pl.col("kind").is_in(["bank_only_fee", "bank_only_payroll", "bank_only_prev_interest"])).iter_rows(named=True):
    ent = ENTITY_BY_CODE[r["account"][:4]]
    ccy = ent["currency"]
    kind = {"bank_only_fee": "Bank charge advice", "bank_only_payroll": "Debit advice: payroll file",
            "bank_only_prev_interest": "Credit advice: sweep interest"}[r["kind"]]
    pdf_doc(f"{DOCS}/bank_advices/ADV-{r['ref']}.pdf", kind.upper(), [
        ent["bank"],
        f"Account: {r['account']}",
        f"Advice reference: {r['ref']}",
        f"Booking date: {r['book_date']}",
        f"Amount: {ccy} {abs(r['amount']):,.2f} {'credit' if r['amount'] > 0 else 'debit'}",
        f"Details: {r['info']}",
    ], footer="Fictional bank advice generated for a demo.")
    n_adv += 1
print(f"bank advices={n_adv}")

# COMMAND ----------
# MAGIC %md ## Policy: POL-FC-01 Financial Close and Reconciliation Policy

# COMMAND ----------
POLICY = [
    "Policy owner: Corporate Controller. Applies to all Corvane Technologies entities. Version 4.2.",
    "## 1 Purpose and scope",
    "1.1 This policy sets the controls that support accurate, complete and timely financial reporting at each month end, and the evidence needed to show each control operated.",
    "1.2 Controls are monitored continuously by automated tests on full populations. A control is effective for a period when its automated test passes or every exception has an approved disposition.",
    "## 2 Cash reconciliation (CASH-01 to CASH-04)",
    "2.1 Bank statements must be received for every business day. A missing statement must be escalated to Treasury within one business day.",
    "2.2 Every bank transaction must match a book entry with the same amount and reference within five calendar days. Unmatched items open longer than five business days are exceptions.",
    "2.3 The unexplained difference between book and bank for each account and month must not exceed USD 1.00 equivalent.",
    "2.4 Reconciling items older than five business days must be supported by a bank advice showing the same reference and amount.",
    "## 3 Subledger reconciliation (SLR-01 to SLR-05)",
    "3.1 The AP, AR and payroll subledgers must agree to their GL control accounts per entity and month within the greater of 0.1% and USD 1,000.",
    "3.2 Manual journals must not be posted to subledger control accounts (20000, 11000, 22000). Corrections are made in the subledger.",
    "3.3 AP invoices of USD 750,000 or more require a supplier invoice document whose supplier and amount agree with the AP record.",
    "## 4 Journal entries (JET-01 to JET-05)",
    "4.1 The preparer of a manual journal may not approve it.",
    "4.2 Manual journals above USD 250,000 must be approved before posting.",
    "4.3 Manual journals posted on weekends or between 21:00 and 06:00 local time by people (not system accounts) are reviewed by the Controller.",
    "4.4 Potential duplicate journals (same account and amount within three days) are investigated before close.",
    "4.5 Statistical outliers (round amounts, unusual size, Benford deviation by preparer) are monitored as key risk indicators.",
    "## 5 Access to financial systems (PAM-01 to PAM-04)",
    "5.1 No user may hold conflicting roles: journal entry with journal approval; invoice entry with payment release; supplier maintenance with payment release.",
    "5.2 ERP access must be removed within one business day of the HR termination date.",
    "5.3 Terminated users must not post transactions after their termination date.",
    "5.4 Privileged roles require an approved access request before assignment.",
    "## 6 Financial statements and flux review (FSC-01 to FSC-04, FPA-01 to FPA-04)",
    "6.1 The trial balance must balance, the balance sheet must balance, cash on the cash flow statement must agree to the balance sheet, and net income must roll into retained earnings.",
    "6.2 Variances to budget greater than both USD 250,000 and 10% of budget at entity and statement-line level are material and must be explained by the Controller within five business days of identification.",
    "6.3 Each explanation must be acknowledged by a reviewer who is not its author.",
    "## 7 Data quality (DQ-01 to DQ-03)",
    "7.1 Source feeds must arrive within their service level (one business day for ERP, CRM and bank feeds).",
    "7.2 Unexpected source schema changes must be detected and triaged before close.",
    "7.3 Every journal line must use an account and entity defined in the chart of accounts.",
    "## 8 Close calendar and sign-off",
    "8.1 The close calendar defines each close task, its owner, due day and the controls that evidence it. The Controller signs GO when every task is complete.",
    "8.2 Exceptions are dispositioned as explained, adjusted, remediated, false positive or deficiency. Deficiencies are reported to Internal Audit.",
]
pdf_doc(f"{DOCS}/policies/POL-FC-01.pdf", "POL-FC-01 Financial Close and Reconciliation Policy", POLICY,
        footer="Fictional policy for a demo company.")
planted.save(spark, catalog, schema)
print("policy written")
