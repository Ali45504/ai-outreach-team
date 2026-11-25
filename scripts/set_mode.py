# -*- coding: utf-8 -*-
"""Switch the team between 'draft' (the owner presses send) and 'send' (team sends by itself).
USAGE: python -I set_mode.py draft|send"""
import sys, os, json
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "outreach_settings.json")
mode = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
if mode not in ("draft", "send"):
    raise SystemExit("use: draft or send")
cfg = json.load(open(p, encoding="utf-8"))
cfg["send_mode"] = mode
json.dump(cfg, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("Sending mode is now:", mode.upper(),
      "(the team sends emails by itself, about 5 a minute)" if mode == "send" else "(the team makes Gmail drafts, you press send)")
