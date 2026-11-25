# -*- coding: utf-8 -*-
"""
EMPLOYEE: Inbox Watcher  (n8n workflow "Outreach - Gmail Scan")
JOB: read the outreach Gmail and report (a) every address we have emailed and
(b) every address that wrote back, so nobody already talking to the owner gets a cold
email again. Reads Gmail in 5-day windows with a pause between each, because the
Gmail API has a per-minute limit and n8n fetches every message one by one.
Trigger: schedule (AutomateJoy does not serve webhooks). Claude runs it once via
n8n_api.run_once(); the daily pipeline will reuse the same nodes.
Output saved to n8n task/data/gmail_scan.json
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import n8n_api as N

NAME = "Outreach - Gmail Scan"
DAYS_BACK = 120
WINDOW_DAYS = 5

WINDOWS_JS = r"""
const out = [];
const DAY = 86400000, now = Date.now();
const fmt = d => { const x = new Date(d); return x.getUTCFullYear()+'/'+String(x.getUTCMonth()+1).padStart(2,'0')+'/'+String(x.getUTCDate()).padStart(2,'0'); };
for (let back = %(days)d; back > 0; back -= %(win)d) {
  const a = now - back*DAY, b = now - Math.max(back-%(win)d, -1)*DAY;
  out.push({ json: { q: 'in:sent after:' + fmt(a) + ' before:' + fmt(b + DAY) } });
}
out.push({ json: { q: 'in:inbox -from:me newer_than:%(days)dd -category:promotions -category:social -category:updates -category:forums' } });
return out;
""" % {"days": DAYS_BACK, "win": WINDOW_DAYS}

AGG_JS = r"""
const mine = e => e.split('@')[0].replace(/\./g,'') === 'yourgmailuser' && e.endsWith('@gmail.com');
const grab = v => {
  if (v == null) return [];
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return (s.toLowerCase().match(/[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}/g) || []);
};
const contacted = new Set(), replied = new Set();
let n = 0;
for (const it of $input.all()) {
  const j = it.json;
  if (!j || (!j.id && !j.From && !j.from)) continue;      // empty window placeholder
  n++;
  const from = grab(j.From ?? j.from ?? (j.headers && j.headers.from));
  const to = grab(j.To ?? j.to ?? (j.headers && j.headers.to)).concat(grab(j.Cc ?? j.cc));
  const sent = (j.labelIds || []).includes('SENT') || from.some(mine);
  if (sent) { for (const e of to) if (!mine(e)) contacted.add(e); }
  else { for (const e of from) if (!mine(e)) replied.add(e); }
}
return [{ json: { messages_scanned: n, contacted: [...contacted].sort(), replied: [...replied].sort() } }];
"""

nodes = [
    {"parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
     "id": "n-trig", "name": "Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2,
     "position": [160, 300]},
    {"parameters": {"mode": "runOnceForAllItems", "jsCode": WINDOWS_JS},
     "id": "n-win", "name": "Make date windows", "type": "n8n-nodes-base.code", "typeVersion": 2,
     "position": [360, 300]},
    {"parameters": {"batchSize": 1, "options": {}},
     "id": "n-loop", "name": "One window at a time", "type": "n8n-nodes-base.splitInBatches", "typeVersion": 3,
     "position": [560, 300]},
    {"parameters": {"resource": "message", "operation": "getAll", "returnAll": True, "simple": True,
                    "filters": {"q": "={{ $json.q }}"}},
     "id": "n-gmail", "name": "Read outreach Gmail", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1,
     "position": [780, 420], "credentials": N.CRED_GMAIL, "alwaysOutputData": True,
     "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000},
    {"parameters": {"resume": "timeInterval", "amount": 15, "unit": "seconds"},
     "id": "n-wait", "name": "Pause (Gmail limit)", "type": "n8n-nodes-base.wait", "typeVersion": 1.1,
     "position": [980, 420], "webhookId": "b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d"},
    {"parameters": {"mode": "runOnceForAllItems", "jsCode": AGG_JS},
     "id": "n-agg", "name": "Who we emailed / who replied", "type": "n8n-nodes-base.code", "typeVersion": 2,
     "position": [780, 180]},
]
connections = {
    "Trigger": {"main": [[{"node": "Make date windows", "type": "main", "index": 0}]]},
    "Make date windows": {"main": [[{"node": "One window at a time", "type": "main", "index": 0}]]},
    "One window at a time": {"main": [
        [{"node": "Who we emailed / who replied", "type": "main", "index": 0}],   # done
        [{"node": "Read outreach Gmail", "type": "main", "index": 0}],            # loop
    ]},
    "Read outreach Gmail": {"main": [[{"node": "Pause (Gmail limit)", "type": "main", "index": 0}]]},
    "Pause (Gmail limit)": {"main": [[{"node": "One window at a time", "type": "main", "index": 0}]]},
}

if __name__ == "__main__":
    print("Gmail scan:", DAYS_BACK, "days in", WINDOW_DAYS, "day windows (takes several minutes) ...", flush=True)
    ex = N.fire_once(NAME, nodes, connections, trigger_name="Trigger")
    r = N.last_node_output(ex, "Who we emailed / who replied")[0]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "gmail_scan.json")
    json.dump(r, open(out, "w", encoding="utf-8"), indent=1)
    print("messages scanned:", r.get("messages_scanned"), "| emailed:", len(r.get("contacted", [])),
          "| wrote back:", len(r.get("replied", [])), "| saved:", os.path.normpath(out))
