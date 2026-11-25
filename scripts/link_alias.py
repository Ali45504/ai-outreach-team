# -*- coding: utf-8 -*-
"""
Link a second email (manager, team, other address) to the influencer's main row.
Everything known under the second email (price, contacts, numbers, notes, talking) moves to the main row,
and future replies from the second email are filed under the main row by the Reply Handler.
USAGE: python -I link_alias.py SECOND_EMAIL MAIN_EMAIL
       python -I link_alias.py --forget EMAIL     (mark as not an influencer, the record is kept)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import team as T

R = T.settings()["region"]
T.take_run_lock(R, "link alias")
try:
    st = T.state(R)
    if sys.argv[1] == "--forget":
        e = sys.argv[2].lower()            # memory is never deleted: the record stays, marked as not an influencer
        rec = st.setdefault(e, {})
        rec["status"] = "not_influencer"
        T.log_event(rec, "marked not an influencer (newsletter / company mail)")
        print("marked not an influencer:", e)
    else:
        alias, main = sys.argv[1].lower(), sys.argv[2].lower()
        a, m = st.get(alias, {}), st.setdefault(main, {})
        for k in ("contacts", "numbers", "notes"):
            for x in a.get(k, []):
                if x not in m.setdefault(k, []):
                    m[k].append(x)
        if a.get("price"):
            m["price"] = "; ".join(dict.fromkeys(([m["price"]] if m.get("price") else []) + [a["price"]]))
        if a.get("status") in ("talking", "declined") and m.get("status") not in ("talking", "declined"):
            m["status"] = a["status"]
            for k in ("reply_category", "open_to_future"):
                if k in a:
                    m[k] = a[k]
        m.setdefault("aliases", [])
        if alias not in m["aliases"]:
            m["aliases"].append(alias)
        T.log_event(m, f"linked second email {alias}")
        st[alias] = {"alias_of": main, "status": "alias"}
        print(alias, "->", main, "| now:", m.get("status"), "| price:", m.get("price", "")[:60], "| contacts:", m.get("contacts"))
    T.save_state(R, st)
finally:
    T.release_run_lock(R)
