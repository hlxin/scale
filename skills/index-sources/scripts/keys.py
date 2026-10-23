"""API keys: which databases are usable, which keys are missing, and a live check of the keys you added.

Keys live in ~/.scale/sources/keys.txt (one `service: key` per line; `service = key` also works; # comments).
An optional <project>/.claude/keys.txt overrides it for one project. No script ever prints or logs a key value —
only "set" / "missing" and the last 4 characters. Never paste keys into the chat: write them into the file.

  python3 -I keys.py                 # table: every database, needs which key, present or missing
  python3 -I keys.py --init          # create ~/.scale/sources/keys.txt from the template (chmod 600) if absent
  python3 -I keys.py --test          # one tiny request per configured key -> ok / rejected / error
  python3 -I keys.py --json          # same table as JSON (for Claude)
"""
import argparse
import difflib
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (GLOBAL_DIR, KEY_ALIASES, HTTPFail, Project, add_project_arg, key_files, load_keys, parse_keys,
                     set_contact)
from _databases import CATALOG, FETCHERS, keys_needed

SKILL = Path(__file__).resolve().parents[1]
WHERE = {   # how to get each key (also in README.md)
    "openalex": "free — https://openalex.org (account -> API key); strongly recommended: without it OpenAlex uses a "
                "small daily budget shared by everyone on your network",
    "s2": "free — https://www.semanticscholar.org/product/api#api-key-form",
    "core": "free — https://core.ac.uk/services/api (register)",
    "lens": "free for non-commercial use — https://www.lens.org/lens/user/subscriptions (Scholarly + Patent API)",
    "scopus": "institutional — https://dev.elsevier.com (needs your library's Scopus subscription; on campus or VPN)",
    "scopus_insttoken": "optional — from your library, lets Scopus work off campus",
    "springer": "free — https://dev.springernature.com",
    "wos": "institutional — https://developer.clarivate.com (Web of Science Starter API)",
    "ieee": "free (limited) — https://developer.ieee.org",
    "ads": "free — https://ui.adsabs.harvard.edu/user/settings/token",
    "epo_key": "free — https://developers.epo.org (Open Patent Services: consumer key)",
    "epo_secret": "free — the consumer secret of the same EPO app",
    "crossref": "optional — Crossref Metadata Plus token (paid); not needed",
    "zenodo": "optional — https://zenodo.org/account/settings/applications (higher rate limit)",
    "ncbi": "optional — https://www.ncbi.nlm.nih.gov/account/settings (higher PMC rate limit)",
    "cinii": "optional — CiNii appid (https://support.nii.ac.jp/en/cinii/api/developer)",
    "llm_api_key": "only for screening with an OpenAI-compatible API (your institution's LLM service)",
}


def mask(v):
    return "set (…" + v[-4:] + ")" if v and len(v) > 8 else ("set" if v else "missing")


def table(proj):
    keys, origin = load_keys(proj, with_origin=True)
    rows = []
    for name, c in CATALOG.items():
        if name not in FETCHERS or name == "citations":
            continue
        need = keys_needed(name)
        opt = c.get("optional_key")
        missing = [k for k in need if not keys.get(k)]
        rows.append({"database": name, "status": "ready" if not missing else "needs key",
                     "requires": need, "optional": opt, "missing": missing,
                     "optional_present": bool(opt and keys.get(opt))})
    named = sorted(set(k for r in rows for k in r["requires"] + ([r["optional"]] if r["optional"] else [])) | {"llm_api_key"})
    return rows, {k: {"state": mask(keys.get(k)), "file": origin.get(k), "how_to_get": WHERE.get(k, "")} for k in named}


def unknown_names(proj):
    """Names in the key files that no database reads: a typo ('opendalex') leaves the key unused without any error."""
    known = set(WHERE) | set(KEY_ALIASES.values()) | set(keys_needed_all())
    out = []
    for f in key_files(proj):
        try:
            text = f.read_text()
        except OSError:
            continue
        for k in parse_keys(text):
            if k not in known:
                near = difflib.get_close_matches(k, sorted(known), n=1, cutoff=0.6)
                out.append({"name": k, "file": str(f), "did_you_mean": near[0] if near else None})
    return out


