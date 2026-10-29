"""Hard limits for ALL EZproxy traffic (library module; also a tiny CLI for status / clearing a hard stop).

Every visit through EZproxy must be granted by Limiter.acquire(). State persists in
~/.scale/sources/ezproxy/limiter_state.json (machine-wide, shared by every project and topic on this computer)
so restarts never reset the counters, and an exclusive OS lock guarantees that only ONE EZproxy process runs at a
time on this machine (the limits protect the institution's IP range, not a topic or a project).

A "visit" = one source (landing page + PDF, the way a person clicks through) or one SI file.

  python3 -I _ezlimit.py status
  python3 -I _ezlimit.py clear-hard-stop      (only after a human has reviewed why it stopped)
"""
import datetime as _dt
import fcntl
import json
import os
import random
import sys
import time
from pathlib import Path

LIMITS = {
    # --- per-publisher limits ---
    "per_publisher_min_interval_s": 90,   # between two visits to the same publisher
    "per_publisher_jitter_s": 45,         # + random 0..45 s on top
    "per_publisher_daily_cap": 120,       # visits per publisher per day
    "block_cooldown_min": 60,             # first block signal from a publisher -> 60 min pause for it
    "hard_stop_blocked_publishers": 2,    # 2 distinct publishers blocking in a day -> stop everything
    # --- global caps (protect the campus IP range and the library proxy) ---
    "global_min_gap_s": 15,               # between ANY two visits, any publisher
    "global_15min_visits": 20,
    "global_15min_mb": 80,
    "global_hourly_visits": 60,
    "global_hourly_mb": 300,
    "global_daily_visits": 600,
    "max_file_mb": 250,                   # a single download larger than this is aborted (big reviews are ~50-150 MB)
    "login_pause_min": 60,                # EZproxy asks for a login (off campus?) -> pause all, never log in
    "login_pauses_before_hard_stop": 3,
}


class HardStop(Exception):
    pass


class Busy(Exception):
    pass


