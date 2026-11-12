"""Allaya admin backend: notes, skills, character, essentials, connectors, audit log.
All of it lives in plain files next to server.py (admin_data.json, admin_audit.jsonl, config.json, notes/).
Secrets are written to config.json and are NEVER returned by any endpoint (only a masked tail)."""
import json, re, time, datetime, shutil, threading
from pathlib import Path
import build

ROOT = Path(__file__).parent
DATA = ROOT / "admin_data.json"
AUDIT = ROOT / "admin_audit.jsonl"
TRASH = ROOT / "notes_trash"
LK = threading.RLock()

DEFAULT = {
    "character": {
        "name": "Allaya", "greeting": "হ্যালো আমি আলেয়া কিভাবে সাহায্য করতে পারি?",
        "about": "A warm, curious guide who knows the notes well and is happy to talk about anything.",
        "formal": 70, "detail": 40, "playful": 55,
        "beyond_notes": True, "mention_notes": True, "followup": False,
    },
    "essentials": [
        {"id": "profile", "title": "Company profile", "hint": "Name, offer, audience, locations", "body": ""},
        {"id": "pricing", "title": "Products and pricing", "hint": "Plans, prices, what is included", "body": ""},
        {"id": "policies", "title": "Policies", "hint": "Refunds, privacy, support hours", "body": ""},
        {"id": "contact", "title": "Contact and escalation", "hint": "Who Allaya hands over to", "body": ""},
    ],
    "skills": [],
    "rules": {"notes_per_answer": 6},
}

BUILTIN_SKILLS = [
    {"id": "b-3d", "name": "3D builder", "desc": "Builds products part by part in the workshop", "say": "build a speaker"},
    {"id": "b-mesh", "name": "Mesh clean-up", "desc": "Simplifies and repairs STL meshes (Open3D)", "say": "Clean mesh button"},
    {"id": "b-pano", "name": "360 viewer", "desc": "Opens panorama images", "say": "360 button"},
    {"id": "b-search", "name": "Note search", "desc": "Finds and explains notes in the galaxy", "say": "find notes on GEO"},
]

# (id, name, group, description, kind) kind: "key" = needs an API key / token
CATALOG = [
    ("gemini", "Gemini", "AI models", "Chat, voice, vision and the 3D builder.", "key"),
    ("claude", "Claude", "AI models", "Anthropic models for builds and long answers.", "key"),
    ("openrouter", "OpenRouter", "AI models", "One key, hundreds of models (GPT, Claude, Llama, Mistral, DeepSeek and more).", "key"),
    ("openai", "OpenAI", "AI models", "GPT models for chat and image generation.", "key"),
    ("mistral", "Mistral", "AI models", "Open-weight models, strong on European languages.", "key"),
    ("llama", "Llama", "AI models", "Meta models through a hosted API.", "key"),
    ("deepseek", "DeepSeek", "AI models", "Low-cost reasoning and coding model.", "key"),
    ("grok", "xAI Grok", "AI models", "Chat model with live web context.", "key"),
    ("perplexity", "Perplexity", "AI models", "Search-grounded answers with sources.", "key"),
    ("ollama", "Ollama (local)", "AI models", "Models running on your own machine.", "url"),
    ("elevenlabs", "ElevenLabs", "AI models", "Natural voice for Allaya's speech.", "key"),
    ("facebook", "Facebook Pages", "Social media", "Reply to messages and comments.", "key"),
    ("instagram", "Instagram", "Social media", "Answer DMs and draft captions.", "key"),
    ("x", "X (Twitter)", "Social media", "Post updates and monitor mentions.", "key"),
    ("linkedin", "LinkedIn", "Social media", "Company page posts.", "key"),
    ("tiktok", "TikTok", "Social media", "Schedule videos and read comments.", "key"),
    ("youtube", "YouTube", "Social media", "Upload videos and reply to comments.", "key"),
    ("pinterest", "Pinterest", "Social media", "Publish pins from products.", "key"),
    ("reddit", "Reddit", "Social media", "Watch communities for brand mentions.", "key"),
    ("whatsapp", "WhatsApp Business", "Messaging", "Let customers chat with Allaya.", "key"),
    ("telegram", "Telegram", "Messaging", "Run Allaya as a bot.", "key"),
    ("slack", "Slack", "Messaging", "Alerts, and teammates can ask Allaya.", "key"),
    ("discord", "Discord", "Messaging", "Community bot for your server.", "key"),
    ("email", "Email (SMTP)", "Messaging", "Send and receive email replies.", "key"),
    ("drive", "Google Drive", "Data and tools", "Import docs into the knowledgebase.", "key"),
    ("notion", "Notion", "Data and tools", "Sync pages as notes.", "key"),
    ("github", "GitHub", "Data and tools", "Sync Markdown repos as notes.", "key"),
    ("sheets", "Google Sheets", "Data and tools", "Read and write rows from chat.", "key"),
    ("calendar", "Google Calendar", "Data and tools", "Book and check meetings.", "key"),
    ("stripe", "Stripe", "Data and tools", "Billing data for the admin dashboard.", "key"),
    ("supabase", "Supabase", "Data and tools", "Database for tenants and audit history.", "key"),
    ("webhooks", "Webhooks", "Data and tools", "Send events to your endpoints when notes change.", "url"),
    ("zapier", "Zapier", "Data and tools", "Link Allaya to thousands of other apps.", "url"),
]
ACTIVE = {"gemini", "claude", "ollama", "openrouter"}          # connectors the app actually calls today
# connector id -> (provider name in config.json, secret key, model key, default model)
CHAT = {"gemini": ("gemini", "gemini_api_key", "gemini_chat_model", "gemini-flash-lite-latest"),
        "claude": ("anthropic", "anthropic_api_key", "model", "claude-opus-5-5"),
        "openrouter": ("openrouter", "openrouter_api_key", "openrouter_model", "openrouter/auto"),
        "ollama": ("ollama", "ollama_url", "ollama_model", "qwen2.5:3b")}


