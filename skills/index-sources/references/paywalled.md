# Paywalled papers through EZproxy

## Contents
- Rules that never change
- The limits and why
- Setting up access (check_paywalled_access.py verdicts)
- Running and watching the runner
- Hard stops, login prompts, blocks
- Publishers, throughput, what cannot be fetched

## Rules that never change

- Only sanctioned access: the institution's subscription, reached through its EZproxy from the campus network or
  VPN. The scripts never log in, never type credentials, never solve or bypass a CAPTCHA, never use pirate mirrors.
- One EZproxy process per computer (OS lock in `~/.paper-acquisition/ezproxy/limiter_state.json.proc.lock`), for all
  projects and topics together. Never start a second one, never edit `LIMITS` in `scripts/_ezlimit.py`, never delete
  or reset `limiter_state.json` — the counters must survive restarts.
- The user's standing instruction: the institution's rate limits must never be exceeded. When in doubt, stop.

## The limits

Publishers block automated bulk downloads, and a block can land on the institution's whole IP range. Each visit (one
paper: landing page + PDF, or one SI file) must be granted by the limiter:

| Limit | Value |
|---|---|
| between two visits to the same publisher | 90 s + random 0-45 s |
| visits per publisher per day | 120 |
| between any two visits | 15 s |
| visits per 15 min / per hour / per day | 20 / 60 / 600 |
| MB per 15 min / per hour | 80 / 300 |
| largest single file | 250 MB |
| first block by a publisher | that publisher pauses 60 min; a second block ends it for the day |
| two publishers blocking in one day | HARD STOP |
| EZproxy login page | everything pauses 60 min; the third time: HARD STOP |
| EZproxy usage-limit / suspension page | HARD STOP |

Throughput is therefore about 200-600 papers per day. `status.py` turns the queue into days.

## Setting up access

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/check_paywalled_access.py --topic <slug> [--host <ezproxy host>] [--doi <doi>]
```

Host: `--host`, else the saved machine-wide config, else guesses from the institution's email domain
(`ezproxy.lib.<domain>`, `ezproxy.<domain>`, `proxy.lib.<domain>`, `libproxy.<domain>`, `<name>.idm.oclc.org`) that
resolve in DNS. Verification: one paced visit for a paywalled paper of the topic (ACS, Wiley, RSC, Springer, Nature,
... in that order) — the downloaded paper is kept. Verdicts and what to do:

| `reason` says | Do this |
|---|---|
| EZproxy served <doi> without a login | access works: re-run `download_open.py`, start the runner |
| no EZproxy host found | ask the user for the library's EZproxy address, re-run with `--host` |
| EZproxy asked for a login | the machine is off-network: ask the user to connect the VPN and re-run, or continue without paywalled |
| does not proxy this publisher (wrong host?) | ask for the correct host |
| an EZproxy download is already running and fetched N papers | access works; the running runner will pick up the new queue |
| HARD STOP in effect | a human must review (below) |
| no paywalled paper from a supported publisher | re-run with `--doi` of a paywalled ACS/Wiley/RSC/Springer/Nature paper |

`--disable` turns paywalled access off. The verdict is stored in `~/.paper-acquisition/ezproxy/config.json`.

## Running and watching

`download_open.py` queues two kinds of papers for EZproxy when access is verified: Paywalled papers (if Paywalled
was selected) and OA / OA+ND / Free-to-read papers whose only copy sits on a bot-protected publisher site. Start the
runner once — it serves every topic's queue, most relevant and most cited first, round-robin over publishers:

```bash
nohup zsh ${CLAUDE_SKILL_DIR}/scripts/run_paywalled.sh "$PWD" > /dev/null 2>&1 &
```

The wrapper restarts the runner after a crash (≤ 20 times a day), never after a hard stop. Arguments after the
project go to `download_paywalled.py` (e.g. `--skip-publishers iop`). Watch it with:

```bash
tail -20 .scripts/logs/paywalled.log
python3 -I ${CLAUDE_SKILL_DIR}/scripts/_ezlimit.py status
```

To pause: `kill $(cat .scripts/ezproxy/runner.pid)` and then the `download_paywalled.py` process (`pgrep -f
download_paywalled.py`). Restarting later is safe; counters persist. A foreground test of a few papers:
`download_paywalled.py --max-papers 3 --exit-when-empty`.

## Hard stops, login prompts, blocks

- **HARD STOP**: nothing runs until a human looks. Show the user the reason (`_ezlimit.py status`) and the saved pages
  in `.scripts/logs/ezproxy_evidence/`. Only after the user confirms it is safe (e.g. the library confirmed, or a day
  has passed after a block):
  `python3 -I ${CLAUDE_SKILL_DIR}/scripts/_ezlimit.py clear-hard-stop`. Never clear it on your own initiative.
- **Login prompt**: the VPN dropped or the machine left campus. The runner pauses itself; ask the user to reconnect.
  When the prompts come from one publisher only while the others download (the library does not proxy that
  publisher for this account), restart the runner with `--skip-publishers <keys>` (comma list, the keys of the
  queue line in `paywalled.log`, e.g. `annualreviews,sage`): those papers stay queued, nothing is sent to that
  publisher, and every pause it caused stops.
- **Publisher block** (403/429/challenge): automatic cooldown; it is the automated pattern being refused, not the
  subscription. Do not retry faster.

## Publishers

Supported through EZproxy (DOI prefix → bucket): Wiley (10.1002, 10.1111, 10.1155), ACS (10.1021), RSC (10.1039),
Springer (10.1007, 10.1023, 10.1134, 10.1557, 10.1140), Nature (10.1038), IOP/ECS (10.1088, 10.1149), AIP (10.1063,
10.1116), Taylor & Francis (10.1080), OUP (10.1093, 10.1246), Science (10.1126), PNAS (10.1073), Cambridge (10.1017),
De Gruyter (10.1515), SAGE (10.1177), Annual Reviews (10.1146).

Not fetchable: **Elsevier** (10.1016, 10.1006) shows a CAPTCHA even through EZproxy — its papers stay listed with
`Notes: Paywalled — Elsevier (CAPTCHA wall ...)`. Publishers the institution does not subscribe to end as
`EZproxy: not covered by the institution's subscription`.
