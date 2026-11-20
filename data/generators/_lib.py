# Databricks notebook source
# MAGIC %md
# MAGIC # _lib: shared helpers for the Corvane Technologies generators
# MAGIC
# MAGIC Source with `%run ./_lib`. Everything here is deterministic (MASTER_SEED).
# MAGIC
# MAGIC * Fictional company: entities, segments, chart of accounts with statement
# MAGIC   (FSLI) mapping, bank accounts, FX rates, ERP users and roles.
# MAGIC * Calendar: monthly close periods, business days, close-day offsets (T+n).
# MAGIC * As-of helpers: never generate the future.
# MAGIC * IO helpers: volume paths, file-family wipes, Delta writes, planted-exception
# MAGIC   registry (`meta_planted_exceptions`, demo-only ground truth).
# MAGIC
# MAGIC All names are fictional. No real company, bank, or person names are used.

# COMMAND ----------
import glob
import hashlib
import json
import math
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import polars as pl

# COMMAND ----------
# MAGIC %md ## Deterministic sub-seeds

# COMMAND ----------
MASTER_SEED = 42


def derive_seed(label: str) -> int:
    h = hashlib.md5(f"{MASTER_SEED}::{label}".encode()).digest()
    return int.from_bytes(h[:4], "little")


def rng_for(label: str) -> np.random.Generator:
    return np.random.default_rng(derive_seed(label))