def load():
    with LK:
        try:
            d = json.loads(DATA.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        out = json.loads(json.dumps(DEFAULT))
        for k in ("character", "rules"):
            out[k].update(d.get(k, {}))
        if isinstance(d.get("skills"), list):
            out["skills"] = d["skills"]
        if isinstance(d.get("essentials"), list) and d["essentials"]:
            out["essentials"] = d["essentials"]
        return out


def save(d):
    with LK:
        tmp = DATA.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DATA)


def audit(who_what, detail=""):
    with LK:
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "what": who_what, "detail": detail}, ensure_ascii=False) + "\n")


def audit_list(n=30):
    if not AUDIT.exists():
        return []
    rows = []
    for line in AUDIT.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[::-1]


# ---------- persona ----------
def persona(base):
    d = load()
    c, parts = d["character"], [base]
    if c["name"].strip() and c["name"].strip().lower() != "allaya":
        parts.append(f"Your name is {c['name'].strip()}.")
    if c["about"].strip():
        parts.append("About you: " + c["about"].strip())
    style = []
    style.append("casual and relaxed" if c["formal"] > 66 else "formal and polished" if c["formal"] < 34 else "friendly")
    style.append("playful and witty" if c["playful"] > 66 else "serious and measured" if c["playful"] < 34 else "lightly witty")
    if c["detail"] > 66:
        style.append("detailed: give fuller answers of up to six sentences (this overrides the length rule above)")
    elif c["detail"] < 34:
        style.append("very brief: one or two sentences (this overrides the length rule above)")
    parts.append("Your style: " + ", ".join(style) + ".")
    if not c["beyond_notes"]:
        parts.append("Stay on the topics covered by the notes and the essentials; politely decline unrelated topics (this overrides the free-ranging rule above).")
    if not c["mention_notes"]:
        parts.append("Always lead with what the notes say when they are relevant, and say which note you used.")
    if c["followup"]:
        parts.append("End each reply with one short follow-up question.")
    ess = [e for e in d["essentials"] if e["body"].strip()]
    if ess:
        parts.append("ESSENTIAL FACTS from the owner (always true; use them before the notes):\n" + "\n".join(f"- {e['title']}: {e['body'].strip()}" for e in ess))
    sk = [s for s in d["skills"] if s.get("on") and s.get("instructions", "").strip()]
    if sk:
        parts.append("EXTRA SKILLS the owner added:\n" + "\n".join(
            f"- {s['name']}" + (f" (when the user says something like: {s['trigger']})" if s.get("trigger") else "") + f": {s['instructions'].strip()}" for s in sk))
    return "\n\n".join(parts)


