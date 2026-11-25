# -*- coding: utf-8 -*-
"""Agent 3 · Reply Handler. See AGENT.md in this folder. Usage: python -I agent.py USA"""
import os, sys, re, json
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T
sys.path.insert(0, os.path.join(T.ROOT, "llm"))
try:
    import engine
except Exception:
    engine = None

ME = re.compile(re.escape(T.settings()["sender_email"]), re.I)
AUTO = re.compile(r"automatic reply|auto.?reply|autoreply|out of (the )?office|\booo\b|on vacation|on holiday|"
                  r"travell?ing|mail received|we have received your|received your (email|message)|"
                  r"will (get back|respond|reply) (to you )?(as soon|shortly|within)|currently away|away from (my|the) (desk|office)",
                  re.I)
BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster|mail delivery", re.I)
BOUNCE_SUBJ = re.compile(r"delivery status notification|undeliverable|address not found|delivery has failed|"
                         r"returned mail|failure notice", re.I)
NO = re.compile(r"not interested|no thanks|no thank you|unsubscribe|remove me|stop (emailing|contacting)|"
                r"not a (good )?fit|we.?ll pass|pass on this|do not contact|don.?t contact|not at this time", re.I)
CATS = {"rates_given", "interested_no_rates", "question", "not_interested", "auto_reply", "bounce", "unclear"}


QUOTE_START = re.compile(
    r"(\n\s*>|On [^\n]{0,200}?\n?[^\n]{0,160}?wrote:|Am [^\n]{0,160}schrieb|Le [^\n]{0,160}a .crit|"
    r"El [^\n]{0,160}escribi|Em [^\n]{0,160}escreveu|-{2,}\s*(Original Message|Urspr.ngliche Nachricht|Forwarded)|"
    r"\n\s*(From|Von|De|Da):\s[^\n]*@|\n_{5,}|\nSent from my )", re.I | re.S)
OURS = re.compile(re.escape(T.settings().get("telegram_handle", "@none").lstrip("@")) + "|" + re.escape(T.settings()["sender_email"].split("@")[0]), re.I)


def strip_quoted(text):
    t = text or ""
    m = QUOTE_START.search(t)
    return (t[:m.start()] if m else t).strip()


def quote_depth(text):
    """How many earlier messages are quoted inside this one (1 = a first reply, 2+ = ongoing chat)."""
    return len(re.findall(r"wrote:|schrieb|a .crit|escribi|escreveu|Urspr.ngliche Nachricht|Original Message",
                          text or "", re.I))


def contacts_from(text):
    """Telegram handles and real phone numbers from the creator's OWN words only (not quoted mail)."""
    # a handle needs a clear marker: "telegram: x", "telegram @x", "tg: @x", "tg @x". A bare "TG post" is not a handle.
    # t.me links inside a rate card are channels being sold, not the creator's contact, so they are skipped.
    handles = re.findall(r"\btelegram\b[\s:?\-]*(?:is\s+)?@?([A-Za-z][A-Za-z0-9_]{3,31})", text, re.I)
    handles += re.findall(r"\btg\b\s*[:\-]?\s*@([A-Za-z][A-Za-z0-9_]{3,31})", text, re.I)
    for line in text.splitlines():
        if not re.search(r"\d{2,}", line):                       # a t.me link on a line with no price = their contact
            handles += re.findall(r"t\.me/@?([A-Za-z][A-Za-z0-9_]{3,31})", line, re.I)
    handles += re.findall(r"(?<![\w/])@([A-Za-z][A-Za-z0-9_]{4,31})\b(?=[^\n]{0,40}\b(?:telegram|tg)\b)", text, re.I)
    handles = [h for h in dict.fromkeys(handles)
               if h.lower() not in ("https", "http", "www", T.settings().get("telegram_handle", "@none").lstrip("@").lower(), "telegram", "channel", "group", "post", "posts",
                                    "account", "username", "handle", "here", "please", "only", "chat")]
    phones = []
    for p in T.C.PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", p)
        if re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", p):        # a date, not a phone
            continue
        if len(digits) > 15:                                      # longer than any real phone: an id inside a link
            continue
        if re.search(re.escape(p.strip()) + r"[\w/?=&]", text) or re.search(r"[/=?&]" + re.escape(p.strip()), text):
            continue                                              # digits inside a URL
        if (p.strip().startswith("+") and len(digits) >= 8) or len(digits) >= 10:
            n = ("+" if p.strip().startswith("+") else "") + digits
            if n not in phones:
                phones.append(n)
    return handles, phones


