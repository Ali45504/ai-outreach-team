# -*- coding: utf-8 -*-
"""Manager 1 · checks the Selector. Any breach stops the line. Usage: python -I manager.py USA"""
import os, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import already_contacted


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    cfg = T.settings()
    sel = T.load(T.today_file(region, "01_selected.json"), None)
    if not sel:
        T.report("Manager 1 Selection", "FAIL", region=region, problems=["Selector produced no file"])
    st, sup = T.state(region), T.suppression(region)
    out = T.load(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"), {})
    ready = {r["Email"].lower() for r in out.get("ready", []) if r.get("Email")}
    contacted = already_contacted(region)
    problems, emails, domains = [], [], {}
    new, fol = sel.get("new", []), sel.get("followups", [])
    if len(new) > cfg["daily_new_limit"]:
        problems.append(f"{len(new)} new picks, limit is {cfg['daily_new_limit']}")
    if len(fol) > cfg["followup_daily_limit"]:
        problems.append(f"{len(fol)} follow-ups, limit is {cfg['followup_daily_limit']}")
    for p in new:
        e = p["email"]
        ok, why = T.email_ok(e)
        if not ok: problems.append(f"{e}: {why}")
        if e in st: problems.append(f"{e}: already in team memory")
        if e in sup: problems.append(f"{e}: suppressed")
        if e in contacted: problems.append(f"{e}: emailed before")
        if e in ready: problems.append(f"{e}: is in Ready to work")
        emails.append(e)
        d = T.company_domain(e)
        if d:
            domains[d] = domains.get(d, 0) + 1
    for d, n in domains.items():
        if n > cfg["max_per_company_domain_per_day"]:
            problems.append(f"domain {d} has {n} picks today")
    if len(emails) != len(set(emails)):
        problems.append("duplicate emails in today's picks")
    for f in fol:
        rec = st.get(f["email"], {})
        if rec.get("status") != "emailed" or f["email"] in sup:
            problems.append(f"{f['email']}: follow-up not allowed (status {rec.get('status')})")
    T.report("Manager 1 Selection", "FAIL" if problems else "PASS", region=region,
             new_checked=len(new), followups_checked=len(fol), problems=problems[:20])


if __name__ == "__main__":
    main()