def stable_id(*parts) -> str:
    """Short deterministic hex id from parts (used for Salesforce-style Ids)."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:15]

# COMMAND ----------
# MAGIC %md ## Fictional company

# COMMAND ----------
COMPANY = "Corvane Technologies"

SEGMENTS = [
    # code, name, revenue mix, revenue account, cost of revenue account
    {"code": "CLD", "name": "Cloud Platform",        "mix": 0.42, "rev_acct": "40000", "cogs_acct": "50000"},
    {"code": "ENT", "name": "Enterprise Software",   "mix": 0.30, "rev_acct": "40000", "cogs_acct": "50000"},
    {"code": "DEV", "name": "Devices",               "mix": 0.16, "rev_acct": "41000", "cogs_acct": "51000"},
    {"code": "SVC", "name": "Professional Services", "mix": 0.12, "rev_acct": "42000", "cogs_acct": "52000"},
]
SEGMENT_CODES = [s["code"] for s in SEGMENTS]
CORPORATE_SEGMENT = "COR"

ENTITIES = [
    # code, Oracle ledger id, legal name, country, region, functional currency, revenue mix, bank
    {"code": "US01", "ledger_id": 101, "name": "Corvane Technologies Inc.",     "country": "US", "region": "NA",
     "currency": "USD", "mix": 0.36, "bank": "Harborline Bank N.A."},
    {"code": "US02", "ledger_id": 102, "name": "Corvane Cloud Services LLC",    "country": "US", "region": "NA",
     "currency": "USD", "mix": 0.14, "bank": "Harborline Bank N.A."},
    {"code": "CA01", "ledger_id": 103, "name": "Corvane Technologies Canada ULC", "country": "CA", "region": "NA",
     "currency": "CAD", "mix": 0.06, "bank": "Maple Crest Bank"},
    {"code": "GB01", "ledger_id": 201, "name": "Corvane Technologies UK Ltd",   "country": "GB", "region": "EMEA",
     "currency": "GBP", "mix": 0.12, "bank": "Northcote Bank plc"},
    {"code": "IE01", "ledger_id": 202, "name": "Corvane Technologies Ireland Ltd", "country": "IE", "region": "EMEA",
     "currency": "EUR", "mix": 0.08, "bank": "Northcote Bank plc"},
    {"code": "DE01", "ledger_id": 203, "name": "Corvane Technologies GmbH",     "country": "DE", "region": "EMEA",
     "currency": "EUR", "mix": 0.10, "bank": "Altmark Kreditbank AG"},
    {"code": "SG01", "ledger_id": 301, "name": "Corvane Technologies Asia Pte Ltd", "country": "SG", "region": "APAC",
     "currency": "SGD", "mix": 0.10, "bank": "Sunda Strait Bank"},
    {"code": "BR01", "ledger_id": 401, "name": "Corvane Tecnologia Brasil Ltda", "country": "BR", "region": "LATAM",
     "currency": "BRL", "mix": 0.04, "bank": "Banco Jacaranda S.A."},
]
ENTITY_CODES = [e["code"] for e in ENTITIES]
ENTITY_BY_CODE = {e["code"]: e for e in ENTITIES}
LEDGER_TO_ENTITY = {e["ledger_id"]: e["code"] for e in ENTITIES}

# USD per one unit of functional currency (base), drifted monthly by fx_rate().
FX_BASE = {"USD": 1.0, "CAD": 0.73, "GBP": 1.27, "EUR": 1.08, "SGD": 0.74, "BRL": 0.19}


def month_index(y: int, m: int) -> int:
    return (y - 2025) * 12 + (m - 1)


def fx_rate(ccy: str, y: int, m: int) -> float:
    """Monthly average rate, USD per unit. Deterministic gentle drift."""
    if ccy == "USD":
        return 1.0
    phase = (derive_seed(f"fx::{ccy}") % 628) / 100.0
    drift = 0.025 * math.sin(2 * math.pi * month_index(y, m) / 12.0 + phase)
    return round(FX_BASE[ccy] * (1.0 + drift), 6)

# COMMAND ----------
# MAGIC %md ## Chart of accounts and statement mapping
# MAGIC
# MAGIC `type`: A asset, L liability, E equity, R revenue, X expense.
# MAGIC `fsli`: financial statement line. Control accounts name their subledger.

# COMMAND ----------
COA = [
    # account, description, type, fsli_code, fsli_name, statement, control_subledger
    ("10100", "Cash - Operating",               "A", "BS-100", "Cash and cash equivalents", "BS", "BANK"),
    ("10200", "Cash - Payroll",                 "A", "BS-100", "Cash and cash equivalents", "BS", "BANK"),
    ("11000", "Accounts Receivable - Trade",    "A", "BS-110", "Accounts receivable, net",  "BS", "AR"),
    ("11500", "Allowance for Doubtful Accounts", "A", "BS-110", "Accounts receivable, net", "BS", None),
    ("12000", "Prepaid Expenses",               "A", "BS-120", "Prepaid expenses",          "BS", None),
    ("13000", "Inventory - Devices",            "A", "BS-130", "Inventory",                 "BS", None),
    ("15000", "Property and Equipment",         "A", "BS-200", "Property and equipment, net", "BS", None),
    ("15500", "Accumulated Depreciation",       "A", "BS-200", "Property and equipment, net", "BS", None),
    ("16000", "Intangible Assets and Goodwill", "A", "BS-210", "Intangible assets and goodwill", "BS", None),
    ("20000", "Accounts Payable - Trade",       "L", "BS-300", "Accounts payable",          "BS", "AP"),
    ("21000", "Accrued Liabilities",            "L", "BS-310", "Accrued liabilities",       "BS", None),
    ("22000", "Payroll Liabilities",            "L", "BS-320", "Payroll liabilities",       "BS", "PAYROLL"),
    ("23000", "Deferred Revenue",               "L", "BS-330", "Deferred revenue",          "BS", None),
    ("24000", "Income Taxes Payable",           "L", "BS-340", "Income taxes payable",      "BS", None),
    ("25000", "Long-Term Debt",                 "L", "BS-400", "Long-term debt",            "BS", None),
    ("30000", "Common Stock and APIC",          "E", "BS-500", "Common stock and APIC",     "BS", None),
    ("31000", "Retained Earnings",              "E", "BS-510", "Retained earnings",         "BS", None),
    ("40000", "Subscription Revenue",           "R", "IS-100", "Subscription revenue",      "IS", None),
    ("41000", "Hardware Revenue",               "R", "IS-110", "Hardware revenue",          "IS", None),
    ("42000", "Services Revenue",               "R", "IS-120", "Services revenue",          "IS", None),
    ("50000", "Cost of Subscription",           "X", "IS-200", "Cost of revenue",           "IS", None),
    ("51000", "Cost of Hardware",               "X", "IS-200", "Cost of revenue",           "IS", None),
    ("52000", "Cost of Services",               "X", "IS-200", "Cost of revenue",           "IS", None),
    ("60000", "Research and Development",       "X", "IS-300", "Research and development",  "IS", None),
    ("61000", "Sales and Marketing",            "X", "IS-310", "Sales and marketing",       "IS", None),
    ("62000", "General and Administrative",     "X", "IS-320", "General and administrative", "IS", None),
    ("64000", "Bank Charges",                   "X", "IS-320", "General and administrative", "IS", None),
    ("63000", "Depreciation and Amortization",  "X", "IS-330", "Depreciation and amortization", "IS", None),
    ("70000", "Interest Expense",               "X", "IS-400", "Interest expense",          "IS", None),
    ("80000", "Income Tax Expense",             "X", "IS-500", "Income tax expense",        "IS", None),
]
COA_DF_COLUMNS = ["account", "description", "account_type", "fsli_code", "fsli_name", "statement",
                  "control_subledger"]
CONTROL_ACCOUNTS = {"AR": "11000", "AP": "20000", "PAYROLL": "22000"}
CASH_ACCOUNTS = {"OPS": "10100", "PAY": "10200"}
ORPHAN_ACCOUNT = "99999"   # not in the COA: planted referential-integrity break (DQ-03)

# Opex functions: payroll cost centers and the AP spend categories that hit them.
OPEX_FUNCTIONS = {"RND": "60000", "SNM": "61000", "GNA": "62000"}
PAYROLL_SHARE_OF_OPEX = 0.58

# Opening balance sheet, 2024-12-31, consolidated USD millions (A = L + E).
OPENING_BS_USD_M = {
    "10100": 1050.0, "10200": 60.0, "11000": 560.0, "11500": -14.0, "12000": 118.0, "13000": 92.0,
    "15000": 1480.0, "15500": -610.0, "16000": 820.0,
    "20000": -205.0, "21000": -176.0, "22000": 0.0, "23000": -440.0, "24000": -38.0, "25000": -1000.0,
    "30000": -1100.0,
}
OPENING_BS_USD_M["31000"] = -round(sum(OPENING_BS_USD_M.values()), 1)   # retained earnings plug

# COMMAND ----------
# MAGIC %md ## Periods, business days, close-day offsets

# COMMAND ----------
FIRST_PERIOD = (2025, 1)
HOLIDAYS = {(1, 1), (12, 25), (12, 26)}   # global office closures (month, day)


def generation_as_of() -> date:
    """Today (UTC). Data is generated through yesterday; simulate_activity adds today."""
    return datetime.now(timezone.utc).date()


def period_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def oracle_period_name(y: int, m: int) -> str:
    return date(y, m, 1).strftime("%b-%y").upper()   # NOV-26


def month_start(y: int, m: int) -> date:
    return date(y, m, 1)


def month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


def next_month(y: int, m: int) -> Tuple[int, int]:
    return (y + (m == 12), m % 12 + 1)


def periods_through(as_of: Optional[date] = None) -> List[Tuple[int, int]]:
    d = as_of or generation_as_of()
    out, (y, m) = [], FIRST_PERIOD
    while (y, m) <= (d.year, d.month):
        out.append((y, m))
        y, m = next_month(y, m)
    return out


def active_period(as_of: Optional[date] = None) -> Tuple[int, int]:
    d = as_of or generation_as_of()
    return d.year, d.month


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and (d.month, d.day) not in HOLIDAYS


def business_days(y: int, m: int) -> List[date]:
    d, end, out = month_start(y, m), month_end(y, m), []
    while d <= end:
        if is_business_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if is_business_day(d):
            left -= 1
    return d


def close_day_offset(d: date, y: int, m: int) -> int:
    """Signed business-day offset from period end T (the last calendar day of the
    month). T+1 = first business day after month end. Days on or before T count
    down: the last business day of the month is T0 if month end is a business day,
    else T-1 counting from the last business day."""
    t = month_end(y, m)
    if d > t:
        n, cur = 0, t
        while cur < d:
            cur += timedelta(days=1)
            if is_business_day(cur):
                n += 1
        return n
    n, cur = 0, t
    while cur > d:
        if is_business_day(cur):
            n -= 1
        cur -= timedelta(days=1)
    return n


def elapsed_business_fraction(y: int, m: int, as_of: Optional[date] = None) -> float:
    """Share of the month's business days strictly before as_of (data runs to yesterday)."""
    d = as_of or generation_as_of()
    bds = business_days(y, m)
    if not bds:
        return 0.0
    return sum(1 for b in bds if b < d) / len(bds)


