# -*- coding: utf-8 -*-
"""
EMPLOYEE: Draft Sender  (n8n workflow "USA Outreach - Send waiting drafts", runs once, then removed)
JOB: send the OUTREACH drafts the team already made in Gmail (first emails, status "Draft ready").
  Never touches negotiation reply drafts: those stay for the owner, always.
CHECKS before anything is sent (the manager part):
  - the person is "draft_ready" in team memory, valid email, not suppressed, not in Ready to work
  - the Gmail draft is a NEW thread (not a reply), and there is exactly one draft for that person
  - the daily limit: never more than daily_new_limit real sends in one day
AFTER: each sent email is written to team memory as "emailed" (so the 4 day follow-up works).
USAGE: python -I send_waiting_drafts.py          (check, then send)
       python -I send_waiting_drafts.py check    (only show what would be sent, sends nothing)
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import n8n_api as N
import team as T

CFG = T.settings()
REGION = CFG["region"]
NAME = f"{REGION} Outreach - Send waiting drafts"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


def approved_list():
    """Manager check in Python: who may receive their waiting draft today, oldest drafts first."""
    st, sup = T.state(REGION), T.suppression(REGION)
    out = T.load(os.path.join(T.ROOT, "output", f"Influencer_{REGION}.json"), {})
    ready = {r["Email"].lower() for r in out.get("ready", []) if r.get("Email")}
    sent_today = sum(1 for r in st.values() if r.get("first_sent") == T.TODAY and r.get("message_id"))
    room = max(0, CFG["daily_new_limit"] - sent_today)
    ok, blocked = [], {}
    for e, rec in sorted(st.items(), key=lambda kv: kv[1].get("draft_date", "")):
        if rec.get("status") != "draft_ready":
            continue
        why = None
        good, bad = T.email_ok(e)
        if not good: why = bad
        elif e in sup: why = "suppressed"
        elif e in ready: why = "in Ready to work"
        if why:
            blocked[e] = why
        else:
            ok.append(e)
    return ok[:room], ok[room:], blocked, sent_today


def http(nodes, name, method, url, x, body=None, **extra):
    p = {"method": method, "url": url, "authentication": "predefinedCredentialType",
         "nodeCredentialType": "gmailOAuth2", "options": {}}
    if body:
        p.update(sendBody=True, specifyBody="json", jsonBody=body)
    n = {"parameters": p, "id": f"n{len(nodes)}", "name": name, "type": "n8n-nodes-base.httpRequest",
         "typeVersion": 4.2, "position": [x, 300], "credentials": N.CRED_GMAIL}
    n.update(extra)
    nodes.append(n)


def code(nodes, name, js, x, y=300, **extra):
    n = {"parameters": {"mode": "runOnceForAllItems", "jsCode": js}, "id": f"n{len(nodes)}", "name": name,
         "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y]}
    n.update(extra)
    nodes.append(n)


def build(allowed, send):
    nodes = [{"parameters": {}, "id": "t", "name": "Trigger", "type": "n8n-nodes-base.scheduleTrigger",
              "typeVersion": 1.2, "position": [0, 300]}]
    http(nodes, "List Gmail drafts", "GET", f"{API}/drafts?maxResults=500", 200, executeOnce=True)
    code(nodes, "New-thread drafts only",
         "const d = $input.first().json.drafts || [];"
         "const a = d.filter(x => x.message && x.message.id === x.message.threadId);"
         "return a.length ? a.map(x => ({json: {draft_id: x.id}})) : [{json: {draft_id: ''}}];", 400)
    http(nodes, "Read each draft (To)", "GET",
         f"={{{{ $json.draft_id ? '{API}/drafts/' + $json.draft_id + '?format=metadata&metadataHeaders=To&metadataHeaders=In-Reply-To' : '{API}/profile' }}}}",
         600, onError="continueRegularOutput")
    keep = r"""
