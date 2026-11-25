# -*- coding: utf-8 -*-
"""Regression test for contact extraction (run: python -I test_contacts.py). Real cases that went wrong once."""
import os, sys, importlib.util
spec = importlib.util.spec_from_file_location("rh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.py"))
RH = importlib.util.module_from_spec(spec); spec.loader.exec_module(RH)

CASES = [
    ("1 TG Post In a well known KOL channel https://t.me/somepaidchannel 3,000", [], []),
    ("1 Twitter Post https://x.com/somecreator?s=21 400\nVideo https://youtu.be/x?si=5334885900356688822 900", [], []),
    ("You can reach me on my telegram: @agency_talent", ["agency_talent"], []),
    ("Telegram @creator_one", ["creator_one"], []),
    ("Write me here t.me/creator_two", ["creator_two"], []),
    ("tg: @creator3 thanks", ["creator3"], []),
    ("my number is +61 400 000 111", [], ["+61400000111"]),
    ("WhatsApp +1 555 010 0199", [], ["+15550100199"]),
    ("Thanks, Your Name Telegram @YourTelegram", [], []),
    ("see you on 12/11/2025", [], []),
]
bad = 0
for text, want_h, want_p in CASES:
    h, p = RH.contacts_from(text)
    ok = h == want_h and p == want_p
    bad += not ok
    print("OK  " if ok else "FAIL", repr(text[:60]), "->", h, p)
print("all good" if not bad else f"{bad} failing")
sys.exit(1 if bad else 0)