def keys_needed_all():
    names = set()
    for name, c in CATALOG.items():
        if name in FETCHERS:
            names.update(keys_needed(name))
            if c.get("optional_key"):
                names.add(c["optional_key"])
    return names


def perms_warning():
    f = GLOBAL_DIR / "keys.txt"
    if f.exists():
        mode = stat.S_IMODE(f.stat().st_mode)
        if mode & 0o077:
            return f"{f} is readable by other users (mode {oct(mode)}): run  chmod 600 {f}"
    return None


def init_file():
    f = GLOBAL_DIR / "keys.txt"
    if f.exists():
        return f"{f} already exists — edit it (nothing was changed)"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((SKILL / "keys.example.txt").read_text())
    os.chmod(f, 0o600)
    return f"created {f} (only you can read it). Open it, paste each key after its `service:` and save."


def test_keys(proj):
    keys = load_keys(proj)
    ctx = {"keys": keys}
    probes = {"openalex": ("openalex", 'title.search:"electrocatalysis"'), "core": ("core", "electrocatalysis"),
              "scopus": ("scopus", "TITLE(electrocatalysis)"), "springer": ("springer", "electrocatalysis"),
              "wos": ("wos", "TI=(electrocatalysis)"), "lens": ("lens", "title:electrocatalysis"),
              "ieee": ("ieee", "electrocatalysis"), "ads": ("ads", "title:electrocatalysis"),
              "epo_key": ("epo", 'ti="electrocatalyst"'), "s2": ("s2", "electrocatalysis")}
    out = {}
    for k, (src, q) in probes.items():
        if not keys.get(k):
            continue
        try:
            recs, _, tot = FETCHERS[src](q, None, None, ctx)
            out[k] = f"ok ({tot if tot is not None else len(recs)} results)"
        except HTTPFail as e:
            st = str(e.status)
            out[k] = ("rejected — check the key" if st in ("401", "403") else
                      "quota used up for today" if "quota" in st else f"error {st}")
        except Exception as e:  # a malformed answer must not stop the other checks
            out[k] = f"error {type(e).__name__}"
    return out


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--email", default=None, help="polite-pool email for the OpenAlex test (optional)")
    a = ap.parse_args()
    proj = Project(a.project)
    set_contact(a.email)
    if a.init:
        print(json.dumps({"init": init_file()}))
        return
    rows, named = table(proj)
    res = {"key_files": [str(f) + (" (present)" if f.exists() else " (absent)") for f in key_files(proj)],
           "keys": named, "databases": rows, "permissions": perms_warning(), "unknown_names": unknown_names(proj)}
    if a.test:
        res["test"] = test_keys(proj)
    if a.json:
        print(json.dumps(res, indent=1))
        return
    print("Key files: " + "; ".join(res["key_files"]))
    if res["permissions"]:
        print("WARNING: " + res["permissions"])
    for u in res["unknown_names"]:
        print(f"WARNING: '{u['name']}' in {u['file']} is not a key name any database reads"
              + (f" — did you mean '{u['did_you_mean']}'?" if u["did_you_mean"] else "")
              + " Rename it in the file (keep the key itself); until then that key is not used.")
    print(f"\n{'key':18}{'state':16}how to get it")
    for k, v in named.items():
        print(f"{k:18}{v['state']:16}{v['how_to_get']}")
    ready = [r["database"] for r in rows if r["status"] == "ready"]
    blocked = [f"{r['database']} ({', '.join(r['missing'])})" for r in rows if r["status"] != "ready"]
    print(f"\nReady databases ({len(ready)}): " + ", ".join(ready))
    print(f"Waiting for a key ({len(blocked)}): " + (", ".join(blocked) or "none"))
    if a.test:
        print("\nKey test: " + (json.dumps(res["test"]) if res["test"] else "no keys to test"))


if __name__ == "__main__":
    main()