# ---------- notes ----------
def _slug(s):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", s).strip(" .")
    return re.sub(r"\s+", " ", s)[:80]


def notes_list():
    base = build.notes_dir()
    rows = []
    for p in sorted(base.rglob("*.md")):
        rel = p.relative_to(base)
        st = p.stat()
        rows.append({"path": rel.as_posix(), "title": p.stem, "folder": rel.parts[0] if len(rel.parts) > 1 else "notes",
                     "size": st.st_size, "mtime": st.st_mtime})
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def _safe(rel):
    base = build.notes_dir().resolve()
    p = (base / rel).resolve()
    if base not in p.parents or p.suffix.lower() != ".md":
        raise ValueError("bad note path")
    return p


def note_get(rel):
    p = _safe(rel)
    return {"path": rel, "content": p.read_text(encoding="utf-8", errors="replace")}


def note_save(title, folder, content, rel=None):
    title, folder = _slug(title), _slug(folder) or "notes"
    if not title:
        raise ValueError("a title is required")
    if not content.strip():
        raise ValueError("write some content first")
    base = build.notes_dir()
    with LK:
        if rel:
            p = _safe(rel)
            if not p.exists():
                raise ValueError("note not found")
        else:
            d = base / folder
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{title}.md"
            if p.exists():
                raise ValueError(f"a note called '{title}' already exists in {folder}")
            _safe(p.relative_to(base).as_posix())
        body = content if content.lstrip().startswith("#") else f"# {title}\n\n{content}"
        p.write_text(body.rstrip() + "\n", encoding="utf-8")
        audit("Note saved" if rel else "Note added", p.relative_to(base).as_posix())
        return p.relative_to(base).as_posix()


def note_delete(rel):
    p = _safe(rel)
    if not p.exists():
        raise ValueError("note not found")
    with LK:
        TRASH.mkdir(exist_ok=True)
        dest = TRASH / f"{int(time.time())}-{p.name}"
        shutil.move(str(p), str(dest))        # recoverable: moved to notes_trash/, never hard-deleted
        audit("Note removed", f"{rel} (moved to notes_trash/)")


# ---------- skills / essentials / character ----------
def skill_add(name, trigger, instructions):
    name = name.strip()
    if not name or not instructions.strip():
        raise ValueError("a skill needs a name and instructions")
    d = load()
    if any(s["name"].lower() == name.lower() for s in d["skills"]):
        raise ValueError("a skill with that name exists")
    d["skills"].append({"id": "s" + str(int(time.time() * 1000)), "name": name[:60], "trigger": trigger.strip()[:120],
                        "instructions": instructions.strip()[:2000], "on": True})
    save(d)
    audit("Skill added", name)


def skill_set(sid, on=None, delete=False):
    d = load()
    s = next((x for x in d["skills"] if x["id"] == sid), None)
    if not s:
        raise ValueError("skill not found")
    if delete:
        d["skills"].remove(s)
        audit("Skill removed", s["name"])
    else:
        s["on"] = bool(on)
        audit("Skill " + ("enabled" if on else "disabled"), s["name"])
    save(d)


def essential_set(eid, title, body):
    d = load()
    e = next((x for x in d["essentials"] if x["id"] == eid), None)
    if not e:
        if not title.strip():
            raise ValueError("a title is required")
        e = {"id": "e" + str(int(time.time() * 1000)), "title": title.strip()[:60], "hint": "", "body": ""}
        d["essentials"].append(e)
    if title.strip():
        e["title"] = title.strip()[:60]
    e["body"] = body.strip()[:4000]
    save(d)
    audit("Essential saved", e["title"])


def essential_delete(eid):
    d = load()
    d["essentials"] = [e for e in d["essentials"] if e["id"] != eid]
    save(d)
    audit("Essential removed", eid)


