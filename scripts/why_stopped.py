# -*- coding: utf-8 -*-
"""
EMPLOYEE: Night Watch  (used by the n8n workflow "USA Outreach - Error alert")
JOB: when the daily team stops, tell the owner in plain words WHY, from the managers' own reports.
Prints one JSON line {subject, body}. Usage: python -I why_stopped.py USA "<node that failed>" "<n8n error>"
"""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import team as T

region = (sys.argv[1] if len(sys.argv) > 1 else "USA").upper()
node = sys.argv[2] if len(sys.argv) > 2 else ""
err = (sys.argv[3] if len(sys.argv) > 3 else "")[:400]

fails = []
for f in sorted(glob.glob(os.path.join(T.ROOT, "data", region, "today", "report_*.json"))):
    r = T.load(f, {})
    if r.get("status") == "FAIL":
        fails.append(f"- {r.get('agent')}: " + "; ".join(str(p) for p in (r.get("problems") or [r.get("why", "")]))[:600])

lines = [f"The USA outreach team stopped today ({T.TODAY}) at: {node or 'unknown step'}.", ""]
if fails:
    lines += ["A manager stopped the line on purpose. Their reasons:", *fails, "",
              "Nothing was sent after this point, so nothing wrong went out."]
elif "another run" in err or "Run lock" in err:
    lines += ["Another run was still working, so this one stopped at the start and changed nothing.",
              "Nothing to fix, just run it again later."]
else:
    lines += ["An n8n step failed (not a manager decision). n8n said:", err or "(no message)", "",
              "Often this is Gmail or Google being busy for a moment. Run it again in an hour from n8n "
              "(Execute workflow). If it fails again, send Claude a screenshot of the red node."]
lines += ["", "Open n8n: http://localhost:5678  (workflow USA Outreach - Daily Team, tab Executions)"]
print(json.dumps({"to": T.settings()["report_to"],
                  "subject": f"USA outreach STOPPED {T.TODAY} at {node or 'a step'}",
                  "body": "\n".join(lines)}, ensure_ascii=True))