def _now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Limiter:
    def __init__(self, state_path, log=print, take_lock=True):
        self.path = Path(state_path)
        self.log = log
        self._lockfh = None
        if take_lock:
            self._lockfh = open(str(self.path) + ".proc.lock", "a")
            try:
                fcntl.flock(self._lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy("another EZproxy process holds the lock — refusing to run a second one")
        self.st = self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        st = {}
        if self.path.exists():
            try:
                st = json.load(open(self.path))
            except Exception:
                st = {}
        if st.get("v") != 3:
            old = st
            st = {"v": 3, "migrated_from_version": old.get("v"), "hard_stop": old.get("hard_stop")}
        st.setdefault("day", time.strftime("%Y-%m-%d"))
        for k, d in (("pub_day", {}), ("pub_blocks_day", {}), ("pub_next_ok", {}), ("cooldown_until", {}),
                     ("blocked_today", []), ("window", []), ("events", []), ("totals", {"visits": 0, "bytes": 0})):
            st.setdefault(k, d)
        st.setdefault("day_total", 0)
        st.setdefault("last_any", 0.0)
        st.setdefault("pause_all_until", 0.0)
        st.setdefault("login_pauses", 0)
        st.setdefault("hard_stop", None)
        st["limits"] = LIMITS
        return st

    def save(self):
        tmp = Path(str(self.path) + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(self.st, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def event(self, kind, **kw):
        self.st["events"].append({"ts": _now_iso(), "kind": kind, **kw})
        self.st["events"] = self.st["events"][-500:]

    # ------------------------------------------------------------------ bookkeeping
    def _roll_day(self):
        today = time.strftime("%Y-%m-%d")
        if self.st["day"] != today:
            self.st.update({"day": today, "pub_day": {}, "pub_blocks_day": {}, "day_total": 0, "blocked_today": []})

    def _prune(self, now):
        self.st["window"] = [w for w in self.st["window"] if now - w[0] < 3600]

    def hard_stopped(self):
        return self.st.get("hard_stop")

    @staticmethod
    def limits():
        return LIMITS

    # ------------------------------------------------------------------ the gate
    def check(self, pub):
        """(allowed_now, wait_seconds_or_None, reason). wait None = not possible again today."""
        if self.st.get("hard_stop"):
            raise HardStop(self.st["hard_stop"]["reason"])
        L = LIMITS
        now = time.time()
        self._roll_day()
        self._prune(now)
        if self.st["pub_day"].get(pub, 0) >= L["per_publisher_daily_cap"]:
            return False, None, "publisher_daily_cap"
        if self.st["day_total"] >= L["global_daily_visits"]:
            return False, None, "global_daily_cap"
        waits = {"publisher_interval": self.st["pub_next_ok"].get(pub, 0) - now,
                 "publisher_cooldown": self.st["cooldown_until"].get(pub, 0) - now,
                 "pause_all": self.st["pause_all_until"] - now,
                 "global_gap": self.st["last_any"] + L["global_min_gap_s"] - now}
        w15 = [w for w in self.st["window"] if now - w[0] < 900]
        if len(w15) >= L["global_15min_visits"]:
            waits["global_15min_visits"] = w15[-L["global_15min_visits"]][0] + 900 - now
        if sum(w[1] for w in w15) / 1e6 >= L["global_15min_mb"]:
            waits["global_15min_mb"] = w15[0][0] + 900 - now
        wh = self.st["window"]
        if len(wh) >= L["global_hourly_visits"]:
            waits["global_hourly_visits"] = wh[-L["global_hourly_visits"]][0] + 3600 - now
        if sum(w[1] for w in wh) / 1e6 >= L["global_hourly_mb"]:
            waits["global_hourly_mb"] = wh[0][0] + 3600 - now
        reason, wait = max(waits.items(), key=lambda kv: kv[1])
        if wait > 0:
            return False, wait, reason
        return True, 0.0, "ok"

    def acquire(self, pub):
        ok, wait, why = self.check(pub)
        if not ok:
            return False, wait, why
        L = LIMITS
        now = time.time()
        self.st["pub_next_ok"][pub] = now + L["per_publisher_min_interval_s"] + random.uniform(0, L["per_publisher_jitter_s"])
        self.st["last_any"] = now
        self.st["pub_day"][pub] = self.st["pub_day"].get(pub, 0) + 1
        self.st["day_total"] += 1
        self.st["window"].append([now, 0])
        self.st["totals"]["visits"] += 1
        self.save()
        return True, 0.0, "ok"

    def add_bytes(self, n):
        if self.st["window"]:
            self.st["window"][-1][1] += int(n)
        self.st["totals"]["bytes"] += int(n)
        self.save()

    # ------------------------------------------------------------------ bad signals
    def block(self, pub, why):
        """A publisher refused the automated pattern (403/429/503/challenge) through EZproxy."""
        L = LIMITS
        now = time.time()
        self._roll_day()
        self.st["cooldown_until"][pub] = now + L["block_cooldown_min"] * 60
        self.st["pub_blocks_day"][pub] = self.st["pub_blocks_day"].get(pub, 0) + 1
        if self.st["pub_blocks_day"][pub] >= 2:  # same publisher blocked twice today -> done with it for today
            self.st["pub_day"][pub] = L["per_publisher_daily_cap"]
        if pub not in self.st["blocked_today"]:
            self.st["blocked_today"].append(pub)
        self.event("publisher_block", publisher=pub, why=str(why)[:300])
        self.log(f"EZPROXY: publisher {pub} blocked ({why}); cooling down {L['block_cooldown_min']} min")
        self.save()
        if len(self.st["blocked_today"]) >= L["hard_stop_blocked_publishers"]:
            self.hard_stop(f"{len(self.st['blocked_today'])} publishers blocked today: {self.st['blocked_today']}")

    def login_prompt(self, url):
        """EZproxy asked for credentials (machine off the VT network?). Never log in: pause everything."""
        L = LIMITS
        self.st["login_pauses"] += 1
        self.st["pause_all_until"] = time.time() + L["login_pause_min"] * 60
        self.event("ezproxy_login_prompt", url=str(url)[:300], n=self.st["login_pauses"])
        self.log(f"EZPROXY: login prompt ({url[:120]}) — pausing all EZproxy traffic {L['login_pause_min']} min")
        self.save()
        if self.st["login_pauses"] >= L["login_pauses_before_hard_stop"]:
            self.hard_stop("EZproxy keeps asking for a login (not on the VT network / VPN?)")

    def login_ok(self):
        if self.st["login_pauses"]:
            self.st["login_pauses"] = 0
            self.save()

    def hard_stop(self, reason):
        self.st["hard_stop"] = {"reason": reason, "at": _now_iso()}
        self.event("HARD_STOP", reason=reason)
        self.log(f"EZPROXY HARD STOP: {reason}")
        self.save()
        raise HardStop(reason)

    def clear_hard_stop(self):
        self.event("hard_stop_cleared", previous=self.st.get("hard_stop"))
        self.st["hard_stop"] = None
        self.st["login_pauses"] = 0
        self.save()


def status(state_path):
    lim = Limiter(state_path, take_lock=False)
    st = lim.st
    now = time.time()
    lim._roll_day()
    lim._prune(now)
    w15 = [w for w in st["window"] if now - w[0] < 900]
    print(json.dumps({
        "hard_stop": st.get("hard_stop"), "day": st["day"], "visits_today": st["day_total"],
        "visits_today_by_publisher": st["pub_day"], "visits_last_15min": len(w15),
        "mb_last_15min": round(sum(w[1] for w in w15) / 1e6, 1), "visits_last_hour": len(st["window"]),
        "mb_last_hour": round(sum(w[1] for w in st["window"]) / 1e6, 1),
        "cooldowns_active": {p: round((t - now) / 60, 1) for p, t in st["cooldown_until"].items() if t > now},
        "blocked_today": st["blocked_today"], "pause_all_min": round(max(0, st["pause_all_until"] - now) / 60, 1),
        "totals": st["totals"], "recent_events": st["events"][-8:], "limits": LIMITS}, indent=1))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "clear-hard-stop"])
    a = ap.parse_args()
    import _core  # noqa: F401  (index-sources' scripts: the shared core)
    from _common import GLOBAL_DIR
    here = GLOBAL_DIR / "ezproxy" / "limiter_state.json"
    here.parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "status":
        status(here)
    else:
        Limiter(here).clear_hard_stop()
        print("hard stop cleared")
