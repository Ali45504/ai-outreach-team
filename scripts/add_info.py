# -*- coding: utf-8 -*-
"""
Write what the owner learned OUTSIDE Gmail (Telegram, WhatsApp, calls) into team memory, so the sheet shows it
and the team never cold emails or follows up on that person.
USAGE: python -I add_info.py EMAIL [--telegram @x] [--whatsapp +1..] [--phone +1..] [--price "text"]
                             [--note "text"] [--status talking|declined] [--category rates_given|interested_no_rates|question]
Easier for the owner: just type it in the Google Sheet (Price / Contacts / Number / Notes). The team keeps sheet edits.
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import team as T

p = argparse.ArgumentParser()
p.add_argument("email")
p.add_argument("--telegram", action="append", default=[])
p.add_argument("--whatsapp", action="append", default=[])
p.add_argument("--phone", action="append", default=[])
p.add_argument("--price")
p.add_argument("--note")
p.add_argument("--status", choices=["talking", "declined"], default="talking")
p.add_argument("--category", default="interested_no_rates")
a = p.parse_args()

R = T.settings()["region"]
T.take_run_lock(R, "add info")         # never write memory while a team run is writing it
st = T.state(R)
e = a.email.strip().lower()
rec = st.setdefault(e, {})
for h in a.telegram:
    c = "Telegram: @" + h.lstrip("@")
    if c not in rec.setdefault("contacts", []):
        rec["contacts"].append(c)
for n in a.whatsapp:
    c = "WhatsApp: " + n
    if c not in rec.setdefault("contacts", []):
        rec["contacts"].append(c)
    if n not in rec.setdefault("numbers", []):
        rec["numbers"].append(n)
for n in a.phone:
    if n not in rec.setdefault("numbers", []):
        rec["numbers"].append(n)
if a.price:
    rec["price"] = "; ".join(dict.fromkeys(([rec["price"]] if rec.get("price") else []) + [a.price]))
if a.note and a.note not in rec.setdefault("notes", []):
    rec["notes"].append(a.note)          # the sheet shows the last 3 notes
if rec.get("status") != "declined" or a.status == "declined":
    rec["status"] = a.status
    if a.status == "talking":
        rec["reply_category"] = a.category
T.log_event(rec, "info added by the owner (outside Gmail)")
T.save_state(R, st)
T.release_run_lock(R)
print(e, "->", rec.get("status"), "| price:", rec.get("price", ""), "| contacts:", rec.get("contacts", []))