const allowed = %s;
const byMail = {};
for (const it of $input.all()) {
  const j = it.json; if (!j.message) continue;
  const h = {}; for (const x of (j.message.payload && j.message.payload.headers) || []) h[x.name.toLowerCase()] = x.value;
  if (h['in-reply-to']) continue;                        // a reply draft: never auto-send
  const m = String(h['to'] || '').toLowerCase().match(/[a-z0-9._%%+-]+@[a-z0-9.-]+\.[a-z]{2,}/g) || [];
  if (m.length !== 1 || !allowed.includes(m[0])) continue;
  (byMail[m[0]] = byMail[m[0]] || []).push({ draft_id: j.id, email: m[0] });
}
const out = [], skipped = [];
for (const e of allowed) {
  const l = byMail[e] || [];
  if (l.length === 1) out.push(l[0]); else skipped.push({ email: e, why: l.length ? 'more than one draft' : 'no draft found (sent or deleted by the owner?)' });
}
return out.length ? out.map(x => ({ json: Object.assign(x, { skipped }) })) : [{ json: { draft_id: '', email: '', skipped } }];
""" % json.dumps(allowed)
    code(nodes, "Manager: keep approved outreach drafts", keep, 800)
    conns = {}
    names = [n["name"] for n in nodes]
    for a, b in zip(names, names[1:]):
        conns[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
    if not send:
        return nodes, conns, "Manager: keep approved outreach drafts"

    nodes.append({"parameters": {"batchSize": 1, "options": {}}, "id": "loop", "name": "One draft at a time",
                  "type": "n8n-nodes-base.splitInBatches", "typeVersion": 3, "position": [1000, 300]})
    http(nodes, "Gmail: send the draft",
         "={{ $json.draft_id ? 'POST' : 'GET' }}",
         f"={{{{ $json.draft_id ? '{API}/drafts/send' : '{API}/profile' }}}}", 1200,
         body="={{ JSON.stringify($json.draft_id ? { id: $json.draft_id } : {}) }}", onError="continueRegularOutput")
    nodes[-1]["position"] = [1200, 450]
    code(nodes, "Record result",
         "const s = $('One draft at a time').first().json; const r = $input.first().json || {};"
         "return [{json: {email: s.email, draft_id: s.draft_id, gmail_id: s.draft_id ? (r.id || '') : '',"
         " thread_id: r.threadId || '', error: r.error ? JSON.stringify(r.error).slice(0, 300) : '', skipped: s.skipped || []}}];",
         1400, 450)
    nodes.append({"parameters": {"resume": "timeInterval",
                                 "amount": "={{ $('One draft at a time').first().json.draft_id ? %d : 1 }}" % CFG["seconds_between_sends"],
                                 "unit": "seconds"},
                  "id": "wait", "name": "Pause between emails", "type": "n8n-nodes-base.wait", "typeVersion": 1.1,
                  "position": [1600, 450], "webhookId": "3b0d6a52-7e41-4c8a-9f0e-5a2c1d7e8f90"})
    code(nodes, "Collect results", "return $input.all().map(i => ({ json: i.json }));", 1200, 150)
    conns = {a: c for a, c in conns.items()}
    conns["Manager: keep approved outreach drafts"] = {"main": [[{"node": "One draft at a time", "type": "main", "index": 0}]]}
    conns["One draft at a time"] = {"main": [[{"node": "Collect results", "type": "main", "index": 0}],
                                             [{"node": "Gmail: send the draft", "type": "main", "index": 0}]]}
    conns["Gmail: send the draft"] = {"main": [[{"node": "Record result", "type": "main", "index": 0}]]}
    conns["Record result"] = {"main": [[{"node": "Pause between emails", "type": "main", "index": 0}]]}
    conns["Pause between emails"] = {"main": [[{"node": "One draft at a time", "type": "main", "index": 0}]]}
    return nodes, conns, "Collect results"


def record(results):
    """Recorder part: write every real send into team memory."""
    st = T.state(REGION)
    sent, errors = [], []
    for r in results:
        e = (r.get("email") or "").lower()
        if not e:
            continue
        if r.get("error") or not r.get("gmail_id"):
            errors.append({"email": e, "error": r.get("error") or "no id back from Gmail"})
            continue
        rec = st.setdefault(e, {})
        rec.update(status="emailed", last_sent=T.TODAY, followups=0, message_id=r["gmail_id"],
                   thread_id=r.get("thread_id") or rec.get("thread_id"))
        rec.setdefault("first_sent", T.TODAY)
        ids = rec.setdefault("sent_ids", [])
        if r["gmail_id"] not in ids:
            ids.append(r["gmail_id"])
        T.log_event(rec, "waiting draft sent")
        sent.append(e)
    T.save_state(REGION, st)
    return sent, errors


def main():
    send = not (len(sys.argv) > 1 and sys.argv[1].lower() == "check")
    allowed, over_limit, blocked, sent_today = approved_list()
    print(f"Already sent today: {sent_today}. Approved to send now: {len(allowed)}."
          + (f" Waiting for tomorrow (daily limit): {len(over_limit)}." if over_limit else "")
          + (f" Blocked: {blocked}" if blocked else ""), flush=True)
    if not allowed:
        print("Nothing to send."); return
    nodes, conns, last = build(allowed, send)
    mins = max(1, round(len(allowed) * CFG["seconds_between_sends"] / 60))
    print(("Sending" if send else "Checking") + f" through n8n (about {mins} minute(s) plus 2 to start) ...", flush=True)
    T.take_run_lock(REGION, "send waiting drafts")
    try:
        ex = N.fire_once(NAME, nodes, conns, trigger_name="Trigger", max_wait=3600)
        out = N.last_node_output(ex, last)
    finally:
        w = N.find_workflow(NAME)
        if w:
            N.api("DELETE", f"/workflows/{w['id']}")
        T.release_run_lock(REGION)
    skipped = next((o.get("skipped") for o in out if o.get("skipped")), [])
    if not send:
        found = [o["email"] for o in out if o.get("email")]
        print(json.dumps({"would_send": len(found), "emails": found, "skipped": skipped}, indent=1)); return
    done, errors = record(out)
    print(json.dumps({"sent": len(done), "errors": errors, "skipped": skipped}, indent=1))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
