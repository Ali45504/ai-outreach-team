# -*- coding: utf-8 -*-
"""
EMPLOYEE: Reply Archivist  (one-off / on demand, n8n workflow "USA Outreach - Backfill old replies", removed after)
JOB: the daily Reply Handler only reads the last few days of Gmail. People who replied BEFORE the team
existed have no rates / Telegram / phone in the sheet. This reads their whole Gmail history once, with
the SAME Reply Handler rules (free model + regex, prices only if literally written), and fills team memory.
SAFE: never makes drafts, never sends. Never downgrades: declined stays declined, talking stays talking.
Someone who replied but is still "emailed" in memory becomes "talking" so no follow-up goes to them.
USAGE: python -I backfill_reply_details.py          (people who replied: Ready "Talking" rows + Gmail scan)
"""
import sys, os, json, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import n8n_api as N
import team as T

REGION = T.settings()["region"]
NAME = f"{REGION} Outreach - Backfill old replies"
spec = importlib.util.spec_from_file_location("reply_handler", os.path.join(T.ROOT, "agents", "3_Reply_Handler", "agent.py"))
RH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RH)

SLIM = r"""
const pick = v => v == null ? '' : (typeof v === 'string' ? v : (v.text || (v.value || []).map(x => x.address).join(', ') || JSON.stringify(v)));
const out = [];
for (const it of $input.all()) {
  const j = it.json; if (!j || !j.id) continue;
  out.push({ json: { id: j.id, threadId: j.threadId, labelIds: j.labelIds || [], from: pick(j.from ?? j.From),
    subject: j.subject ?? j.Subject ?? '', date: j.date ?? j.Date ?? '', text: String(j.text ?? j.snippet ?? '').slice(0, 6000) } });
}
return out.length ? out : [{ json: {} }];
"""


def targets():
    out = T.load(os.path.join(T.ROOT, "output", f"Influencer_{REGION}.json"), {})
    g = T.load(os.path.join(T.ROOT, "data", "gmail_scan.json"), {})
    t = {r["Email"].lower() for r in out.get("ready", []) if r.get("Email") and r.get("Status", "").startswith("Talking")}
    t |= {e.lower() for e in g.get("replied", [])}
    return sorted(e for e in t if T.email_ok(e)[0])