def data_cutoff(as_of: Optional[date] = None) -> date:
    """Last date with generated activity: yesterday."""
    return (as_of or generation_as_of()) - timedelta(days=1)

# COMMAND ----------
# MAGIC %md ## People: ERP users and roles (fictional names)

# COMMAND ----------
FIRST_NAMES = ["Avery", "Jordan", "Riley", "Morgan", "Quinn", "Rowan", "Casey", "Emerson", "Hayden", "Parker",
               "Reese", "Sawyer", "Skyler", "Tatum", "Blair", "Drew", "Elliot", "Finley", "Harper", "Jules",
               "Kendall", "Logan", "Marlow", "Noel", "Oakley", "Peyton", "Remy", "Sage", "Toby", "Wren"]
LAST_NAMES = ["Abernathy", "Brightwater", "Calloway", "Delacroix", "Ellsworth", "Fairbanks", "Galloway",
              "Hollister", "Iverson", "Jardine", "Kessler", "Lindqvist", "Marchetti", "Nakamura", "Okonkwo",
              "Pemberton", "Quintero", "Rasmussen", "Sorensen", "Thackeray", "Underwood", "Valdivia",
              "Whitlock", "Yardley", "Zielinski", "Ashdown", "Bellamy", "Castellano", "Dunmore", "Everhart"]

