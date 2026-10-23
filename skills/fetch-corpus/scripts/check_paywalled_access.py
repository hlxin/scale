"""Set up paywalled (institutional) access: find the EZproxy host and verify that this machine can use it.

  1. EZproxy host: --host, else the saved ~/.scale/sources/ezproxy/config.json, else guessed from the institution's email
     domain (ezproxy.lib.<domain>, ezproxy.<domain>, proxy.lib.<domain>, libproxy.<domain>, <name>.idm.oclc.org);
     only hosts that resolve in DNS are kept.
  2. Verification: ONE paced visit through the global limiter for a paywalled source of the topic (or --doi). On the
     campus network / VPN EZproxy serves it without a login. A login page means this machine is off-network: the
     script never logs in. If another EZproxy process is already running, its recent successful downloads count as
     proof instead of a new request.
  3. Writes ~/.scale/sources/ezproxy/config.json ({enabled, host, verified_at, ...}; machine-wide) and prints one JSON verdict:
     {"access": true|false, "host": ..., "reason": ..., "next": ...}

usage: python3 -I check_paywalled_access.py --topic <slug> [--host ezproxy.lib.example.edu] [--doi 10.x/y]
                                            [--email-domain example.edu] [--disable]
"""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
import _ezlimit as EZL
import _ezproxy as EZ
from _common import Project, add_project_arg, json_read, json_write_atomic, load_config, log, now_iso, polite_email, user_agent
from _download import ez_publisher
from _ledger import Ledger

PROBE_ORDER = ["acs", "wiley", "rsc", "springer", "nature", "iop", "aip", "tandf", "oup", "science", "pnas"]


def candidates(domain):
    if not domain:
        return []
    name = domain.split(".")[0]
    return [f"ezproxy.lib.{domain}", f"ezproxy.{domain}", f"login.ezproxy.lib.{domain}", f"proxy.lib.{domain}",
            f"libproxy.{domain}", f"proxy.{domain}", f"{name}.idm.oclc.org"]


