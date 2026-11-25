# -*- coding: utf-8 -*-
"""
EMPLOYEE: Data Cleaner  (raw country file -> clean outreach sheet)
------------------------------------------------------------------
JOB DESCRIPTION
  Takes the owner's rough, unformatted influencer file for one country and turns it
  into the standard clean format, ready for outreach. Same rules every time.
  Reports to : the n8n Outreach Manager workflow.
  Cost       : 0 Claude tokens, no API calls (pure deterministic rules).

RAW LAYOUT IT UNDERSTANDS (no header row)
  name | instagram | youtube | twitch | tiktok | email | country | extra
  extra = other links (IG / X / Facebook / VK), "DM", phone numbers, t.me Telegram

CLEAN OUTPUT COLUMNS (both tabs)
  No: | Username | Social Profile | Email | Price | Contacts | Number | Notes | Status
  Status: "To contact" (has email) or "Needs email" (enricher / the owner fills it)

RULES
  - Several emails in one cell -> first valid one is Email, the rest go to Notes.
  - Emoji flags and junk around emails are dropped.
  - "USA, Mexico" -> stays in this country's file, "Location: USA, Mexico" in Notes.
  - Telegram (t.me) and "DM" go to Contacts, phone numbers go to Number.
  - Duplicates (same email, or same profile link) are merged into one row.
  - Social Profile = main channel (YouTube > Instagram > TikTok > Twitch);
    any other profiles are listed in Notes.

USAGE
  python -I clean_influencers.py <raw.xlsx> <REGION> <out.xlsx> [out.json]
"""
import sys, re, json, collections
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+\.[A-Za-z]{2,}(?:/[^\s,;]*)?", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
COLUMNS = ["No:", "Username", "Social Profile", "Email", "Price", "Contacts", "Number", "Notes", "Status"]


def s(v):
    return "" if v is None else str(v).strip()


def norm_url(u):
    u = u.strip().strip(".,;")
    if not u:
        return ""
    if not u.lower().startswith("http"):
        u = "https://" + u
    if "profile.php" not in u:          # facebook profile.php needs its ?id=
        u = u.split("?")[0]
    u = u.rstrip("/")
    if u.endswith("/videos"):
        u = u[: -len("/videos")]
    return u


def classify(url):
    l = url.lower()
    for key, name in (("t.me/", "Telegram"), ("telegram.", "Telegram"), ("wa.me", "WhatsApp"),
                      ("whatsapp", "WhatsApp"), ("instagram.com", "Instagram"), ("youtube.com", "YouTube"),
                      ("youtu.be", "YouTube"), ("tiktok.com", "TikTok"), ("twitch.tv", "Twitch"),
                      ("x.com", "X"), ("twitter.com", "X"), ("facebook.com", "Facebook"), ("vk.com", "VK")):
        if key in l:
            return name
    return "Link"


def emails_in(text):
    out = []
    for e in EMAIL_RE.findall(text or ""):
        e = e.strip(".").lower()
        if re.search(r"\.(png|jpe?g|gif|webp)$", e):
            continue
        if e not in out:
            out.append(e)
    return out


def phones_in(text):
    out = []
    for p in PHONE_RE.findall(text or ""):
        digits = re.sub(r"\D", "", p)
        if 7 <= len(digits) <= 15 and digits not in out:
            out.append(("+" if p.strip().startswith("+") else "") + digits)
    return out


