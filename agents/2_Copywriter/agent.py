# -*- coding: utf-8 -*-
"""Agent 2 · Copywriter. See AGENT.md. Usage: python -I agent.py USA"""
import os, sys, re, zlib
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")))
import team as T

SUBJECTS = ["Quick question for {n}", "Brand collab idea for {n}", "{n} and brand partnerships",
            "Partnership question for {n}"]
OPENERS = [
    "I'm the owner, an independent creator partnerships manager. I match creators with brands that fit their audience, "
    "and I'm putting together creators for a few upcoming brand campaigns. I came across your {p} and wanted to "
    "reach out directly.",
    "My name is the owner and I work independently on creator partnerships, connecting creators with brands that suit "
    "their audience. I'm building a shortlist for some upcoming campaigns and your {p} stood out, so I wanted to ask "
    "you directly.",
    "I'm the owner. I connect creators with brands that fit their audience, working independently with several brands. "
    "I'm lining up creators for upcoming campaigns and wanted to reach out after seeing your {p}.",
]
QUESTIONS = ("Before I bring you any offers, a few quick questions so I only send what fits:\n\n"
             "What part of your audience is in the US, roughly?\n"
             "What do you usually charge for a dedicated video, and for a shorter mention or integration?\n"
             "Are you open to performance based deals, like a fixed fee plus a bonus on results, or commission only?\n\n"
             "If you have a media kit or rate card, feel free to send it over. No rush at all.")
FOLLOWUP = ("Just bringing this back to the top of your inbox. Brands I work with are booking creators for the coming "
            "weeks, and many of them now prefer a smaller fixed fee plus a bonus on results, which can work well for "
            "creators with an engaged audience.\n\nIf you share your rates and roughly where your audience is, I can "
            "tell you quickly whether there is a fit.")


def clean_name(name):
    n = re.sub(r"[^\w\s.'&]", "", name or "", flags=re.UNICODE)   # drop emoji and symbols
    n = re.sub(r"\s+", " ", n).strip(" ._")
    return n[:40]


def greet(name):
    n = clean_name(name)
    toks = n.split()
    bad = re.compile(r"\b(official|tv|news|media|channel|team|club|studio|podcast|show|daily|the|crypto|"
                     r"trading|trader|finance|money|invest|bet|picks|sports|gaming|games)\b", re.I)
    if 2 <= len(toks) <= 3 and toks[0].isalpha() and not bad.search(n) and len(toks[0]) > 1:
        t = toks[0]
        return "Hi " + (t.capitalize() if t.islower() or t.isupper() else t) + ","
    if len(toks) == 1 and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{1,20}", toks[0]) and not toks[0].isupper():
        return "Hi " + toks[0] + ","
    return "Hi there,"


def platform_phrase(profile, notes):
    u = (profile or "").lower()
    kind = ("YouTube channel" if "youtube" in u else "Instagram page" if "instagram" in u else
            "TikTok" if "tiktok" in u else "Twitch channel" if "twitch" in u else
            "Kick channel" if "kick.com" in u else "content")
    m = re.search(r"Niche:\s*([^|]+)", notes or "")
    niche = m.group(1).strip() if m else ""
    if niche and len(niche) < 40 and not re.search(r"[-()\[\]]", niche) and "general" not in niche.lower():
        return f"{kind} and how you cover {niche.lower()}"
    return kind


def main():
    region = (sys.argv[1] if len(sys.argv) > 1 else T.settings()["region"]).upper()
    cfg = T.settings()
    sel = T.load(T.today_file(region, "01_selected.json"), {})
    drafts = []
    day = zlib.crc32(T.TODAY.encode())          # rotation shifts every day
    for i, p in enumerate(sel.get("new", [])):
        nm = clean_name(p["name"]) or "you"
        subject = SUBJECTS[(i + day) % len(SUBJECTS)].format(n=nm)
        body = (greet(p["name"]) + "\n\n" + OPENERS[(i + day // 3) % len(OPENERS)].format(p=platform_phrase(p["profile"], p["notes"]))
                + "\n\n" + QUESTIONS + "\n\n" + cfg["signature"])
        drafts.append({"type": "new", "email": p["email"], "name": p["name"], "subject": subject, "body": body})
    for f in sel.get("followups", []):
        subj = f["subject"] or "Following up"
        subj = subj if subj.lower().startswith("re:") else "Re: " + subj
        body = greet(f["name"]) + "\n\n" + FOLLOWUP + "\n\n" + cfg["signature"]
        drafts.append({"type": "followup", "email": f["email"], "name": f["name"], "subject": subj, "body": body,
                       "message_id": f["message_id"], "thread_id": f["thread_id"]})
    T.save(T.today_file(region, "02_drafts.json"), {"date": T.TODAY, "drafts": drafts})
    T.report("Agent 2 Copywriter", "DONE", region=region, first_emails=sum(d["type"] == "new" for d in drafts),
             followups=sum(d["type"] == "followup" for d in drafts))


if __name__ == "__main__":
    main()
