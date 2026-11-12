"""Indexer: scans markdown notes and writes viewer/graph-data.js.
Node id == index in the nodes array. Never reorder after writing."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).parent
# Split on whitespace and punctuation only (Bengali vowel signs are not \w in Python, so do not use \w).
TOKEN_RE = re.compile(r"[^\s.,;:!?()\[\]{}\"'“”‘’।|/\\\-–—*#_`>=+<~@$%^&]+")
STOP = set("the a an and or of to in on at is are was were be it this that for with as by from i you we my me do does did what when where who how which".split())
STOP |= set("কি কী কে কোন কখন কোথায় এবং ও আর এই সেই আমার আমাদের তুমি আপনি হয় হয়ে থেকে জন্য".split())


def tokens(s):
    return [t for t in TOKEN_RE.findall(s.lower()) if len(t) >= 2 and t not in STOP]


def clean(text):
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"[#*_`>]+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


import os
# On a host, set ALLAYA_DATA to a persistent volume (e.g. /data): keys and admin settings saved there survive redeploys.
STORE = Path(os.environ["ALLAYA_DATA"]) if os.environ.get("ALLAYA_DATA") else ROOT


def load_config(with_env=True):
    p = ROOT / "config.json"
    c = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"provider": "local", "notes_dir": "./notes"}
    sp = STORE / "config.json"
    if sp != p and sp.exists():
        c.update(json.loads(sp.read_text(encoding="utf-8")))
    if not with_env:
        return c                                  # on a host, secrets come from environment variables
    for env, key in (("GEMINI_API_KEY", "gemini_api_key"), ("ANTHROPIC_API_KEY", "anthropic_api_key"),
                     ("OPENROUTER_API_KEY", "openrouter_api_key"), ("OPENROUTER_MODEL", "openrouter_model"),
                     ("ALLAYA_PROVIDER", "provider")):
        if os.environ.get(env) and ((not sp.exists()) if key == "provider" else not c.get(key)):     # keys saved in the admin win over env
            c[key] = os.environ[env]
    return c


def notes_dir():
    d = Path(load_config().get("notes_dir", "./notes"))
    return d if d.is_absolute() else (ROOT / d).resolve()


def make_node(idx, path, base):
    raw = path.read_text(encoding="utf-8", errors="replace")
    rel = path.relative_to(base)
    group = rel.parts[0] if len(rel.parts) > 1 else "notes"
    return {"id": idx, "label": path.stem, "group": group, "text": clean(raw),
            "wikilinks": [w.strip().lower() for w in re.findall(r"\[\[([^\]|]+)", raw)]}


def relate(a, b):
    la, lb = a["label"].lower(), b["label"].lower()
    ta, tb = a["text"].lower(), b["text"].lower()
    if (len(lb) >= 4 and lb in ta) or (len(la) >= 4 and la in tb):
        return True
    if lb in a["wikilinks"] or la in b["wikilinks"]:
        return True
    return len(set(a["wikilinks"]) & set(b["wikilinks"])) >= 2   # one shared hub link alone would make every sibling a clique


def scan(base):
    files = sorted(base.rglob("*.md"))
    nodes = [make_node(i, p, base) for i, p in enumerate(files)]
    links = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if relate(nodes[i], nodes[j]):
                links.append([i, j])
    return nodes, links


def link_new(nodes, new):
    return [[n["id"], new["id"]] for n in nodes if relate(n, new)]


def write_graph(nodes, links):
    data = {"nodes": [{"id": n["id"], "label": n["label"], "group": n["group"], "excerpt": n["text"][:700]} for n in nodes],
            "links": [{"source": a, "target": b} for a, b in links]}
    out = ROOT / "viewer" / "graph-data.js"
    out.write_text("const GRAPH = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    nodes, links = scan(notes_dir())
    assert all(n["id"] == i for i, n in enumerate(nodes))
    write_graph(nodes, links)
    print(f"indexed {len(nodes)} notes, {len(links)} links")