SYSTEM_USERS = [
    # user_id, user_name, description, used for
    (1, "ORACLE_INTERFACE",    "Subledger accounting interface",  "Payables journals"),
    (2, "SFDC_INTEGRATION",    "Salesforce Billing integration",  "Receivables journals"),
    (3, "WORKDAY_INTEGRATION", "Workday payroll integration",     "Payroll journals"),
    (4, "AP_PAYMENT_BATCH",    "AP payment process request",      "Payment journals"),
    (5, "FA_DEPRECIATION",     "Fixed assets depreciation run",   "Depreciation journals"),
    (6, "CASH_MGMT_AUTO",      "Cash management bank posting",    "Bank-originated journals"),
]
SYSTEM_USER_IDS = {u[0] for u in SYSTEM_USERS}

ERP_ROLES = {
    # role_name: (common name, privileged)
    "GL_JOURNAL_ENTRY":    ("General Accounting Journal Entry", False),
    "GL_JOURNAL_APPROVER": ("General Accounting Journal Approval", False),
    "GL_PERIOD_CLOSE":     ("General Ledger Period Close", True),
    "AP_INVOICE_ENTRY":    ("Accounts Payable Invoice Entry", False),
    "AP_PAYMENT_RELEASE":  ("Accounts Payable Payment Release", True),
    "VENDOR_MASTER_MAINT": ("Supplier Master Maintenance", False),
    "AR_RECEIPT_ENTRY":    ("Receivables Receipt Entry", False),
    "PAYROLL_INTERFACE":   ("Payroll Journal Interface", False),
    "SECURITY_ADMIN":      ("IT Security Manager", True),
    "FINANCIAL_ANALYST":   ("Financial Analyst (read only)", False),
}
SOD_CONFLICTS = [
    ("GL_JOURNAL_ENTRY", "GL_JOURNAL_APPROVER"),
    ("AP_INVOICE_ENTRY", "AP_PAYMENT_RELEASE"),
    ("VENDOR_MASTER_MAINT", "AP_PAYMENT_RELEASE"),
]

