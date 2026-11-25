# -*- coding: utf-8 -*-
"""
EMPLOYEE: Region Builder  (raw sources -> "Influencer <REGION> raw" -> "Influencer <REGION>")
-------------------------------------------------------------------------------------------
JOB DESCRIPTION
  1. Collect every influencer for one region from all of the owner's sources (Drive country
     file + partner database, YouTube profiles, pipeline and sent log).
  2. Save them merged as the INPUT file  "Influencer <REGION> raw.xlsx" (one row per
     source record, with a Source column, nothing cleaned yet).
  3. Clean + de-duplicate into the standard columns and split into the OUTPUT file
     "Influencer <REGION>.xlsx" with 2 tabs:
       - "Ready to work"        : already talking (replied in Gmail / pipeline Replied or
                                  Interested) OR already has a contact number.
                                  These are NOT cold-emailed again.
       - "Outreaching <REGION>" : everyone else.
            Status "Emailed - no reply yet"  -> follow-up stage, no new first email
            Status "To contact"              -> gets outreach
            Status "Needs email"             -> Apify, then the owner by hand
            Status "Bounced - needs new email"
  Cost: 0 Claude tokens. Gmail knowledge comes from data/gmail_scan.json (n8n Inbox Watcher).

USAGE
  python -I build_region.py USA
"""
import sys, os, re, csv, json, collections
import openpyxl
from openpyxl.styles import Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import clean_influencers as C

PARTNER = os.path.join(ROOT, "data", "raw", "partner")   # optional extra sources
REGIONS = {
    "USA": {
        "drive_files": [os.path.join(ROOT, "data", "raw", "USA", "USAInfluencers.xlsx")],
        "partner": False,  # set True if you have partner files
        "yt_countries": {"US", ""},
    },
}
COLUMNS = C.COLUMNS
READY_PIPELINE = {"replied", "interested", "terms sent", "agreed", "live"}


def s(v):
    return "" if v is None else str(v).strip()


def pkey(url):
    u = s(url).lower()
    u = re.sub(r"^https?://", "", u).replace("www.", "").split("?")[0].rstrip("/")
    return u[:-len("/videos")] if u.endswith("/videos") else u


# ---------------------------------------------------------------- source loaders
def load_drive(path, region):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            if r and s(r[0]):
                raw = {"Source": "Drive: " + os.path.basename(path), "Name": s(r[0])}
                for i, k in enumerate(["Instagram", "YouTube", "Twitch", "TikTok", "Email", "Country", "Extra"], 1):
                    raw[k] = s(r[i]) if len(r) > i else ""
                yield raw, C.clean_row(r, region)


def _row(name, profile, email, notes, contacts="", number="", price="", platform=""):
    return {"Username": name, "Social Profile": profile, "Email": email, "Price": price,
            "Contacts": contacts, "Number": number, "Notes": " | ".join(n for n in notes if n),
            "Status": "To contact" if email else "Needs email", "_platform": platform}


def load_partner_master():
    p = os.path.join(PARTNER, "archive", "1_Influencer_Database_UPDATED.xlsx")
    ws = openpyxl.load_workbook(p, read_only=True, data_only=True)["MASTER (all)"]
    rows = list(ws.iter_rows(values_only=True))
    h = [s(x) for x in rows[0]]
    for r in rows[1:]:
        d = {h[i]: s(r[i]) for i in range(min(len(h), len(r)))}
        if not d.get("Name"):
            continue
        raw = dict({"Source": "Partner MASTER"}, **d)
        emails = C.emails_in(d.get("Email (public)", "") + " " + d.get("Second email", ""))
        contacts, extra_profiles = [], []
        for col in ("Instagram", "X / Twitter", "Other (TG/Discord/YT/link)"):
            for u in C.URL_RE.findall(d.get(col, "").replace("[", " ").replace("]", " ").replace("'", " ")):
                url = C.norm_url(u)
                kind = C.classify(url)
                if kind in ("Telegram", "WhatsApp"):
                    contacts.append(kind + ": " + url)
                elif "discord" in url.lower():
                    contacts.append("Discord: " + url)
                elif url:
                    extra_profiles.append(f"{kind}: {url}")
        notes = []
        if len(emails) > 1: notes.append("Alt emails: " + ", ".join(emails[1:]))
        if d.get("Followers / Subs"): notes.append("Followers: " + d["Followers / Subs"])
        if d.get("Niche / Category"): notes.append("Niche: " + d["Niche / Category"])
        if d.get("Already promotes (brands)"): notes.append("Promotes: " + d["Already promotes (brands)"])
        if d.get("US focus?"): notes.append("US focus: " + d["US focus?"])
        if extra_profiles: notes.append("Also on: " + " | ".join(extra_profiles))
        row = _row(d["Name"], C.norm_url(d.get("Profile URL", "")), emails[0] if emails else "", notes,
                   "; ".join(dict.fromkeys(contacts)), platform=d.get("Platform", ""))
        if d.get("Outreach"):
            row["_outreach"] = d["Outreach"] + (" " + d["Outreach date"] if d.get("Outreach date") else "")
        yield raw, row


