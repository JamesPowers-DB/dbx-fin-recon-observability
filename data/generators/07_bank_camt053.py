# Databricks notebook source
# MAGIC %md
# MAGIC # 07: bank feed, ISO 20022 camt.053 (XML)
# MAGIC
# MAGIC `bank/camt053_<account>_<YYYYMM>.xml`: one file per bank account per month,
# MAGIC one `<Stmt>` per business day with OPBD/CLBD balances and `<Ntry>` entries.
# MAGIC Two accounts per entity: `<ENT>-OPS-0001` (GL 10100) and `<ENT>-PAY-0001`
# MAGIC (GL 10200), in the entity's functional currency.
# MAGIC
# MAGIC Entries mirror what the book recorded, with realistic clearing:
# MAGIC * receipts, payroll, tax, interest, and fees book on the same day;
# MAGIC * supplier payments clear 1 to 2 business days after the check date, so some
# MAGIC   are outstanding at month end (timing, not exceptions).
# MAGIC
# MAGIC Planted (M1), bank-only items:
# MAGIC * unrecorded bank fees (CASH-02, with bank-charge advices);
# MAGIC * an unknown incoming wire with no advice (CASH-02, CASH-04, CASH-03);
# MAGIC * the off-cycle payroll debit that never reached the GL;
# MAGIC * a statement-feed outage for one account in the last three business days
# MAGIC   (CASH-01 continuity gap, DQ-01 stale feed).

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
from xml.sax.saxutils import escape

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
cutoff = data_cutoff(as_of)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
BANK = volume_dir(catalog, schema, raw_volume, "bank")
wipe_family(BANK, "camt053_")
planted = PlantedRegistry("07_bank_camt053")
rng = rng_for("bank")
cash = read_scratch(catalog, schema, raw_volume, "gl_cash_lines").filter(~pl.col("_no_bank"))
pr_runs = read_scratch(catalog, schema, raw_volume, "payroll_runs")
pr = read_scratch(catalog, schema, raw_volume, "payroll_results")
act_bds = [d for d in business_days(ay, am) if d <= cutoff]
py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
PREV = period_key(py, pm)
OUTAGE_ACCOUNT = "BR01-OPS-0001"
outage_days = set(act_bds[-3:]) if len(act_bds) >= 6 else set()


def acct_id(ent, kind):
    return f"{ent}-{kind}-0001"


def next_bd(d):
    while not is_business_day(d):
        d += timedelta(days=1)
    return d

# COMMAND ----------
# MAGIC %md ## Bank entries from the book (+ clearing lag)

# COMMAND ----------
entries = []   # dict: account, book_date, value_date, amount (signed), e2e, info, kind
for r in cash.iter_rows(named=True):
    d = r["default_effective_date"]
    lag = 0
    if r["je_category"] == "Payments":                 # supplier payments clear later
        lag = 1 + int(rng.integers(0, 2))
    bd = next_bd(add_business_days(d, lag) if lag else d)
    if bd > cutoff:
        continue                                        # still outstanding today
    entries.append({"account": acct_id(r["entity"], r["acct_type"]), "book_date": bd, "value_date": bd,
                    "amount": float(r["amount_fc"]), "e2e": r["reference_2"] or "", "info": r["je_category"],
                    "kind": "book"})

# Off-cycle payroll paid by the bank but never posted in the GL.
skip_runs = pr_runs.filter(pl.col("_gl_skip"))
for run in skip_runs.iter_rows(named=True):
    amt = float(pr.filter(pl.col("Payroll_Run_ID") == run["Payroll_Run_ID"])
                .select((pl.col("Gross_Pay") + pl.col("Employer_Taxes")).sum()).item())
    entries.append({"account": acct_id(run["Company"], "PAY"), "book_date": run["Payment_Date"],
                    "value_date": run["Payment_Date"], "amount": -round(amt, 2), "e2e": f"PAY-{run['Payroll_Run_ID']}",
                    "info": "Payroll Payment", "kind": "bank_only_payroll"})

# COMMAND ----------
# MAGIC %md ## Planted bank-only items

