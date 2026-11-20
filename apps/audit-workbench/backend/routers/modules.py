"""Reconciliations & Testing: one tab per module (Cash, Subledger, Journals, Access).

KPIs come from the module's metric view. Each tab has one visual built from the
module's gold tables (the same tables its controls test). The checklist slice and
exceptions on each tab come from /checklist and /exceptions filtered by module, so
there is one checklist and one queue, not a copy per tab.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CallerIdentity, caller_identity
from ..db import fetch_many
from ..sqlutil import fq, period_or_active

router = APIRouter(prefix="/modules", tags=["modules"])

BENFORD = {d: __import__("math").log10(1 + 1 / d) for d in range(1, 10)}


def _cash(caller: CallerIdentity, p: str) -> dict:
    r = fetch_many(caller, {
        "kpis": (f"""SELECT MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd, MEASURE(recon_in_tolerance_pct) AS in_tolerance_pct,
                            MEASURE(auto_match_rate) AS auto_match_rate, MEASURE(aged_items) AS aged_items,
                            MEASURE(reconciliations) AS reconciliations, MEASURE(breaks) AS breaks
                     FROM {fq('gold_mv_reconciliations')} WHERE period = ? AND recon_type = 'CASH'""", [p]),
        "accounts": (f"""SELECT recon_object AS bank_account, entity_code, currency_code, book_balance, external_balance,
                                outstanding_book_items, bank_items_not_in_book, unexplained_amount, unexplained_amount_usd,
                                items_total, items_matched, items_pending, items_aged_unmatched, last_statement_date
                         FROM {fq('gold_m1_cash_recon')} WHERE period = ? ORDER BY abs(unexplained_amount_usd) DESC, recon_object""", [p]),
        "match": (f"""SELECT match_status, count(*) AS items, round(sum(abs(amount)), 2) AS amount
                      FROM {fq('gold_m1_cash_match')} WHERE period = ? GROUP BY match_status ORDER BY items DESC""", [p]),
        # Unmatched items still inside the CASH-03 aging window, net in bank-minus-book terms
        # (same sign convention as unexplained_amount: bank-only adds, book-only subtracts).
        "pending": (f"""SELECT m.bank_account,
                               sum(CASE WHEN m.match_status = 'BANK_ONLY' THEN m.amount WHEN m.match_status = 'BOOK_ONLY' THEN -m.amount ELSE 0 END)
                                 AS pending_net
                        FROM {fq('gold_m1_cash_match')} m
                        CROSS JOIN (SELECT CAST(parameters['aging_bd'] AS INT) AS aging_bd FROM {fq('gold_dim_control')}
                                    WHERE control_id = 'CASH-03') c
                        WHERE m.period = ? AND m.match_status <> 'MATCHED' AND m.age_bd <= c.aging_bd
                        GROUP BY m.bank_account""", [p]),
    })
    pend = {x["bank_account"]: x["pending_net"] or 0.0 for x in r["pending"]}
    for a in r["accounts"]:
        a["pending_items_net"] = pend.get(a["bank_account"], 0.0)
        if a.get("external_balance") is not None:
            # Whatever the components above do not explain (timing across the period end, rounding).
            a["other_reconciling"] = (a["external_balance"] - a["book_balance"] - a["pending_items_net"]
                                      - (a["unexplained_amount"] or 0.0))
    return {"kpis": (r["kpis"] or [{}])[0], "visual": {"kind": "cash_waterfall", "accounts": r["accounts"], "match": r["match"]}}


def _subledger(caller: CallerIdentity, p: str) -> dict:
    r = fetch_many(caller, {
        "kpis": (f"""SELECT MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd, MEASURE(recon_in_tolerance_pct) AS in_tolerance_pct,
                            MEASURE(reconciliations) AS reconciliations, MEASURE(breaks) AS breaks
                     FROM {fq('gold_mv_reconciliations')} WHERE period = ? AND recon_type <> 'CASH'""", [p]),
        "heat": (f"""SELECT recon_type, entity_code, control_id, book_balance, external_balance, difference, difference_usd,
                            tolerance_amount, in_tolerance, currency_code
                     FROM {fq('gold_m2_subledger_recon')} WHERE period = ? ORDER BY recon_type, entity_code""", [p]),
        "trend": (f"""SELECT period, recon_type, sum(abs(difference_usd)) AS abs_difference_usd,
                             sum(CASE WHEN in_tolerance THEN 0 ELSE 1 END) AS breaks
                      FROM {fq('gold_m2_subledger_recon')} WHERE period >= date_format(add_months(to_date(concat(?, '-01')), -5), 'yyyy-MM')
                        AND period <= ? GROUP BY period, recon_type ORDER BY period""", [p, p]),
    })
    return {"kpis": (r["kpis"] or [{}])[0], "visual": {"kind": "tieout_heatmap", "cells": r["heat"], "trend": r["trend"]}}


def _journals(caller: CallerIdentity, p: str) -> dict:
    r = fetch_many(caller, {
        "kpis": (f"""SELECT MEASURE(je_count) AS je_count, MEASURE(je_amount_usd) AS je_amount_usd, MEASURE(manual_je_pct) AS manual_je_pct,
                            MEASURE(flagged_je_count) AS flagged_je_count, MEASURE(flagged_je_amount_usd) AS flagged_je_amount_usd,
                            MEASURE(self_approved_count) AS self_approved_count,
                            MEASURE(unapproved_over_threshold_count) AS unapproved_over_threshold_count,
                            MEASURE(off_hours_count) AS off_hours_count, MEASURE(duplicate_count) AS duplicate_count,
                            MEASURE(outlier_count) AS outlier_count
                     FROM {fq('gold_mv_journal_entries')} WHERE period = ?""", [p]),
        "digits": (f"""SELECT CAST(substr(regexp_replace(CAST(abs(amount_usd) AS STRING), '[^1-9]', ''), 1, 1) AS INT) AS digit, count(*) AS n
                       FROM {fq('gold_fact_journal_entries')}
                       WHERE period = ? AND is_manual AND abs(amount_usd) >= 10 GROUP BY 1 ORDER BY 1""", [p]),
        # Benford needs volume: users with a handful of journals always look non-conforming.
        "users": f"""SELECT created_by_user_id, user_name, journals, mad, non_conforming FROM {fq('gold_m3_benford_by_user')}
                     WHERE journals >= 30 ORDER BY mad DESC LIMIT 12""",
        "flags": (f"""SELECT sum(CASE WHEN jet01_self_approved THEN 1 ELSE 0 END) AS self_approved,
                             sum(CASE WHEN jet02_unapproved_over_threshold THEN 1 ELSE 0 END) AS unapproved_over_threshold,
                             sum(CASE WHEN jet03_off_hours THEN 1 ELSE 0 END) AS off_hours,
                             sum(CASE WHEN jet04_duplicate THEN 1 ELSE 0 END) AS duplicates,
                             sum(CASE WHEN jet05_round_amount THEN 1 ELSE 0 END) AS round_amounts,
                             sum(CASE WHEN jet05_outlier THEN 1 ELSE 0 END) AS outliers, count(*) AS population
                      FROM {fq('gold_fact_journal_entries')} WHERE period = ?""", [p]),
    })
    total = sum(int(d["n"]) for d in r["digits"] if d["digit"]) or 1
    digits = [{"digit": d, "expected_pct": BENFORD[d],
               "observed_pct": next((int(x["n"]) for x in r["digits"] if x["digit"] == d), 0) / total} for d in range(1, 10)]
    return {"kpis": (r["kpis"] or [{}])[0],
            "visual": {"kind": "benford", "digits": digits, "population": total, "users": r["users"],
                       "flags": (r["flags"] or [{}])[0]}}


def _access(caller: CallerIdentity, p: str) -> dict:
    r = fetch_many(caller, {
        "kpis": (f"""SELECT MEASURE(active_users) AS active_users, MEASURE(sod_conflict_users) AS sod_conflict_users,
                            MEASURE(terminated_with_access) AS terminated_with_access,
                            MEASURE(post_termination_journals) AS post_termination_journals,
                            MEASURE(post_termination_amount_usd) AS post_termination_amount_usd
                     FROM {fq('gold_mv_access_risk')} WHERE period = ?""", [p]),
        "pairs": (f"""SELECT c AS conflict, count(DISTINCT user_id) AS users FROM {fq('gold_fact_user_access')}
                      LATERAL VIEW explode(sod_conflicts) x AS c WHERE period = ? GROUP BY c ORDER BY users DESC""", [p]),
        "roles": (f"""SELECT r AS role, count(DISTINCT user_id) AS users FROM {fq('gold_fact_user_access')}
                      LATERAL VIEW explode(roles) x AS r WHERE period = ? GROUP BY r ORDER BY users DESC""", [p]),
        "terminated": (f"""SELECT user_name, {fq('mask_pii')}(legal_name) AS legal_name, entity_code, job_profile, termination_date, access_end_date,
                                  removal_lag_bd, post_termination_journals, post_termination_amount_usd
                           FROM {fq('gold_fact_user_access')}
                           WHERE period = ? AND (terminated_with_access OR post_termination_journals > 0)
                           ORDER BY post_termination_amount_usd DESC NULLS LAST""", [p]),
    })
    return {"kpis": (r["kpis"] or [{}])[0],
            "visual": {"kind": "sod_matrix", "pairs": r["pairs"], "roles": r["roles"], "terminated": r["terminated"]}}


HANDLERS = {"cash": ("M1", _cash), "subledger": ("M2", _subledger), "journals": ("M3", _journals), "access": ("M4", _access)}


@router.get("/{name}")
def module(name: str, period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    if name not in HANDLERS:
        raise HTTPException(404, f"Unknown module {name}")
    p = period_or_active(period)
    code, fn = HANDLERS[name]
    return {"module": code, "name": name, "period": p, **fn(caller, p)}