# COMMAND ----------
# MAGIC %md ## Volume paths, file families, writes

# COMMAND ----------
def get_widget(name: str, default: str = "") -> str:
    try:
        return dbutils.widgets.get(name)  # noqa: F821
    except Exception:
        return default


def volume_dir(catalog: str, schema: str, raw_volume: str, *parts: str) -> str:
    return f"/Volumes/{catalog}/{schema}/{raw_volume}/" + "/".join(parts)


def scratch_dir(catalog: str, schema: str, raw_volume: str) -> str:
    """Generator-to-generator hand-off area. The pipeline never reads it."""
    return volume_dir(catalog, schema, raw_volume, "_generator")


def wipe_family(folder: str, prefix: str) -> int:
    """Delete files of one family (prefix) in a source folder. Each generator owns
    the families it writes, so regeneration is idempotent without touching others."""
    os.makedirs(folder, exist_ok=True)
    n = 0
    for p in glob.glob(os.path.join(folder, f"{prefix}*")):
        if os.path.isfile(p):
            os.remove(p)
            n += 1
    return n


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def write_csv(df: pl.DataFrame, path: str) -> None:
    _ensure_parent(path)
    df.write_csv(path)


def write_parquet(df: pl.DataFrame, path: str) -> None:
    _ensure_parent(path)
    df.write_parquet(path)


def write_jsonl(df: pl.DataFrame, path: str) -> None:
    _ensure_parent(path)
    df.write_ndjson(path)


def month_file(prefix: str, y: int, m: int, ext: str, batch: Optional[int] = None) -> str:
    suffix = f"_b{batch:03d}" if batch is not None else ""
    return f"{prefix}_{y:04d}M{m:02d}{suffix}.{ext}"


def write_by_month(df: pl.DataFrame, date_col: str, folder: str, prefix: str, ext: str) -> int:
    """One file per (year, month) of date_col: <prefix>_<YYYY>M<MM>.<ext>."""
    if df.is_empty():
        return 0
    df = df.with_columns(pl.col(date_col).cast(pl.Date).dt.year().alias("_y"),
                         pl.col(date_col).cast(pl.Date).dt.month().alias("_m"))
    n = 0
    for (y, m), part in df.group_by(["_y", "_m"], maintain_order=True):
        out = part.drop(["_y", "_m"])
        path = os.path.join(folder, month_file(prefix, int(y), int(m), ext))
        {"csv": write_csv, "parquet": write_parquet, "json": write_jsonl}[ext](out, path)
        n += 1
    return n


def write_delta(spark, df: pl.DataFrame, fq_table: str, mode: str = "overwrite",
                replace_where: Optional[str] = None) -> None:
    sdf = spark.createDataFrame(df.to_pandas()) if not df.is_empty() else None
    if sdf is None:
        return
    w = sdf.write.format("delta").mode(mode).option("overwriteSchema", "true" if not replace_where else "false")
    if replace_where:
        w = w.option("replaceWhere", replace_where)
    w.saveAsTable(fq_table)

# COMMAND ----------
# MAGIC %md ## Planted exceptions (demo-only ground truth)
# MAGIC
# MAGIC Every generator that plants a control exception registers it here. The
# MAGIC `gate_controls` task asserts each one is detected by its expected control
# MAGIC (recall 100%). `record_key` uses the same format the control emits.