# COMMAND ----------
bank_only = []   # (account, date, amount_fc, info, control plan)
aged = aged_business_days(act_bds, 6)
if len(aged) >= 3:
    for k, amt in enumerate([1_850.00, 2_140.00, 975.00]):
        d = aged[min(len(aged) - 1, 2 * k)]
        bank_only.append(("US01-OPS-0001", d, -amt, "Wire service charge, account analysis", "fee"))
    wire_d = aged[min(len(aged) - 1, 1)]
    bank_only.append(("GB01-OPS-0001", wire_d, round(85_000.00 / entity_rate("GB01", wire_d), 2),
                      "Incoming wire, remitter reference not recognised", "unknown_wire"))
prev_d = business_days(py, pm)[12]
bank_only.append(("US02-OPS-0001", prev_d, 3_210.55, "Interest credit, money market sweep", "prev_interest"))

for (account, d, amt, info, plan) in bank_only:
    entries.append({"account": account, "book_date": d, "value_date": d, "amount": float(amt), "e2e": "",
                    "info": info, "kind": f"bank_only_{plan}"})

bank = frame(entries).sort(["account", "book_date", "e2e"])
bank = bank.with_columns(pl.col("book_date").dt.strftime("%Y%m%d").alias("_ymd"))
bank = bank.with_columns((pl.lit("BNK-") + pl.col("account") + "-" + pl.col("_ymd") + "-"
                          + (pl.int_range(pl.len()).over(["account", "_ymd"]) + 1).cast(pl.Utf8).str.zfill(4)).alias("ref"))

# Register planted exceptions with the bank references just assigned.
for r in bank.filter(pl.col("kind").str.starts_with("bank_only_")).iter_rows(named=True):
    ent = r["account"][:4]
    per = period_key(r["book_date"].year, r["book_date"].month)
    usd = abs(r["amount"]) * entity_rate(ent, r["book_date"])
    if r["kind"] == "bank_only_fee":
        planted.add("M1", "CASH-02", f"BANK:{r['ref']}", ent, per, usd, f"Bank fee {r['ref']} not recorded in the GL")
    elif r["kind"] == "bank_only_unknown_wire":
        planted.add("M1", "CASH-02", f"BANK:{r['ref']}", ent, per, usd, f"Unidentified incoming wire {r['ref']} with no book entry")
        planted.add("M1", "CASH-04", f"BANK:{r['ref']}", ent, per, usd, "Aged reconciling item with no supporting bank advice")
        planted.add("M1", "CASH-03", f"{r['account']}|{per}", ent, per, usd, "Unexplained book-to-bank difference")
    elif r["kind"] == "bank_only_payroll" and per == ACTIVE and r["book_date"] in set(aged_business_days(act_bds, 6)):
        # The prior-period off-cycle debit is matched by EndToEndId once 06 re-interfaces the run.
        planted.add("M1", "CASH-02", f"BANK:{r['ref']}", ent, per, usd, "Payroll debit with no GL payment journal (off-cycle run not interfaced)")
    elif r["kind"] == "bank_only_prev_interest":
        planted.add("M1", "CASH-02", f"BANK:{r['ref']}", ent, per, usd, "Sweep interest credit not recorded in the GL",
                    expected_disposition="adjusted")
if len(aged) >= 3:
    planted.add("M1", "CASH-03", f"US01-OPS-0001|{ACTIVE}", "US01", ACTIVE, 4_965.00, "Unexplained difference from unrecorded fees")
for d in sorted(outage_days):
    planted.add("M1", "CASH-01", f"{OUTAGE_ACCOUNT}|{d.isoformat()}", "BR01", ACTIVE, 0.0,
                f"No bank statement received for {d} (feed outage)")
if outage_days:
    planted.add("DQ", "DQ-01", f"bank:{OUTAGE_ACCOUNT}", "BR01", ACTIVE, 0.0,
                f"Bank statement feed for {OUTAGE_ACCOUNT} is {len(outage_days)} business days behind")

# COMMAND ----------
# MAGIC %md ## Write camt.053 XML (one file per account per month)

# COMMAND ----------
def opening_balance(account):
    ent, kind = account[:4], account[5:8]
    acct = CASH_ACCOUNTS[kind]
    e = ENTITY_BY_CODE[ent]
    return round(OPENING_BS_USD_M[acct] * 1_000_000 * e["mix"] / fx_rate(e["currency"], 2024, 12), 2)


def amt_xml(v, ccy):
    return f'<Amt Ccy="{ccy}">{abs(v):.2f}</Amt><CdtDbtInd>{"CRDT" if v >= 0 else "DBIT"}</CdtDbtInd>'