def load_us_profiles(countries):
    p = os.path.join(PARTNER, "engine", "us_profiles_all.json")
    for x in json.load(open(p, encoding="utf-8")):
        if s(x.get("channel_country")).upper() not in countries:
            continue
        c = x.get("contacts") or {}
        emails = C.emails_in(" ".join((c.get("emails") or []) + (x.get("video_emails") or [])))
        contacts = [f"Telegram: {t}" for t in c.get("telegram") or []] + \
                   [f"WhatsApp: {w}" for w in c.get("whatsapp") or []]
        nums = [n for w in (c.get("whatsapp") or []) for n in C.phones_in(w)]
        notes = [f"Subscribers: {x.get('subs')}" if x.get("subs") else "",
                 "Niche: " + s(x.get("niche")) if x.get("niche") else "",
                 "Promotes: " + ", ".join(x.get("brands") or []) if x.get("brands") else "",
                 "Location: " + s(x.get("channel_country")) if x.get("channel_country") else ""]
        if len(emails) > 1: notes.append("Alt emails: " + ", ".join(emails[1:]))
        raw = {"Source": "Partner YouTube profiles", "Name": s(x.get("title")), "Profile URL": s(x.get("url")),
               "Email": ", ".join(emails), "Contacts": json.dumps(c, ensure_ascii=False),
               "Country": s(x.get("channel_country")), "Subscribers": s(x.get("subs"))}
        yield raw, _row(s(x.get("title")), C.norm_url(s(x.get("url"))), emails[0] if emails else "", notes,
                        "; ".join(contacts), ", ".join(nums), platform="YouTube")


def load_pipeline():
    p = os.path.join(PARTNER, "PARTNER_MASTER.xlsx")
    rows = list(openpyxl.load_workbook(p, read_only=True, data_only=True)["Pipeline"].iter_rows(values_only=True))
    h = [s(x) for x in rows[0]]
    out = {}
    for r in rows[1:]:
        d = {h[i]: s(r[i]) for i in range(min(len(h), len(r)))}
        emails = C.emails_in(d.get("Contact", ""))
        phones = C.phones_in(re.sub(C.EMAIL_RE, " ", d.get("Contact", "")))
        rec = {"name": d.get("Creator", ""), "profile": C.norm_url(d.get("Channel", "")),
               "status": d.get("Status", ""), "rate": d.get("Rate", ""), "deal": d.get("Deal Type", ""),
               "last": d.get("Last Contact", ""), "next": d.get("Next Step", ""), "notes": d.get("Notes", ""),
               "us": d.get("US %", ""), "phones": phones, "raw": dict({"Source": "Partner PIPELINE"}, **d)}
        for e in emails:
            out[e] = rec
        if rec["profile"]:
            out[pkey(rec["profile"])] = rec
    return out


def load_sentlog():
    p = os.path.join(PARTNER, "Outreach_Sent_Log.csv")
    out = {}
    for d in csv.DictReader(open(p, encoding="utf-8")):
        e = s(d.get("email")).lower()
        if e:
            out[e] = d
    return out


def load_gmail():
    p = os.path.join(ROOT, "data", "gmail_scan.json")
    if not os.path.exists(p):
        return set(), set(), False
    g = json.load(open(p, encoding="utf-8"))
    return set(g.get("contacted", [])), set(g.get("replied", [])), True


