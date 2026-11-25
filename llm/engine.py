# -*- coding: utf-8 -*-
"""
Free model adapter. The agents call two functions:
  smart(system, text, max_tokens)          -> (model_name, answer_text)
  ask(model_key, system, text, max_tokens) -> answer_text
It talks to any OpenAI compatible endpoint. Default: Groq free tier.
Set GROQ_API_KEY (and optionally LLM_BASE_URL, LLM_MODEL) in your environment or in secrets.env.
No paid model is needed anywhere in this project.
"""
import os, json, urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _env(name, default=""):
    if os.environ.get(name):
        return os.environ[name]
    p = os.path.join(ROOT, "secrets.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return default


BASE = _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODEL = _env("LLM_MODEL", "openai/gpt-oss-120b")


def _chat(system, text, max_tokens=700, model=None):
    key = _env("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    body = {"model": model or MODEL, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
    req = urllib.request.Request(BASE.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"] or ""


def smart(system, text, max_tokens=700):
    return MODEL, _chat(system, text, max_tokens)


def ask(model_key, system, text, max_tokens=400):
    return _chat(system, text, max_tokens)