def character_save(c):
    d = load()
    cur = d["character"]
    for k in ("name", "greeting", "about"):
        if k in c:
            cur[k] = str(c[k])[:600]
    for k in ("formal", "detail", "playful"):
        if k in c:
            cur[k] = max(0, min(100, int(c[k])))
    for k in ("beyond_notes", "mention_notes", "followup"):
        if k in c:
            cur[k] = bool(c[k])
    save(d)
    audit("Character updated", cur["name"])


def rules_save(r):
    d = load()
    d["rules"]["notes_per_answer"] = max(1, min(20, int(r.get("notes_per_answer", 6))))
    save(d)
    audit("Answering rules updated", str(d["rules"]["notes_per_answer"]))


# ---------- connectors ----------
def _cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def _put_cfg(c):
    tmp = (ROOT / "config.json").with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ROOT / "config.json")


def _secret_of(c, cid):
    if cid == "gemini":
        return c.get("gemini_api_key", "")
    if cid == "claude":
        return c.get("anthropic_api_key", "")
    if cid == "ollama":
        return c.get("ollama_url", "")
    if cid == "openrouter":
        return c.get("openrouter_api_key", "")
    return (c.get("connectors") or {}).get(cid, "")


def _real(v):
    return bool(v) and "PUT-YOUR" not in str(v)


def connectors_list():
    c = _cfg()
    out = []
    for cid, name, group, desc, kind in CATALOG:
        v = _secret_of(c, cid)
        ok = _real(v)
        tail = ("…" + str(v)[-4:]) if ok and kind == "key" and len(str(v)) > 8 else ("set" if ok and kind == "key" else (str(v) if ok else ""))
        out.append({"id": cid, "name": name, "group": group, "desc": desc, "kind": kind, "connected": ok,
                    "detail": tail, "used": cid in ACTIVE, "chat": cid in CHAT,
                    "primary": cid in CHAT and c.get("provider") == CHAT[cid][0],
                    "model": c.get(CHAT[cid][2], CHAT[cid][3]) if cid in CHAT else ""})
    return out


def connector_set(cid, value):
    meta = next((x for x in CATALOG if x[0] == cid), None)
    if not meta:
        raise ValueError("unknown connector")
    value = str(value).strip()
    if not value:
        raise ValueError("paste a value first")
    with LK:
        c = _cfg()
        if cid == "gemini":
            c["gemini_api_key"] = value
        elif cid == "claude":
            c["anthropic_api_key"] = value
        elif cid == "ollama":
            c["ollama_url"] = value
        elif cid == "openrouter":
            c["openrouter_api_key"] = value
        else:
            c.setdefault("connectors", {})[cid] = value
        _put_cfg(c)
    audit("Connector connected", meta[1])


def connector_clear(cid):
    meta = next((x for x in CATALOG if x[0] == cid), None)
    if not meta:
        raise ValueError("unknown connector")
    with LK:
        c = _cfg()
        if cid == "gemini":
            c["gemini_api_key"] = ""
        elif cid == "claude":
            c["anthropic_api_key"] = ""
        elif cid == "ollama":
            pass
        elif cid == "openrouter":
            c["openrouter_api_key"] = ""
            if c.get("provider") == "openrouter":          # never leave the app pointing at a key that is gone
                c["provider"] = "local"
        else:
            (c.get("connectors") or {}).pop(cid, None)
        _put_cfg(c)
    audit("Connector disconnected", meta[1])


def set_provider(p):
    if p not in ("local", "gemini", "ollama", "anthropic", "openrouter"):
        raise ValueError("unknown provider")
    with LK:
        c = _cfg()
        c["provider"] = p
        _put_cfg(c)
    audit("Active AI changed", p)


def set_model(cid, model):
    """Pick which model a chat connector uses (e.g. openrouter: anthropic/claude-sonnet-4.5)."""
    if cid not in CHAT:
        raise ValueError("this connector has no model setting")
    model = str(model).strip()
    if not model or len(model) > 120 or any(ch.isspace() for ch in model):
        raise ValueError("enter a model id, e.g. openai/gpt-4o-mini")
    with LK:
        c = _cfg()
        c[CHAT[cid][2]] = model
        _put_cfg(c)
    audit("Model changed", f"{cid}: {model}")