def fetch(emails):
    q = "-in:sent -in:drafts from:(" + " OR ".join(emails) + ")"
    nodes = [
        {"parameters": {}, "id": "t", "name": "Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0]},
        {"parameters": {"resource": "message", "operation": "getAll", "returnAll": True, "simple": False,
                        "filters": {"q": q}, "options": {}},
         "id": "g", "name": "Read their replies (all time)", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1,
         "position": [220, 0], "credentials": N.CRED_GMAIL, "alwaysOutputData": True,
         "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000},
        {"parameters": {"mode": "runOnceForAllItems", "jsCode": SLIM}, "id": "s", "name": "Keep what matters",
         "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [440, 0]},
    ]
    conns = {"Trigger": {"main": [[{"node": "Read their replies (all time)", "type": "main", "index": 0}]]},
             "Read their replies (all time)": {"main": [[{"node": "Keep what matters", "type": "main", "index": 0}]]}}
    try:
        ex = N.fire_once(NAME, nodes, conns, trigger_name="Trigger", max_wait=900)
        return [m for m in N.last_node_output(ex, "Keep what matters") if m.get("id")]
    finally:
        w = N.find_workflow(NAME)
        if w:
            N.api("DELETE", f"/workflows/{w['id']}")


def read_one(m):
    """Same reading as the daily Reply Handler, without any draft."""
    frm, subject = m.get("from") or "", m.get("subject") or ""
    text = RH.strip_quoted(m.get("text") or "")
    if RH.BOUNCE_FROM.search(frm) or RH.BOUNCE_SUBJ.search(subject):
        return {"category": "bounce"}
    if RH.AUTO.search(subject + " " + text[:600]) or RH.REACTION.search(m.get("text") or "") or not text:
        return {"category": "auto_reply"}
    r = RH.llm_read(text)
    cat = r.get("category") if r.get("category") in RH.CATS else ""
    if RH.NO.search(text):
        cat = "not_interested"
    prices = RH.verified_prices(r.get("prices"), text)
    if not cat:
        cat = "rates_given" if prices else ("question" if "?" in text else "unclear")
    if cat == "rates_given" and not prices:
        cat = "interested_no_rates"
    tg, nums = RH.contacts_from(text)
    contacts = [f"Telegram: @{h}" for h in tg]
    if nums and RH.re.search(r"whats\s?app|wa\.me", text, RH.re.I):
        contacts += [f"WhatsApp: {n}" for n in nums]
    us = r.get("us_audience", "")
    us = us if str(us) and RH.re.sub(r"\D", "", str(us)) and RH.re.sub(r"\D", "", str(us)) in RH.re.sub(r"\D", "", text) else ""
    return {"category": cat, "prices": prices, "contacts": contacts, "numbers": nums, "us_audience": us,
            "demands": r.get("demands", ""), "summary": r.get("summary", ""),
            "open_to_future": cat == "not_interested" and bool(RH.FUTURE.search(text))}


def main():
    emails = targets()
    print(f"People who replied at some point: {len(emails)}. Reading their full Gmail history through n8n ...", flush=True)
    T.take_run_lock(REGION, "backfill old replies")
    try:
        msgs = fetch(emails)
        print(f"Messages from them: {len(msgs)}. Reading each one with the free model ...", flush=True)
        st, sup = T.state(REGION), T.suppression(REGION)
        processed = T.load(T.state_file(REGION, "processed_messages.json"), [])
        per = {}
        for m in sorted(msgs, key=lambda x: str(x.get("date", ""))):
            e = RH.addr(m.get("from"))
            if e not in emails:
                continue
            per.setdefault(e, []).append((str(m.get("date", ""))[:10], read_one(m)))
            if m["id"] not in processed:
                processed.append(m["id"])        # the daily Reply Handler must not draft for these old messages again
        changed = []
        for e, reads in per.items():
            real = [(d, r) for d, r in reads if r["category"] not in ("auto_reply", "bounce")]
            if not real:
                continue
            rec = st.setdefault(e, {})
            before = rec.get("status")
            for d, r in real:
                if r["prices"]:
                    rec["price"] = "; ".join(dict.fromkeys(([rec["price"]] if rec.get("price") else []) + r["prices"]))
                for c in r["contacts"]:
                    if c not in rec.setdefault("contacts", []):
                        rec["contacts"].append(c)
                for n in r["numbers"]:
                    if n not in rec.setdefault("numbers", []):
                        rec["numbers"].append(n)
                if r["us_audience"]:
                    rec["us_audience"] = r["us_audience"]
            d_last, last = real[-1]
            note = " | ".join(x for x in [f"Earlier reply {d_last}: {last['summary']}" if last["summary"] else "",
                                          f"Demands: {last['demands']}" if last["demands"] else ""] if x)
            if note and note not in rec.setdefault("notes", []):
                rec["notes"].append(note)          # the sheet shows the last 3 notes
            if before in (None, "", "emailed", "draft_ready"):
                if last["category"] == "not_interested":
                    rec["status"], rec["open_to_future"] = "declined", last["open_to_future"]
                    sup.setdefault(e, ("declined, open to future " if last["open_to_future"] else "declined ") + d_last)
                else:
                    rec["status"], rec["reply_category"] = "talking", last["category"]
            T.log_event(rec, "old replies read (backfill)")
            changed.append({"email": e, "was": before, "now": rec.get("status"), "price": rec.get("price", ""),
                            "contacts": rec.get("contacts", []), "numbers": rec.get("numbers", [])})
        T.save_state(REGION, st)
        T.save_suppression(REGION, sup)
        T.save(T.state_file(REGION, "processed_messages.json"), processed[-5000:])
    finally:
        T.release_run_lock(REGION)
    print(json.dumps({"people_updated": len(changed), "details": changed}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
