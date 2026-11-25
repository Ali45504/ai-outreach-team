# -*- coding: utf-8 -*-
"""Manager 3 · checks the Reply Handler's work. Removes bad drafts, stops the line on broken work.
Usage: python -I manager.py USA"""
import os, sys, re
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T

NO_DRAFT = {"auto_reply", "bounce", "unclear"}
VALID = {"rates_given", "interested_no_rates", "question", "not_interested", "auto_reply", "bounce", "unclear"}


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    path = T.today_file(region, "03_reply_events.json")
    if not os.path.exists(path):
        T.report("Manager 3 Replies", "FAIL", region=region, problem="Reply Handler produced no file")
    data = T.load(path, {})
    events = data.get("events", [])
    issues, removed = [], 0
    for e in events:
        if e.get("category") not in VALID:
            issues.append(f"{e.get('from')}: unknown category {e.get('category')}")
            e["category"] = "unclear"
        flat = re.sub(r"[,\s]", "", e.get("excerpt", ""))
        good = [p for p in e.get("prices", []) if all(re.sub(r"[,\s]", "", n).rstrip(".") in flat
                                                      for n in re.findall(r"\d[\d,.]*", p))]
        if len(good) != len(e.get("prices", [])):
            issues.append(f"{e.get('from')}: removed {len(e['prices']) - len(good)} price(s) not found in the reply")
            e["prices"] = good
        d = e.get("draft")
        if d and e["category"] in NO_DRAFT:
            e.pop("draft"); removed += 1
            issues.append(f"{e.get('from')}: draft removed, category {e['category']} must not get one")
        elif d:
            fs, fb, probs, ok = T.qc_reply(d["subject"], d["body"])
            if ok:
                d["subject"], d["body"] = fs, fb
                d["qc"] = "passed"
            else:
                e.pop("draft"); removed += 1
                e["flag_for_ali"] = "reply draft failed quality check: " + "; ".join(probs)
                issues.append(f"{e.get('from')}: draft blocked ({'; '.join(probs)})")
    data["manager_checked"] = True
    T.save(path, data)
    T.report("Manager 3 Replies", "PASS", region=region, replies_checked=len(events),
             drafts_approved=sum(1 for e in events if e.get("draft")), drafts_removed=removed, notes=issues[:20])


if __name__ == "__main__":
    main()