def clean_row(r, region):
    r = list(r) + [None] * (8 - len(r))
    name = s(r[0])
    profiles = []  # (platform, url)
    for idx, plat in ((2, "YouTube"), (1, "Instagram"), (4, "TikTok"), (3, "Twitch")):
        u = norm_url(s(r[idx]))
        if u:
            profiles.append((plat, u))
    notes, contacts, numbers = [], [], []

    raw_email = s(r[5])
    found = emails_in(raw_email)
    leftover = EMAIL_RE.sub(" ", raw_email).strip(" ,;/|")
    leftover = re.sub(r"[^\w\s#&.'\-]", "", leftover).strip()   # drop emoji flags / junk
    if leftover:
        if re.search(r"#\d{4}\b", leftover):
            contacts.append("Discord: " + leftover)
        elif not found:
            notes.append("Agency / source: " + leftover)
    extra = s(r[7])
    if extra:
        if extra.strip().upper() == "DM":
            contacts.append("DM on social")
        else:
            for u in URL_RE.findall(extra):
                if "@" in u:
                    continue
                url = norm_url(u)
                kind = classify(url)
                if kind in ("Telegram", "WhatsApp"):
                    contacts.append(kind + ": " + url)
                elif url not in [p[1] for p in profiles]:
                    profiles.append((kind, url))
            for e in emails_in(extra):
                if e not in found:
                    found.append(e)
            numbers.extend(n for n in phones_in(re.sub(URL_RE, " ", extra)) if n not in numbers)

    email = found[0] if found else ""
    if len(found) > 1:
        notes.append("Alt emails: " + ", ".join(found[1:]))

    country = s(r[6])
    parts = [p.strip() for p in country.split(",") if p.strip()]
    if len(parts) > 1:
        notes.append("Location: " + ", ".join(parts))
    elif parts and parts[0].upper() != region.upper():
        notes.append("Location: " + parts[0])

    main = profiles[0][1] if profiles else ""
    if len(profiles) > 1:
        notes.append("Also on: " + " | ".join(f"{p}: {u}" for p, u in profiles[1:]))
    if not email and profiles:
        notes.append("No email yet, check " + profiles[0][0] + " About / contact")

    return {
        "Username": name,
        "Social Profile": main,
        "Email": email,
        "Price": "",
        "Contacts": "; ".join(contacts),
        "Number": ", ".join(numbers),
        "Notes": " | ".join(notes),
        "Status": "To contact" if email else "Needs email",
        "_platform": profiles[0][0] if profiles else "",
    }


def dedupe(rows):
    seen, out, merged = {}, [], 0
    for row in rows:
        keys = [k for k in (row["Email"], row["Social Profile"].lower()) if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit is None:
            out.append(row)
            for k in keys:
                seen[k] = row
            continue
        merged += 1
        for col in ("Email", "Social Profile", "Contacts", "Number"):
            if not hit[col] and row[col]:
                hit[col] = row[col]
        if row["Notes"] and row["Notes"] not in hit["Notes"]:
            hit["Notes"] = (hit["Notes"] + " | " + row["Notes"]).strip(" |")
        hit["Status"] = "To contact" if hit["Email"] else "Needs email"
    return out, merged


def write_xlsx(rows, region, path):
    wb = openpyxl.Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F3864")
    widths = [6, 26, 48, 34, 10, 30, 18, 60, 13]
    for i, title in enumerate(["Outreaching " + region, "Ready to work"]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title[:31]
        ws.append(COLUMNS)
        for c, w in zip(ws[1], widths):
            c.font, c.fill = head_font, head_fill
            ws.column_dimensions[c.column_letter].width = w
        ws.freeze_panes = "A2"
        if i == 0:
            for n, row in enumerate(rows, 1):
                ws.append([n] + [row[c] for c in COLUMNS[1:]])
            for line in ws.iter_rows(min_row=2):
                line[7].alignment = Alignment(wrap_text=False)
    wb.save(path)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    raw, region, out_xlsx = sys.argv[1], sys.argv[2], sys.argv[3]
    out_json = sys.argv[4] if len(sys.argv) > 4 else ""
    wb = openpyxl.load_workbook(raw, read_only=True, data_only=True)
    raw_rows = [r for ws in wb.worksheets for r in ws.iter_rows(values_only=True)
                if r and s(r[0])]
    cleaned = [clean_row(r, region) for r in raw_rows]
    rows, merged = dedupe(cleaned)
    write_xlsx(rows, region, out_xlsx)
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump([dict({"No:": i}, **{c: r[c] for c in COLUMNS[1:]}) for i, r in enumerate(rows, 1)],
                      f, ensure_ascii=False)
    need = [r for r in rows if r["Status"] == "Needs email"]
    stats = {
        "region": region,
        "raw_rows": len(raw_rows),
        "duplicates_merged": merged,
        "clean_rows": len(rows),
        "to_contact_with_email": len(rows) - len(need),
        "needs_email": len(need),
        "needs_email_by_platform": dict(collections.Counter(r["_platform"] or "none" for r in need)),
        "with_phone_number": sum(1 for r in rows if r["Number"]),
        "with_telegram_or_whatsapp": sum(1 for r in rows if ("Telegram" in r["Contacts"] or "WhatsApp" in r["Contacts"])),
        "dm_only_contact": sum(1 for r in rows if r["Contacts"] == "DM on social"),
        "multi_email_rows": sum(1 for r in rows if "Alt emails" in r["Notes"]),
        "output": out_xlsx,
    }
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