# COMMAND ----------
PLANTED_COLUMNS = {
    "scenario_id": pl.Utf8, "generator": pl.Utf8, "module": pl.Utf8, "control_id": pl.Utf8,
    "record_key": pl.Utf8, "entity_code": pl.Utf8, "period": pl.Utf8, "amount_usd": pl.Float64,
    "description": pl.Utf8, "expected_disposition": pl.Utf8,
}


class PlantedRegistry:
    def __init__(self, generator: str):
        self.generator = generator
        self.rows: List[dict] = []

    def add(self, module: str, control_id: str, record_key: str, entity_code: str, period: str,
            amount_usd: float, description: str, expected_disposition: str = "open") -> None:
        sid = f"{control_id}:{record_key}"
        self.rows.append({"scenario_id": sid, "generator": self.generator, "module": module,
                          "control_id": control_id, "record_key": record_key, "entity_code": entity_code,
                          "period": period, "amount_usd": float(round(amount_usd, 2)),
                          "description": description, "expected_disposition": expected_disposition})

    def frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.rows, schema=PLANTED_COLUMNS) if self.rows else pl.DataFrame(schema=PLANTED_COLUMNS)

    def save(self, spark, catalog: str, schema: str) -> None:
        fq = f"`{catalog}`.`{schema}`.meta_planted_exceptions"
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq} (
            scenario_id STRING, generator STRING, module STRING, control_id STRING, record_key STRING,
            entity_code STRING, period STRING, amount_usd DOUBLE, description STRING,
            expected_disposition STRING)
            COMMENT 'DEMO-ONLY ground truth: control exceptions deliberately planted by the generators. gate_controls asserts 100% are detected by the expected control. Real source data would not have this table.'""")
        spark.sql(f"DELETE FROM {fq} WHERE generator = '{self.generator}'")
        if self.rows:
            spark.createDataFrame(self.frame().to_pandas()).write.format("delta").mode("append").saveAsTable(fq)
        print(f"planted exceptions registered by {self.generator}: {len(self.rows)}")

# COMMAND ----------
# MAGIC %md ## Small helpers

# COMMAND ----------
def renormalize(rng: np.random.Generator, n: int, total: float, sigma: float = 0.9) -> np.ndarray:
    """n positive lognormal amounts summing exactly to total (rounded to cents)."""
    if n <= 0:
        return np.array([])
    raw = rng.lognormal(mean=0.0, sigma=sigma, size=n)
    amts = np.round(raw * (total / raw.sum()), 2)
    amts[-1] = round(total - amts[:-1].sum(), 2)
    return amts


def pick_dates(rng: np.random.Generator, days: List[date], n: int, month_end_weight: float = 1.6) -> List[date]:
    """Business dates weighted toward month end (quarter-end heavy business)."""
    if not days or n <= 0:
        return []
    w = np.linspace(1.0, month_end_weight, num=len(days))
    w = w / w.sum()
    idx = rng.choice(len(days), size=n, p=w)
    return [days[i] for i in idx]


def ts(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour % 24, minute % 60))


def iso(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat() if isinstance(dt, (date, datetime)) else str(dt)


def entity_rate(entity_code: str, d: date) -> float:
    return fx_rate(ENTITY_BY_CODE[entity_code]["currency"], d.year, d.month)


def read_scratch(catalog: str, schema: str, raw_volume: str, name: str) -> pl.DataFrame:
    return pl.read_parquet(os.path.join(scratch_dir(catalog, schema, raw_volume), f"{name}.parquet"))


def write_scratch(df: pl.DataFrame, catalog: str, schema: str, raw_volume: str, name: str) -> None:
    write_parquet(df, os.path.join(scratch_dir(catalog, schema, raw_volume), f"{name}.parquet"))


def load_as_of(catalog: str, schema: str, raw_volume: str) -> date:
    """The as-of date fixed by 01_period_anchors_seed for this generate_data run, so
    every generator agrees even if the run crosses midnight UTC."""
    p = os.path.join(scratch_dir(catalog, schema, raw_volume), "as_of.json")
    with open(p) as f:
        return date.fromisoformat(json.load(f)["as_of"])


def monthly_targets(anchors: pl.DataFrame) -> pl.DataFrame:
    """M rows pivoted: one row per (period, segment_code) with a column per metric (USD)."""
    m = anchors.filter(pl.col("period_type") == "M")
    return (m.with_columns((pl.col("value_usd_m") * 1_000_000).alias("usd"))
             .pivot(values="usd", index=["period", "fiscal_year", "fiscal_month", "segment_code", "status"],
                    on="metric", aggregate_function="sum")
             .fill_null(0.0)
             .sort(["period", "segment_code"]))


# Fictional counterparty name parts (customers and suppliers).
NAME_PREFIX = ["Bluefin", "Crestline", "Driftwood", "Emberly", "Fernhollow", "Glasswing", "Halden", "Ironbark",
               "Juniper", "Kingsmere", "Larkspur", "Marrowstone", "Northwind Ridge", "Oakhurst", "Pinecrest",
               "Quarrystone", "Redfern", "Silverbirch", "Thistledown", "Umberline", "Vantor", "Willowmere",
               "Yarrowfield", "Zephyrine", "Ashcombe", "Brackwater", "Coldharbor", "Dunmere", "Eastvale",
               "Foxglove", "Greystone", "Highmoor", "Inkwell", "Kestrel Bay", "Lowmoor", "Moonvale"]
CUSTOMER_INDUSTRY = ["Logistics", "Health Systems", "Retail", "Energy", "Media", "Capital", "Foods", "Robotics",
                     "Insurance", "Mobility", "Biosciences", "Telecom", "Manufacturing", "Hospitality",
                     "Analytics", "Aerostructures", "Agritech", "Utilities"]
LEGAL_SUFFIX = {"US": ["Inc.", "Corp.", "LLC", "Holdings Inc."], "CA": ["Ltd.", "Inc."], "GB": ["Ltd", "plc"],
                "IE": ["Ltd", "DAC"], "DE": ["GmbH", "AG"], "SG": ["Pte Ltd"], "BR": ["Ltda", "S.A."]}


def frame(rows: List[dict], schema: Optional[dict] = None) -> pl.DataFrame:
    """DataFrame from dicts with full-length type inference (columns that start
    with nulls, such as termination dates, must not infer as Null)."""
    if schema:
        return pl.DataFrame(rows, schema=schema)
    return pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()


def repo_root() -> str:
    """Workspace path of the synced bundle root (…/files), from this notebook's path.
    Generators live at <root>/data/generators/<notebook>."""
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
        path = "/Workspace" + nb if not nb.startswith("/Workspace") else nb
        return os.path.dirname(os.path.dirname(os.path.dirname(path)))
    except Exception:
        return os.path.abspath(os.path.join(os.getcwd(), "..", ".."))


def load_yaml(rel_path: str) -> dict:
    import yaml
    with open(os.path.join(repo_root(), rel_path)) as f:
        return yaml.safe_load(f)


def date_for_close_offset(y: int, m: int, k: int) -> date:
    """Inverse of close_day_offset: T+k for k > 0; 0 = last business day of the month;
    -1 = the business day before that, and so on."""
    if k > 0:
        return add_business_days(month_end(y, m), k)
    bds = business_days(y, m)
    return bds[max(0, len(bds) - 1 + k)]


def aged_business_days(bds: List[date], min_age: int = 6) -> List[date]:
    """Business days at least `min_age` business days before the last one, so
    planted reconciling items are past the policy's aging window at the cutoff."""
    return [d for i, d in enumerate(bds) if len(bds) - 1 - i >= min_age]
