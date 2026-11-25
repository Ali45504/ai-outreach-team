# -*- coding: utf-8 -*-
"""Manager 2 · Quality Critic. Checks every email, fixes safe issues, blocks bad ones.
Usage: python -I manager.py USA"""
import os, sys, re
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    path = T.today_file(region, "02_drafts.json")
    data = T.load(path, None)
    if data is None:
        T.report("Manager 2 Quality Critic", "FAIL", region=region, problems=["Copywriter produced no file"])
    drafts = data.get("drafts", [])
    approved, blocked = 0, []
    for d in drafts:
        if d["type"] == "new":
            fs, fb, probs, ok = T.qc_outreach(d["subject"], d["body"])
        else:
            fs, fb, probs, ok = T.qc_reply(d["subject"], d["body"])
        extra = []
        if not fs.strip(): extra.append("empty subject")
        if re.search(r"\{[a-z_]+\}|\[[A-Z ]+\]|undefined|None\b", fs + fb): extra.append("unfilled placeholder")
        if not fb.startswith("Hi "): extra.append("missing greeting")
        if len(fb) > 1500: extra.append("too long for a first touch")
        probs = probs + extra
        d["subject"], d["body"] = fs, fb
        d["qc"] = "passed" if not probs else "blocked: " + "; ".join(probs)
        if probs:
            blocked.append({"email": d["email"], "problems": probs})
        else:
            approved += 1
    data["manager_checked"] = True
    T.save(path, data)
    rate = len(blocked) / len(drafts) if drafts else 0
    T.report("Manager 2 Quality Critic", "FAIL" if rate > 0.2 else "PASS", region=region,
             checked=len(drafts), approved=approved, blocked=len(blocked), blocked_examples=blocked[:5])


if __name__ == "__main__":
    main()