def resolves(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def verdict(proj, cfg_ez, access, host, reason, nxt, **extra):
    cfg_ez.update({"host": host, "enabled": bool(access), "last_check": {"at": now_iso(), "access": access, "reason": reason}})
    if access:
        cfg_ez["verified_at"] = now_iso()
    else:
        cfg_ez.pop("verified_at", None)
    json_write_atomic(proj.ezg / "config.json", cfg_ez)
    print(json.dumps({"access": access, "host": host, "reason": reason, "next": nxt, **extra}))


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--host", default=None)
    ap.add_argument("--doi", default=None, help="probe this paywalled DOI instead of one from the topic")
    ap.add_argument("--email-domain", default=None)
    ap.add_argument("--disable", action="store_true", help="turn paywalled access off")
    a = ap.parse_args()
    proj = Project(a.project)
    proj.ezg.mkdir(parents=True, exist_ok=True)
    load_config(proj, a.topic)
    proj.ez.mkdir(parents=True, exist_ok=True)
    cfg_ez = json_read(proj.ezg / "config.json", {}) or {}
    cfg_ez["polite_email"] = cfg_ez.get("polite_email") or polite_email()
    if a.disable:
        cfg_ez.update({"enabled": False})
        cfg_ez.pop("verified_at", None)
        json_write_atomic(proj.ezg / "config.json", cfg_ez)
        print(json.dumps({"access": False, "reason": "disabled by request"}))
        return
    domain = a.email_domain or ((polite_email() or "").split("@")[-1] if "@" in (polite_email() or "") else None)
    hosts = [a.host] if a.host else ([cfg_ez["host"]] if cfg_ez.get("host") else []) + candidates(domain)
    hosts = list(dict.fromkeys(h for h in hosts if h))
    live = [h for h in hosts if resolves(h)]
    log(f"EZproxy host candidates: {hosts} -> resolving: {live}")
    if not live:
        return verdict(proj, cfg_ez, False, None, "no EZproxy host found (none of the candidates resolves in DNS)",
                       "ask the user for their library's EZproxy address, then re-run with --host <host>",
                       tried=hosts)
    host = live[0]
    led = Ledger(proj)
    try:
        lim = EZL.Limiter(proj.ezg / "limiter_state.json", log=log)
    except EZL.Busy:
        recent = led.q("SELECT COUNT(*) FROM sources WHERE download_source='ezproxy' AND download_date >= date('now','-2 day')")
        if recent and recent[0][0] > 0:
            return verdict(proj, cfg_ez, True, cfg_ez.get("host") or host,
                           f"an EZproxy download is already running and fetched {recent[0][0]} sources in the last 2 days",
                           "queue paywalled sources; the running runner will pick them up")
        return verdict(proj, cfg_ez, False, host, "another EZproxy process is running and has no recent successes",
                       "check .scripts/logs/paywalled.log, then re-run this check")
    if lim.hard_stopped():
        return verdict(proj, cfg_ez, False, host, f"EZproxy HARD STOP in effect: {lim.hard_stopped()}",
                       "a human must review .scripts/logs/ezproxy_evidence/ and clear it with _ezlimit.py clear-hard-stop")
    probes = []
    if a.doi:
        p = led.get(led.find_id(doi=a.doi.lower())) if led.find_id(doi=a.doi.lower()) else None
        probes = [p or {"id": 0, "doi": a.doi.lower(), "title": "", "access_type": "Paywalled"}]
    else:
        by_pub = {}      # the most cited paywalled source of each publisher (ids only: a topic may hold millions)
        for pid, doi in led.q("SELECT p.id, p.doi FROM source_topics t JOIN sources p ON p.id = t.source_id WHERE t.topic = ? "
                              "AND p.downloaded = 0 AND p.access_type = 'Paywalled' AND COALESCE(t.in_scope,1) = 1 "
                              "ORDER BY COALESCE(p.cited_by, 0) DESC, t.rowid", (a.topic,)):
            pub = ez_publisher(doi)
            if pub and pub not in by_pub:
                by_pub[pub] = pid
        pick = [by_pub[p] for p in PROBE_ORDER if p in by_pub][:3]
        got = {r["id"]: r for r in led.topic_rows(a.topic, f"AND p.id IN ({','.join('?' * len(pick))})", tuple(pick))} \
            if pick else {}
        probes = [got[i] for i in pick if i in got]
    if not probes:
        return verdict(proj, cfg_ez, False, host, "no paywalled source from a supported publisher to test with",
                       "re-run with --doi <a paywalled DOI from ACS/Wiley/RSC/Springer/Nature>")
    sess = requests.Session()
    sess.headers.update({"User-Agent": user_agent()})
    results = []
    for p in probes:
        pub = ez_publisher(p["doi"])
        while True:
            ok, wait, why = lim.check(pub)
            if ok or wait is None or wait > 600:
                break
            log(f"waiting {wait:.0f}s for the limiter ({why})")
            time.sleep(wait + 1)
        if not ok:
            results.append({"doi": p["doi"], "outcome": f"limiter: {why}"})
            continue
        lim.acquire(pub)
        if not p.get("id"):
            r = EZ.ez_get(sess, lim, EZ.ezrewrite(f"https://doi.org/{p['doi']}", host), "text/html,*/*;q=0.8")
            out = "valid_pdf" if r.content[:4] == b"%PDF" else (EZ.signal(proj, r, host) or "landing_ok")
        else:
            out = EZ.fetch_source(proj, led, sess, lim, host, p, pub)
        results.append({"doi": p["doi"], "publisher": pub, "outcome": out})
        log(f"probe {p['doi']} ({pub}): {out}")
        if out in ("valid_pdf", "duplicate", "landing_ok"):
            led.export()
            return verdict(proj, cfg_ez, True, host, f"EZproxy served {p['doi']} without a login", "queue paywalled sources",
                           probes=results)
        if out == "login_prompt":
            lim.login_prompt(p["doi"])
            return verdict(proj, cfg_ez, False, host, "EZproxy asked for a login — this machine is not on the campus "
                           "network or VPN (the skill never logs in)", "connect to the VPN and re-run, or skip paywalled",
                           probes=results)
        if out == "usage_limit":
            try:
                lim.hard_stop(f"usage-limit page during access check ({p['doi']})")
            except EZL.HardStop:
                pass
            return verdict(proj, cfg_ez, False, host, "EZproxy showed a usage-limit page — stopped", "a human must review",
                           probes=results)
        if out == "not_configured":
            return verdict(proj, cfg_ez, False, host, f"{host} does not proxy this publisher (wrong host?)",
                           "ask the user for the correct EZproxy address, re-run with --host", probes=results)
        if out == "blocked":
            lim.block(pub, f"access check {p['doi']}")
    verdict(proj, cfg_ez, False, host, "no probe succeeded", "try another --doi, or skip paywalled", probes=results)


if __name__ == "__main__":
    main()