FUTURE = re.compile(r"future|feel free to (email|reach|contact)|happy to hear from you|keep (us|me) in mind|"
                    r"keep in touch|another time|next (campaign|time)|fixed.?fee", re.I)
REACTION = re.compile(r"reacted via gmail", re.I)


def addr(s):
    m = T.C.EMAIL_RE.findall(s or "")
    return m[0].lower() if m else ""


def llm_read(text):
    """Free model reads the reply. Returns dict or {} on failure. Never trusted blindly (see verify)."""
    if engine is None:
        return {}
    system = ("You read replies from social media creators to an influencer marketing manager. "
              "Return ONLY a JSON object, no other text, with keys: "
              "category (one of rates_given, interested_no_rates, question, not_interested, unclear), "
              "prices (list of strings, each a deliverable and its price exactly as written in the message), "
              "whatsapp (string or empty), telegram (string or empty), phone (string or empty), "
              "us_audience (string or empty), demands (short string or empty), summary (one short sentence). "
              "Only use information that is literally in the message. If something is not there, leave it empty.")
    try:
        _, out = engine.smart(system, text[:6000], max_tokens=700)
        m = re.search(r"\{.*\}", out, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def verified_prices(prices, text):
    """Anti-invention: keep a price only if every number in it is literally in the reply."""
    keep = []
    flat = re.sub(r"[,\s]", "", text)
    for p in prices or []:
        nums = re.findall(r"\d[\d,.]*", str(p))
        if nums and all(re.sub(r"[,\s]", "", n).rstrip(".") in flat for n in nums):
            keep.append(str(p).strip())
    return keep


def draft_for(cat, first, subject, sig):
    hi = f"Hi {first}," if first else "Hi there,"
    subj = subject if subject.lower().startswith("re:") else "Re: " + subject
    if cat == "rates_given":
        body = (f"{hi}\n\nThanks a lot for sending your rates, that is really helpful.\n\n"
                "To match you with the right brand, could you share your average views on your last 10 videos "
                "and roughly what share of your audience is in the US?\n\n"
                "Also, the brands I work with often prefer to start with a smaller first collaboration, a lower fixed "
                "fee plus a bonus on results. What would be your best price for a first test collaboration, or for a "
                "package of two?\n\nI will take everything to the brand and come back to you.\n\n" + sig)
    elif cat == "interested_no_rates":
        body = (f"{hi}\n\nGreat to hear from you, thanks for getting back to me.\n\n"
                "Could you share your rate card, or your prices for a dedicated video and for a shorter mention? "
                "Your average views on recent videos and your US audience share would help me a lot too.\n\n"
                "Many of the brands I work with like performance based deals, a fixed fee plus a bonus on results. "
                "Let me know if that works for you.\n\n" + sig)
    elif cat == "question":
        body = (f"{hi}\n\nGood question. I am an independent partnerships manager, I work with several brands and "
                "match each creator to the right campaign. Once there is a fit I share the brand and the full brief "
                "before anything is agreed, and all terms are confirmed in writing.\n\n"
                "To see where you fit best, could you share your prices for a dedicated video and a shorter mention, "
                "and roughly what share of your audience is in the US?\n\n" + sig)
    elif cat == "not_interested":
        body = (f"{hi}\n\nNo problem at all, thanks for letting me know. If anything changes in the future, "
                "feel free to reach out.\n\n" + sig)
    else:
        return None
    return {"subject": subj, "body": body}


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    T.take_run_lock(region, "daily team")      # first agent of the line: a second run at the same time stops here
    T.start_new_day(region)
    tdir = T.region_dir(region, "today")
    for fn in os.listdir(tdir):                  # a new run starts clean: no old PASS can open the gate
        if fn.startswith("report_") or fn.startswith("0"):
            os.remove(os.path.join(tdir, fn))
    cfg = T.settings()
    st = T.state(region)
    processed = set(T.load(T.state_file(region, "processed_messages.json"), []))
    msgs = T.n8n_items(T.inbox_file(region, "gmail_recent.json"))

    by_thread = {r.get("thread_id"): e for e, r in st.items() if r.get("thread_id")}
    universe = {}
    out_json = T.load(os.path.join(T.ROOT, "output", f"Influencer_{region}.json"), {})
    for tab in ("outreaching", "ready"):
        for row in out_json.get(tab, []):
            if row.get("Email"):
                universe[row["Email"].lower()] = row

    events, skipped = [], []
    for m in msgs:
        mid = m.get("id")
        if not mid or mid in processed:
            continue
        frm = m.get("from") or ""
        if ME.search(frm) or "SENT" in (m.get("labelIds") or []):
            continue                                   # our own sent mail is the Recorder's business
        sender = addr(frm)
        subject = m.get("subject") or ""
        text = strip_quoted(m.get("text") or "")
        ev = {"message_id": mid, "thread_id": m.get("threadId"), "from": sender, "subject": subject,
              "date": m.get("date"), "excerpt": text[:1500]}

        if BOUNCE_FROM.search(frm) or BOUNCE_SUBJ.search(subject):
            failed = [e for e in T.C.emails_in(m.get("text") or "") if not ME.search(e) and not BOUNCE_FROM.search(e)]
            ev.update(category="bounce", matched_email=next((e for e in failed if e in universe or e in st), failed[0] if failed else ""))
            events.append(ev); continue

        matched = sender if (sender in universe or sender in st) else by_thread.get(m.get("threadId"), "")
        if st.get(matched, {}).get("alias_of"):          # a manager / second address: file it under the main row
            matched = st[matched]["alias_of"]
        if not matched:
            skipped.append({"message_id": mid, "from": sender, "subject": subject, "why": "not one of our influencers"})
            continue
        ev["matched_email"] = matched
        row = universe.get(matched, {})
        first = T.first_name(row.get("Username") or st.get(matched, {}).get("name", ""), matched)

        if AUTO.search(subject + " " + text[:600]) or REACTION.search(m.get("text") or ""):
            ev["category"] = "auto_reply"
        else:
            r = llm_read(text) if text else {}
            cat = r.get("category") if r.get("category") in CATS else ""
            if NO.search(text):
                cat = "not_interested"
            ev["prices"] = verified_prices(r.get("prices"), text)
            if not cat:
                cat = "rates_given" if ev["prices"] else ("question" if "?" in text else "unclear")
            if cat == "rates_given" and not ev["prices"]:
                cat = "interested_no_rates"
            ev["category"] = cat
            tg, nums = contacts_from(text)
            ev["numbers"] = nums
            ev["contacts"] = [f"Telegram: @{h}" for h in tg]
            if nums and re.search(r"whats\s?app|wa\.me", text, re.I):
                ev["contacts"] += [f"WhatsApp: {n}" for n in nums]
            if cat == "not_interested" and FUTURE.search(text):
                ev["open_to_future"] = True
            ev["ongoing_chat"] = quote_depth(m.get("text") or "") >= 2
            ev["us_audience"] = r.get("us_audience", "") if str(r.get("us_audience", "")) and \
                re.sub(r"\D", "", str(r.get("us_audience", ""))) in re.sub(r"\D", "", text) else ""
            ev["demands"] = r.get("demands", "")
            ev["summary"] = r.get("summary", "")
            d = draft_for(cat, first, subject, cfg["signature"])
            if m.get("has_image"):
                # rates or audience stats are often a screenshot: the free model cannot see it, the owner must open it
                ev["flag_for_ali"] = "sent a screenshot or file (rates or stats?), open the email"
                d = None
            if d and ev["ongoing_chat"]:
                ev["flag_for_ali"] = "ongoing conversation, reply yourself (no template draft)"
            elif d:
                ev["draft"] = dict(d, to=sender, thread_id=m.get("threadId"), reply_to_message_id=mid)
        events.append(ev)

    # one draft per conversation: only the newest message in a thread / from a person gets a draft
    newest = {}
    for e in events:
        k = e.get("thread_id") or e.get("matched_email")
        if k not in newest or str(e.get("date", "")) >= str(newest[k].get("date", "")):
            newest[k] = e
    for e in events:
        if e.get("draft") and newest.get(e.get("thread_id") or e.get("matched_email")) is not e:
            e.pop("draft")

    T.save(T.today_file(region, "03_reply_events.json"), {"events": events, "skipped": skipped,
                                                          "messages_seen": len(msgs)})
    counts = {}
    for e in events:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
    T.report("Agent 3 Reply Handler", "DONE", region=region, new_replies=len(events), by_category=counts,
             drafts=sum(1 for e in events if e.get("draft")), not_ours=len(skipped))


if __name__ == "__main__":
    main()