accounts = [acct_id(e["code"], k) for e in ENTITIES for k in ("OPS", "PAY")]
by_acct_day = {}
for r in bank.iter_rows(named=True):
    by_acct_day.setdefault((r["account"], r["book_date"]), []).append(r)
files = 0
withheld = {}   # (account, y, m) -> statements the bank has not delivered yet (simulate_activity delivers them)
for account in accounts:
    ent = account[:4]
    ccy = ENTITY_BY_CODE[ent]["currency"]
    bal = opening_balance(account)
    for (y, m) in periods_through(as_of):
        stmts = []
        for d in business_days(y, m):
            if d > cutoff:
                break
            day = by_acct_day.get((account, d), [])
            open_bal = bal
            bal = round(bal + sum(x["amount"] for x in day), 2)
            ntry = "".join(
                f"<Ntry><NtryRef>{i + 1}</NtryRef>{amt_xml(x['amount'], ccy)}<Sts><Cd>BOOK</Cd></Sts>"
                f"<BookgDt><Dt>{d}</Dt></BookgDt><ValDt><Dt>{x['value_date']}</Dt></ValDt>"
                f"<AcctSvcrRef>{x['ref']}</AcctSvcrRef><BkTxCd><Prtry><Cd>{escape(x['info'][:35])}</Cd></Prtry></BkTxCd>"
                f"<NtryDtls><TxDtls><Refs><EndToEndId>{escape(x['e2e'] or 'NOTPROVIDED')}</EndToEndId></Refs>"
                f"<RmtInf><Ustrd>{escape(x['info'])}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>"
                for i, x in enumerate(day))
            (withheld.setdefault((account, y, m), []) if account == OUTAGE_ACCOUNT and d in outage_days else stmts).append(
                f"<Stmt><Id>STMT-{account}-{d:%Y%m%d}</Id><CreDtTm>{add_business_days(d, 1)}T06:00:00</CreDtTm>"
                f"<Acct><Id><Othr><Id>{account}</Id></Othr></Id><Ccy>{ccy}</Ccy><Svcr><FinInstnId><Nm>{escape(ENTITY_BY_CODE[ent]['bank'])}</Nm></FinInstnId></Svcr></Acct>"
                f"<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>{amt_xml(open_bal, ccy)}<Dt><Dt>{d}</Dt></Dt></Bal>"
                f"<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>{amt_xml(bal, ccy)}<Dt><Dt>{d}</Dt></Dt></Bal>"
                f"<TxsSummry><TtlNtries><NbOfNtries>{len(day)}</NbOfNtries></TtlNtries></TxsSummry>{ntry}</Stmt>")
        if not stmts:
            continue
        doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
               f'<GrpHdr><MsgId>CAMT053-{account}-{y}{m:02d}</MsgId><CreDtTm>{as_of}T06:00:00</CreDtTm></GrpHdr>'
               + "".join(stmts) + "</BkToCstmrStmt></Document>\n")
        os.makedirs(BANK, exist_ok=True)
        with open(f"{BANK}/camt053_{account}_{y}{m:02d}.xml", "w") as f:
            f.write(doc)
        files += 1

# Statements held back by the outage: kept in the generator scratch so the
# simulate_activity "bank feed catches up" scenario can deliver them as an
# intraday batch file (camt053_<account>_<yyyymm>_b001.xml).
WH = os.path.join(scratch_dir(catalog, schema, raw_volume), "withheld_bank")
os.makedirs(WH, exist_ok=True)
for f_ in os.listdir(WH):
    os.remove(os.path.join(WH, f_))
for (account, y, m), stmts_ in withheld.items():
    doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
           f'<GrpHdr><MsgId>CAMT053-{account}-{y}{m:02d}-CATCHUP</MsgId><CreDtTm>{as_of}T06:00:00</CreDtTm></GrpHdr>'
           + "".join(stmts_) + "</BkToCstmrStmt></Document>\n")
    with open(os.path.join(WH, f"camt053_{account}_{y}{m:02d}.xml"), "w") as f:
        f.write(doc)
print(f"withheld statements kept for simulate_activity: {sum(len(v) for v in withheld.values())}")

write_scratch(bank.drop("_ymd"), catalog, schema, raw_volume, "bank_entries")
planted.save(spark, catalog, schema)
print(f"bank entries={bank.height} files={files} outage_days={sorted(outage_days)}")