# ---------------------------------------------------------------- merge + split
def merge(rows):
    seen, out, dup = {}, [], 0
    for row in rows:
        keys = [k for k in (row["Email"], pkey(row["Social Profile"])) if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit is None:
            out.append(row)
        else:
            dup += 1
            for col in ("Email", "Social Profile", "Contacts", "Number", "Price"):
                if not hit[col] and row[col]:
                    hit[col] = row[col]
                elif col in ("Contacts", "Number") and row[col] and row[col] not in hit[col]:
                    hit[col] = (hit[col] + "; " + row[col]).strip("; ")
            for part in row["Notes"].split(" | "):
                if part and part not in hit["Notes"]:
                    hit["Notes"] = (hit["Notes"] + " | " + part).strip(" |")
            if row.get("_outreach") and not hit.get("_outreach"):
                hit["_outreach"] = row["_outreach"]
            row = hit
        for k in [k for k in (row["Email"], pkey(row["Social Profile"])) if k]:
            seen[k] = row
    return out, dup


def load_enriched():
    p = os.path.join(ROOT, "data", "enriched_emails.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


ENRICHED = load_enriched()


def classify(row, pipeline, sentlog, g_contacted, g_replied):
    if not row["Email"]:
        hit = ENRICHED.get(pkey(row["Social Profile"]))
        if hit and hit.get("phone") and hit["phone"] not in row["Number"]:
            row["Number"] = ", ".join(x for x in [row["Number"], hit["phone"]] if x)
        if hit and hit.get("email"):
            row["Email"] = hit["email"]
            note = "Email found: " + hit["source"] + (" | Alt emails: " + ", ".join(hit["alt"]) if hit.get("alt") else "")
            row["Notes"] = " | ".join(x for x in [row["Notes"].replace(
                "No email yet, check YouTube About / contact", "").strip(" |"), note] if x)
        elif hit:
            row["_free_checked"] = hit["source"]
    e = row["Email"].lower()
    alt = [x.strip().lower() for x in re.findall(r"Alt emails: ([^|]+)", row["Notes"])
           for x in x.split(",")]
    allmail = [x for x in [e] + alt if x]
    pr = next((pipeline[k] for k in allmail + [pkey(row["Social Profile"])] if k and k in pipeline), None)
    if pr:
        if pr["rate"] and not row["Price"]: row["Price"] = pr["rate"]
        if pr["phones"]:
            row["Number"] = ", ".join(dict.fromkeys([x for x in row["Number"].split(", ") if x] + pr["phones"]))
        bits = [f"Pipeline: {pr['status']}", f"Last contact {pr['last']}" if pr["last"] else "",
                f"Deal: {pr['deal']}" if pr["deal"] else "", f"US%: {pr['us']}" if pr["us"] else "",
                f"Next: {pr['next']}" if pr["next"] else "", pr["notes"]]
        row["Notes"] = " | ".join(x for x in [" | ".join(b for b in bits if b), row["Notes"]] if x)
    replied_gmail = any(x in g_replied for x in allmail)
    sl = next((sentlog[x] for x in allmail if x in sentlog), None)
    replied_log = bool(sl and s(sl.get("replied")))
    pstat = (pr["status"].lower() if pr else "")

    if replied_gmail or replied_log or pstat in READY_PIPELINE:
        row["Status"] = "Talking - " + (pr["status"] if pstat in READY_PIPELINE else "replied in Gmail")
        return "ready"
    if row["Number"]:
        row["Status"] = "Has contact number - reach directly"
        return "ready"
    if pstat == "bounced":
        row["Status"] = "Bounced - needs new email"
        return "out"
    emailed = any(x in g_contacted for x in allmail) or sl is not None or pstat == "contacted" \
        or bool(row.get("_outreach"))
    if row["Email"] and emailed:
        row["Status"] = "Emailed - no reply yet"
    elif row["Email"]:
        row["Status"] = "To contact"
    else:
        plat = (row.get("_platform") or "").lower() or row["Social Profile"].lower()
        if "youtube" in plat:
            row["Status"] = "Needs email - manual (YouTube View email button)" if row.get("_free_checked") \
                else "Needs email - YouTube check pending"
        elif any(p in plat for p in ("instagram", "tiktok", "twitch", "kick")):
            row["Status"] = "Needs email - manual (Apify found none)" if row.get("_free_checked") \
                else "Needs email - Apify"
        else:
            row["Status"] = "Needs email - manual"
    return "out"


def write_raw(raws, path):
    cols = []
    for r in raws:
        for k in r:
            if k not in cols:
                cols.append(k)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Raw (all sources)"
    ws.append(cols)
    for c in ws[1]: c.font = Font(bold=True)
    for r in raws:
        ws.append([r.get(k, "") for k in cols])
    ws.freeze_panes = "A2"
    wb.save(path)


def write_output(ready, out, region, path):
    wb = openpyxl.Workbook()
    hf, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3864")
    widths = [6, 26, 48, 34, 14, 34, 20, 70, 30]
    for i, (title, rows) in enumerate([("Outreaching " + region, out), ("Ready to work", ready)]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title[:31]
        ws.append(COLUMNS)
        for c, w in zip(ws[1], widths):
            c.font, c.fill = hf, fill
            ws.column_dimensions[c.column_letter].width = w
        ws.freeze_panes = "A2"
        for n, r in enumerate(rows, 1):
            ws.append([n] + [r[c] for c in COLUMNS[1:]])
    wb.save(path)


def assemble(region):
    """All sources -> merged, cleaned, classified rows. Each row gets row['_tab'] = 'ready' | 'out'.
    Used by main() and by the Recorder agent (which then overlays the team's daily state)."""
    cfg = REGIONS[region]
    raws, rows = [], []
    for f in cfg["drive_files"]:
        for raw, row in load_drive(f, region):
            raws.append(raw); rows.append(row)
    if cfg.get("partner"):
        for loader in (load_partner_master, lambda: load_us_profiles(cfg["yt_countries"])):
            for raw, row in loader():
                raws.append(raw); rows.append(row)
        pipeline, sentlog = load_pipeline(), load_sentlog()
        for rec in {id(v): v for v in pipeline.values()}.values():
            raws.append(rec["raw"])
        for d in sentlog.values():
            raws.append(dict({"Source": "Partner sent log"}, **d))
    else:
        pipeline, sentlog = {}, {}
    g_contacted, g_replied, have_gmail = load_gmail()
    merged, dup = merge(rows)
    for r in merged:
        r["_tab"] = classify(r, pipeline, sentlog, g_contacted, g_replied)
    return {"raws": raws, "rows_before_merge": len(rows), "merged": merged, "dup": dup, "have_gmail": have_gmail,
            "g_contacted": g_contacted}


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else "USA").upper()
    a = assemble(region)
    raws, merged, dup, have_gmail = a["raws"], a["merged"], a["dup"], a["have_gmail"]
    rows = [None] * a["rows_before_merge"]
    ready = [r for r in merged if r["_tab"] == "ready"]
    out = [r for r in merged if r["_tab"] != "ready"]
    _finish(region, raws, rows, merged, dup, have_gmail, ready, out)


def status_rank(status):
    """Sheet order: people we can email first, people we are waiting on next, closed rows,
    and at the very BOTTOM every row that needs a (new) email from the owner: no email, bounced, or failed to send."""
    s_ = status.lower()
    if s_.startswith("to contact"): return 0
    if s_.startswith("draft ready"): return 1
    if s_.startswith("emailed"): return 2
    if s_.startswith("declined"): return 3
    if s_.startswith("needs email"): return 8
    if s_.startswith("bounced") or s_.startswith("email failed"): return 8
    return 3


def _finish(region, raws, rows, merged, dup, have_gmail, ready, out):
    out.sort(key=lambda r: status_rank(r["Status"]))
    os.makedirs(os.path.join(ROOT, "data", region), exist_ok=True)
    raw_path = os.path.join(ROOT, "data", region, f"Influencer {region} raw.xlsx")
    out_path = os.path.join(ROOT, "output", f"Influencer {region}.xlsx")
    write_raw(raws, raw_path)
    write_output(ready, out, region, out_path)
    raw_cols = list(dict.fromkeys(k for r in raws for k in r))
    json.dump([{k: s(r.get(k, "")) for k in raw_cols} for r in raws],
              open(os.path.join(ROOT, "output", f"Influencer_{region}_raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    json.dump({"region": region,
               "outreaching": [dict({"No:": i}, **{c: r[c] for c in COLUMNS[1:]}) for i, r in enumerate(out, 1)],
               "ready": [dict({"No:": i}, **{c: r[c] for c in COLUMNS[1:]}) for i, r in enumerate(ready, 1)]},
              open(os.path.join(ROOT, "output", f"Influencer_{region}.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    st = collections.Counter(r["Status"] for r in out)
    rd = collections.Counter(r["Status"] for r in ready)
    print(json.dumps({
        "region": region, "gmail_scan_used": have_gmail,
        "raw_records_all_sources": len(raws), "influencer_rows_before_merge": len(rows),
        "duplicates_merged": dup, "unique_influencers": len(merged),
        "ready_to_work": len(ready), "ready_breakdown": dict(rd),
        "outreaching": len(out), "outreaching_breakdown": dict(st),
        "input_file": raw_path, "output_file": out_path}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
