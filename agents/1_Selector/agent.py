# -*- coding: utf-8 -*-
"""Agent 1 · Selector. See AGENT.md. Usage: python -I agent.py USA"""
import os, sys, datetime
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T


def already_contacted(region):
    g = T.load(os.path.join(T.ROOT, "data", "gmail_scan.json"), {})
    return set(g.get("contacted", [])) | set(g.get("replied", []))


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    cfg = T.settings()
    st, sup = T.state(region), T.suppression(region)
    out = T.load(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"), {})
    ready_emails = {r["Email"].lower() for r in out.get("ready", []) if r.get("Email")}
    contacted = already_contacted(region)

    # the daily limit counts EVERY run today, so pressing Run twice never doubles the emails
    used_today = sum(1 for rec in st.values()
                     if rec.get("draft_date") == T.TODAY or (rec.get("first_sent") == T.TODAY and rec.get("message_id")))
    limit_left = max(0, cfg["daily_new_limit"] - used_today)
    fol_today = sum(1 for rec in st.values() for h in rec.get("history", [])
                    if h.get("date") == T.TODAY and "followup" in h.get("event", ""))
    fol_left = max(0, cfg["followup_daily_limit"] - fol_today)

    picked, skipped, per_domain, seen = [], {}, {}, set()
    for r in out.get("outreaching", []):
        if len(picked) >= limit_left:
            break
        if r.get("Status") != "To contact" or not r.get("Email"):
            continue
        e = r["Email"].strip().lower()
        why = None
        ok, bad = T.email_ok(e)
        if not ok: why = bad
        elif e in seen: why = "duplicate in today's list"
        elif e in st: why = "already in team memory (" + str(st[e].get("status")) + ")"
        elif e in sup: why = "suppressed (" + sup[e] + ")"
        elif e in contacted: why = "already emailed before (Gmail history)"
        elif e in ready_emails: why = "in Ready to work"
        elif r.get("Number"): why = "has a contact number"
        else:
            dom = T.company_domain(e)
            if dom and per_domain.get(dom, 0) >= cfg["max_per_company_domain_per_day"]:
                why = "domain limit for today (" + dom + ")"
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        seen.add(e)
        dom = T.company_domain(e)
        if dom:
            per_domain[dom] = per_domain.get(dom, 0) + 1
        picked.append({"email": e, "name": r.get("Username", ""), "profile": r.get("Social Profile", ""),
                       "notes": r.get("Notes", ""), "row_no": r.get("No:")})

    due_before = (datetime.date.today() - datetime.timedelta(days=cfg["followup_after_days"])).isoformat()
    follow = []
    gmail_failed = any(m.get("gmail_error") for m in T.n8n_items(T.inbox_file(region, "gmail_recent.json")))
    for e, rec in st.items():
        if gmail_failed:        # replies were not read this run: someone may have answered, so no follow-ups today
            break
        if len(follow) >= fol_left:
            break
        if rec.get("status") != "emailed" or e in sup or e in ready_emails:
            continue
        if rec.get("followups", 0) >= cfg["max_followups"] or not rec.get("last_sent"):
            continue
        if rec["last_sent"] > due_before:
            continue
        mid = rec.get("message_id") or (rec.get("sent_ids") or [None])[-1]
        if not mid:
            continue
        follow.append({"email": e, "name": rec.get("name", ""), "message_id": mid, "thread_id": rec.get("thread_id"),
                       "subject": rec.get("subject") or "", "last_sent": rec["last_sent"]})

    T.save(T.today_file(region, "01_selected.json"), {"date": T.TODAY, "new": picked, "followups": follow,
                                                      "skipped_reasons": skipped})
    T.report("Agent 1 Selector", "DONE", region=region, new_selected=len(picked), followups_due=len(follow),
             already_done_today=used_today, skipped=skipped,
             **({"note": "Gmail could not be read this run, follow-ups held until next run"} if gmail_failed else {}))


if __name__ == "__main__":
    main()
