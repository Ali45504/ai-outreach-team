# -*- coding: utf-8 -*-
"""Manager 4 · checks the Recorder. Usage: python -I manager.py USA sync|finalize"""
import os, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    shift = sys.argv[2] if len(sys.argv) > 2 else "sync"
    rep = T.load(T.today_file(region, f"report_agent_4_recorder_{shift}.json"), {})
    out = T.load(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"), {})
    t_out, t_ready = out.get("outreaching", []), out.get("ready", [])
    problems, notes = [], []
    if rep.get("status") != "DONE":
        problems.append("Recorder did not finish")
    total = len(t_out) + len(t_ready)
    if total != rep.get("total_influencers"):
        problems.append(f"row count mismatch: tabs have {total}, recorder built {rep.get('total_influencers')}")
    prev = T.load(T.state_file(region, "last_row_count.json"), {}).get("total", 0)
    if prev and total < prev:
        problems.append(f"rows lost: {prev} yesterday, {total} now")
    keys = [T.row_key(r) for r in t_out + t_ready]
    if len(keys) != len(set(keys)):
        notes.append(f"{len(keys) - len(set(keys))} rows share a profile key (kept, not merged)")
    # human edits must survive
    edits = T.load(T.state_file(region, "manual_edits.json"), {})
    by_key = {T.row_key(r): r for r in t_out + t_ready}
    lost = [k for k, e in edits.items() if k in by_key and any(
        f in e and str(e[f]).strip() != str(by_key[k].get(f, "")).strip() for f in ("Email", "Price", "Contacts", "Number", "Notes"))]
    if lost:
        problems.append(f"{len(lost)} of the owner's edits were not kept, e.g. {lost[:3]}")
    # talking / number people must be in Ready to work
    st = T.state(region)
    misplaced = [r["Email"] for r in t_out if r.get("Email") and st.get(r["Email"].lower(), {}).get("status") == "talking"]
    if misplaced:
        problems.append(f"{len(misplaced)} people who are talking are not in Ready to work: {misplaced[:3]}")
    # missing-email rows must be at the bottom of Outreaching
    seen_missing = False
    for r in t_out:
        if r["Status"].startswith("Needs email"):
            seen_missing = True
        elif seen_missing and r["Status"] in ("To contact",):
            problems.append("a 'To contact' row sits below the missing-email rows"); break
    if shift == "finalize":
        sent = T.n8n_items(T.today_file(region, "06_send_results.json"))
        ok_new = {x["email"].lower() for x in sent if x.get("action") in ("send_new", "draft_new") and x.get("gmail_id")}
        shown = {r["Email"].lower() for r in t_out + t_ready if r.get("Email")
                 and (r["Status"].startswith("Emailed") or r["Status"].startswith("Draft ready")
                      or r["Status"].startswith("Talking"))}
        missing = ok_new - shown
        if missing:
            problems.append(f"{len(missing)} emails done today are not shown as emailed/draft: {sorted(missing)[:3]}")
        for f in (f"sheet_{region}_outreaching.json", f"sheet_{region}_ready.json"):
            if not os.path.exists(os.path.join(T.ROOT, "output", f)):
                problems.append(f"sheet file {f} missing")
        if not problems:
            T.save(T.state_file(region, "last_row_count.json"), {"total": total, "date": T.TODAY})
    T.report(f"Manager 4 Recorder {shift}", "FAIL" if problems else "PASS", region=region,
             outreaching=len(t_out), ready=len(t_ready), problems=problems, notes=notes)


if __name__ == "__main__":
    main()
