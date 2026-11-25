# -*- coding: utf-8 -*-
"""Agent 4 · Recorder. See AGENT.md. Usage: python -I agent.py USA sync|finalize"""
import os, sys, re, json, email.utils
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T
import build_region as B

ME = re.compile(re.escape(T.settings()["sender_email"]), re.I)
# Gmail being busy is not the influencer's fault: such a send is retried on a later run, never marked failed
TEMPORARY = re.compile(r"rate.?limit|quota|429|403|forbidden|too many|backend error|500|502|503|timeout|ETIMEDOUT|ECONNRESET|no id back", re.I)
EDIT_FIELDS = ["Email", "Price", "Contacts", "Number", "Notes", "Status"]
COLS = T.C.COLUMNS
CAT_LABEL = {"rates_given": "sent rates", "interested_no_rates": "interested, no rates yet",
             "question": "asked a question", "unclear": "replied, read it"}


def sval(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def msg_date(m):
    d = sval(m.get("date"))
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    try:
        return email.utils.parsedate_to_datetime(d).date().isoformat()
    except Exception:
        return T.TODAY


# ------------------------------------------------------------------ human edits from the sheet
def norm(field, v):
    """Compare by meaning, not formatting: Google Sheets may drop a leading +, add spaces,
    or show '#ERROR!' for a value it misread. None of that is the owner's edit."""
    s = sval(v).lstrip("'=")
    if s.startswith("#ERROR") or s.startswith("#VALUE") or s.startswith("#NAME"):
        return None
    if field == "Number":
        return ",".join(sorted(re.sub(r"\D", "", p) for p in re.split(r"[,;/]", s) if re.sub(r"\D", "", p)))
    return re.sub(r"\s+", " ", s).strip()


def same(field, a, b):
    na, nb = norm(field, a), norm(field, b)
    return na is None or nb is None or na == nb


def read_human_edits(region):
    snap_out = T.n8n_items(T.inbox_file(region, "sheet_outreaching.json"))
    snap_ready = T.n8n_items(T.inbox_file(region, "sheet_ready.json"))
    last_path = T.state_file(region, "last_published.json")
    last = T.load(last_path, None)
    edits = T.load(T.state_file(region, "manual_edits.json"), {})
    if last is None:                       # first run: what is in the sheet now is our baseline
        return edits, 0, len(snap_out) + len(snap_ready)
    found = 0
    for tab, snap in (("out", snap_out), ("ready", snap_ready)):
        for row in snap:
            row = {k: sval(v) for k, v in row.items()}
            if not row.get("Username") and not row.get("Social Profile"):
                continue
            key = T.row_key(row)
            pub = last.get(key)
            if pub is None:                # a row the owner added by hand
                e = edits.setdefault(key, {})
                for f in ["Username", "Social Profile"] + EDIT_FIELDS:
                    if row.get(f):
                        e[f] = row[f]
                e["_tab"], e["_added_by_ali"] = tab, True
                found += 1
                continue
            for f in EDIT_FIELDS:
                if not same(f, row.get(f, ""), pub.get(f, "")):
                    edits.setdefault(key, {})[f] = row.get(f, "")
                    found += 1
            if pub.get("_tab") and pub["_tab"] != tab:
                edits.setdefault(key, {})["_tab"] = tab
                found += 1
    T.save(T.state_file(region, "manual_edits.json"), edits)
    return edits, found, len(snap_out) + len(snap_ready)


# ------------------------------------------------------------------ gmail sent mail + replies
def apply_gmail_sent(region, st, universe):
    marked = 0
    for m in T.n8n_items(T.inbox_file(region, "gmail_recent.json")):
        if not (ME.search(m.get("from") or "") or "SENT" in (m.get("labelIds") or [])):
            continue
        for rcpt in T.C.emails_in(m.get("to") or ""):
            if ME.search(rcpt) or rcpt not in universe:
                continue
            rec = st.setdefault(rcpt, {"name": universe[rcpt].get("Username", ""), "status": "emailed"})
            ids = rec.setdefault("sent_ids", [])
            if m.get("id") in ids:
                continue
            ids.append(m.get("id"))
            d = msg_date(m)
            rec.setdefault("first_sent", d)
            rec["last_sent"] = max(rec.get("last_sent", d), d)
            rec.setdefault("thread_id", m.get("threadId"))
            if rec.get("status") in (None, "", "draft_ready", "emailed"):
                rec["status"] = "emailed"
                rec["followups"] = max(0, len(ids) - 1)
            T.log_event(rec, "sent mail seen in Gmail")
            marked += 1
    return marked


def apply_reply_events(region, st, sup):
    data = T.load(T.today_file(region, "03_reply_events.json"), {})
    if data and not data.get("manager_checked"):
        raise SystemExit("reply events not checked by Manager 3")
    processed = T.load(T.state_file(region, "processed_messages.json"), [])
    applied = 0
    for e in data.get("events", []):
        em = (e.get("matched_email") or "").lower()
        processed.append(e["message_id"])
        if not em:
            continue
        rec = st.setdefault(em, {"status": "emailed"})
        cat = e["category"]
        if cat == "bounce":
            rec["status"] = "bounced"; sup[em] = "bounced " + T.TODAY
        elif cat == "auto_reply":
            T.log_event(rec, "auto reply received (ignored)")
            continue
        elif cat == "not_interested":
            rec["status"] = "declined"
            rec["open_to_future"] = bool(e.get("open_to_future"))
            sup[em] = ("declined, open to future " if rec["open_to_future"] else "declined ") + T.TODAY
            if e.get("excerpt"):
                rec.setdefault("notes", []).append(f"Declined {T.TODAY}: " + " ".join(e["excerpt"].split())[:160])
        else:
            rec["status"] = "talking"
            rec["reply_category"] = cat
            if e.get("prices"):
                rec["price"] = "; ".join(dict.fromkeys(([rec["price"]] if rec.get("price") else []) + e["prices"]))
            for c in e.get("contacts", []):
                rec.setdefault("contacts", [])
                if c not in rec["contacts"]:
                    rec["contacts"].append(c)
            for n in e.get("numbers", []):
                rec.setdefault("numbers", [])
                if n not in rec["numbers"]:
                    rec["numbers"].append(n)
            note = " | ".join(x for x in [
                f"Replied {T.TODAY}: {e.get('summary') or CAT_LABEL.get(cat, cat)}",
                f"US audience: {e['us_audience']}" if e.get("us_audience") else "",
                f"Demands: {e['demands']}" if e.get("demands") else "",
                e.get("flag_for_ali", "")] if x)
            rec.setdefault("notes", []).append(note)
        T.log_event(rec, "reply: " + cat)
        applied += 1
    T.save(T.state_file(region, "processed_messages.json"), processed[-5000:])
    return applied


def apply_send_results(region, st):
    res = T.n8n_items(T.today_file(region, "06_send_results.json"))
    done = {"sent": 0, "drafted": 0, "followups": 0, "reply_drafts": 0, "errors": 0}
    for r in res:
        em = (r.get("email") or "").lower()
        act = r.get("action")
        if not em or act in (None, "none"):
            continue
        if r.get("error") or not r.get("gmail_id"):
            done["errors"] += 1
            err = str(r.get("error") or "no id back from Gmail")
            if TEMPORARY.search(err):
                # Gmail was busy (rate limit / quota): nothing is written, so the person is simply tried on a later run
                done.setdefault("retry_later", []).append(em)
                continue
            rec = st.setdefault(em, {"name": r.get("name", "")})
            if act == "send_new":
                rec["status"] = "send_failed"            # a real address problem: row goes to the bottom for the owner
            rec.setdefault("notes", []).append(f"{T.TODAY}: {act} failed: {err[:120]}")
            continue
        rec = st.setdefault(em, {"name": r.get("name", "")})
        if act == "send_new":
            rec.update(status="emailed", first_sent=T.TODAY, last_sent=T.TODAY, followups=0,
                       message_id=r["gmail_id"], thread_id=r.get("thread_id"), subject=r.get("subject"))
            rec.setdefault("sent_ids", []).append(r["gmail_id"]); done["sent"] += 1
        elif act == "draft_new":
            rec.update(status="draft_ready", draft_date=T.TODAY, subject=r.get("subject"))
            done["drafted"] += 1
        elif act == "send_followup":
            rec["followups"] = rec.get("followups", 0) + 1
            rec["last_sent"] = T.TODAY; done["followups"] += 1
        elif act == "draft_followup":
            rec["followups"] = rec.get("followups", 0) + 1
            rec.setdefault("notes", []).append(f"{T.TODAY}: follow-up draft ready in Gmail"); done["followups"] += 1
        elif act == "draft_reply":
            rec.setdefault("notes", []).append(f"{T.TODAY}: negotiation reply draft ready in Gmail")
            done["reply_drafts"] += 1
        T.log_event(rec, act)
    return done


# ------------------------------------------------------------------ rebuild the two tabs
def rebuild(region, st, sup, edits):
    a = B.assemble(region)
    rows = a["merged"]
    seen = {T.row_key(r) for r in rows}
    for key, e in edits.items():            # rows the owner added by hand
        if e.get("_added_by_ali") and key not in seen:
            rows.append({"Username": e.get("Username", ""), "Social Profile": e.get("Social Profile", ""),
                         "Email": "", "Price": "", "Contacts": "", "Number": "", "Notes": "Added by the owner",
                         "Status": "To contact", "_tab": e.get("_tab", "out")})
    for r in rows:
        key = T.row_key(r)
        man = edits.get(key, {})
        if man.get("Email"):
            r["Email"] = man["Email"].strip()
            if r["Status"].startswith("Needs email") or not r["Status"]:
                r["Status"] = "To contact"
        em = r["Email"].lower()
        rec = st.get(em) if em else None
        if rec:
            s = rec.get("status")
            if s == "talking":
                r["_tab"] = "ready"
                r["Status"] = "Talking - " + CAT_LABEL.get(rec.get("reply_category"), "replied")
            elif s == "declined":
                r["_tab"] = "out"
                r["Status"] = ("Declined for now - open to future offers" if rec.get("open_to_future")
                               else "Declined - do not contact")
            elif s == "bounced":
                r["_tab"], r["Status"] = "out", "Bounced - needs new email"
            elif s == "send_failed":
                r["_tab"], r["Status"] = "out", "Email failed - needs new email"
            elif s == "draft_ready" and r["_tab"] != "ready":
                r["Status"] = f"Draft ready in Gmail ({rec.get('draft_date', '')})"
            elif s == "emailed" and r["_tab"] != "ready":
                r["Status"] = f"Emailed {rec.get('last_sent', rec.get('first_sent', ''))} - waiting reply" + \
                              (" (follow-up sent)" if rec.get("followups") else "")
            if rec.get("price") and not r["Price"]:
                r["Price"] = rec["price"]
            if rec.get("contacts"):
                merged_c, keys = [], set()
                for c in [x for x in r["Contacts"].split("; ") if x] + rec["contacts"]:
                    k = re.sub(r"^(telegram|whatsapp|discord):\s*|https?://|t\.me/|@|\s", "", c.lower())
                    if k not in keys:
                        keys.add(k); merged_c.append(c)
                r["Contacts"] = "; ".join(merged_c)
            if rec.get("numbers"):
                r["Number"] = ", ".join(dict.fromkeys([x for x in r["Number"].split(", ") if x] + rec["numbers"]))
            if rec.get("notes"):
                r["Notes"] = " | ".join(x for x in [" | ".join(rec["notes"][-3:]), r["Notes"]] if x)
        elif em and em in sup:
            r["_tab"], r["Status"] = "out", "Declined - do not contact"
        for f in ("Price", "Contacts", "Number", "Notes", "Status"):     # human edits always win
            if f in man:
                r[f] = man[f]
        if "_tab" in man:
            r["_tab"] = man["_tab"]
        if r["_tab"] != "ready" and r["Number"] and r["Status"] in ("To contact", "") and "Status" not in man:
            r["_tab"], r["Status"] = "ready", "Has contact number - reach directly"
    ready = [r for r in rows if r["_tab"] == "ready"]
    out = [r for r in rows if r["_tab"] != "ready"]
    out.sort(key=lambda r: B.status_rank(r["Status"]))     # missing emails at the bottom

    def table(rs):
        return [dict({"No:": i}, **{c: r.get(c, "") for c in COLS[1:]}) for i, r in enumerate(rs, 1)]

    t_out, t_ready = table(out), table(ready)
    T.save(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"),
           {"region": region, "outreaching": t_out, "ready": t_ready})
    return t_out, t_ready, len(rows)


def publish_files(region, t_out, t_ready):
    T.save(os.path.join(T.ROOT, "output", f"sheet_{region}_outreaching.json"), t_out)
    T.save(os.path.join(T.ROOT, "output", f"sheet_{region}_ready.json"), t_ready)
    last = {}
    for tab, rows in (("out", t_out), ("ready", t_ready)):
        for r in rows:
            last[T.row_key(r)] = dict({f: sval(r.get(f, "")) for f in EDIT_FIELDS}, _tab=tab)
    T.save(T.state_file(region, "last_published.json"), last)
    # the xlsx is only a local backup copy: if the owner has it open in Excel, Windows locks it. Never stop the line for that.
    try:
        B.write_output([{c: r[c] for c in COLS} for r in t_ready], [{c: r[c] for c in COLS} for r in t_out],
                       region, os.path.join(T.ROOT, "output", f"Influencer {region}.xlsx"))
        return ""
    except PermissionError:
        return "Influencer USA.xlsx is open in Excel, so the local copy was not refreshed (Google Sheet is fine)"


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    shift = sys.argv[2] if len(sys.argv) > 2 else "sync"
    st, sup = T.state(region), T.suppression(region)
    out_json = T.load(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"), {})
    universe = {r["Email"].lower(): r for tab in ("outreaching", "ready") for r in out_json.get(tab, []) if r.get("Email")}
    info = {}
    if shift == "sync":
        edits, n_edits, sheet_rows = read_human_edits(region)
        info["sheet_rows_read"] = sheet_rows
        info["human_edits_found"] = n_edits
        info["sent_mail_recorded"] = apply_gmail_sent(region, st, universe)
        info["replies_applied"] = apply_reply_events(region, st, sup)
    else:
        edits = T.load(T.state_file(region, "manual_edits.json"), {})
        info.update(apply_send_results(region, st))
    T.save_state(region, st)
    T.save_suppression(region, sup)
    t_out, t_ready, total = rebuild(region, st, sup, edits)
    if shift == "finalize":
        note = publish_files(region, t_out, t_ready)
        if note:
            info["note"] = note
    info.update(outreaching_rows=len(t_out), ready_rows=len(t_ready), total_influencers=total,
                to_contact=sum(1 for r in t_out if r["Status"] == "To contact"))
    T.report(f"Agent 4 Recorder {shift}", "DONE", region=region, **info)


if __name__ == "__main__":
    main()
