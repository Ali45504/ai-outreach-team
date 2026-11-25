# -*- coding: utf-8 -*-
"""
Back up every n8n workflow to archive/n8n_backup/<date>/<name>.json (re-import in n8n: Workflows, Import from file).
With --remove-extras: after the backup, removes from n8n every workflow that is NOT one of the KEEP list,
so the owner only sees what he uses. Credentials are never touched (they live separately in n8n).
USAGE: python -I backup_n8n_workflows.py [--remove-extras]
"""
import os, sys, json, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import n8n_api as N

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
KEEP = {"USA Outreach - Daily Team", "USA Outreach - Error alert"}

out = os.path.join(ROOT, "archive", "n8n_backup", datetime.date.today().isoformat())
os.makedirs(out, exist_ok=True)
ws = N.api("GET", "/workflows?limit=200").get("data", [])
saved = {}
for w in ws:
    full = N.api("GET", f"/workflows/{w['id']}")
    fn = re.sub(r"[^\w\- ]+", "_", w["name"]).strip() + f" ({w['id']}).json"
    path = os.path.join(out, fn)
    json.dump(full, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = json.load(open(path, encoding="utf-8")).get("nodes") is not None
    saved[w["id"]] = ok
    print(("saved   " if ok else "FAILED  ") + w["name"], "->", fn)

if "--remove-extras" in sys.argv:
    for w in ws:
        if w["name"] in KEEP:
            continue
        if not saved.get(w["id"]):
            print("NOT removed (backup failed):", w["name"]); continue
        if w.get("active"):
            N.api("POST", f"/workflows/{w['id']}/deactivate")
        N.api("DELETE", f"/workflows/{w['id']}")
        print("removed from n8n:", w["name"])
print("left in n8n:", [w["name"] for w in N.api("GET", "/workflows?limit=200").get("data", [])])
