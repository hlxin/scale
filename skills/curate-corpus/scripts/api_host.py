"""Run one hand-out of a curation run on a model behind an API: the agent host of a run prepared with
`--curator api:<model>`.

  python3 -I api_host.py --run <dir> --id <source id> [--role curate|fix] [--max-turns 300] [--context 200000]
                         [--deny <folder> ...] [--dry-run]
  python3 -I api_host.py --key <name> [--key-env <variable>]      (prints the key; the host's apiKeyHelper calls it)

`curate_run.py next --role curate|fix` writes the prompt (prompts/<role>/<id>.md) and names the model; this script runs
that prompt on Claude Code (`claude --bare -p`) pointed at the Anthropic-compatible route of the run's endpoint (the
run's --api-base-url without its /v1), as the run's model, with:
- the key handed to Claude Code by apiKeyHelper (this script with --key), from the run's key (its environment variable,
  else its line in ~/.scale/sources/keys.txt): never in the environment, the command line or a transcript;
- the sandbox on and binding: the host's commands write only in the source's folder, its scratch files in work/tmp,
  and reach no network; a command may not ask to run outside it (Claude Code's dangerouslyDisableSandbox, which
  `--allowedTools Bash` would otherwise approve), a session whose sandbox cannot start (bubblewrap or socat missing)
  fails instead of running unsandboxed, and a source whose scratch path is too long for the sandbox's sockets is
  refused before its session starts (there, every command would fail while the session reported success);
- reading denied for every other run in the run's parent folder, the saved tool outputs of the curator sessions held
  in those folders, and each --deny folder: a curator never sees another curation (another run of the same source
  would hand it the answer);
- the transcript in the source's work/host-<role>-<n>.jsonl.
It needs Claude Code (`claude`) on the PATH and a model that calls tools; reading figures needs one that reads images.
Prints one JSON line: {"id", "role", "model", "exit", "turns", "subtype", "result", "transcript"}.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import curate_run  # noqa: E402

HERE = Path(__file__).resolve()
ROLES = ("curate", "fix")
TMP_MAX = 70    # the sandbox's bridge sockets live in TMPDIR, and a socket path holds at most 107 characters, about
                # 35 of them the socket's own name: measured, work/tmp at 62 characters works, at 101 no command runs


def session_dir(path):
    """The folder in which Claude Code keeps a session's saved tool outputs: the working folder's path, each character
    that is not a letter or a digit replaced by '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def plan(a):
    """The command, environment and settings that run one hand-out, without its key."""
    run = curate_run.Run(a.run)
    model = str(run.models.get("curator") or "")
    if not model.startswith("api:"):
        curate_run.die(f"{run.d} is curated by {model or 'no model'}: api_host runs only an api:<model> curator "
                       "(prepare --curator api:<model> --api-base-url <url>)")
    api = run.models.get("api") or {}
    folder = run.folder(a.id)
    prompt = run.d / "prompts" / a.role / f"{a.id}.md"
    if not folder.is_dir() or not prompt.is_file():
        curate_run.die(f"no hand-out for {a.id} as {a.role}: "
                       f"run curate_run.py next --run {run.d} --role {a.role} first")
    base = re.sub(r"/v1/?$", "", api["base_url"].rstrip("/"))
    others = sorted(p for p in run.d.parent.iterdir() if p.is_dir() and p.resolve() != run.d)
    sessions = Path.home() / ".claude" / "projects"
    mine, root = session_dir(folder), session_dir(run.d.parent)
    saved = [s for s in sorted(sessions.iterdir()) if s.name.startswith(root) and s.name != mine] \
        if sessions.is_dir() else []
    deny = [*others, *saved, *(Path(d).resolve() for d in a.deny)]
    key_name = api.get("key_name") or "llm_api_key"
    helper = f"{shlex.quote(sys.executable)} -I {shlex.quote(str(HERE))} --key {shlex.quote(key_name)}"
    if api.get("key_env"):
        helper += f" --key-env {shlex.quote(api['key_env'])}"
    settings = {"apiKeyHelper": helper,
                # binding: --allowedTools Bash approves any call, one asking to run unsandboxed too
                "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False,
                            "failIfUnavailable": True},
                "permissions": {"deny": [f"Read(/{Path(d).resolve()}/**)" for d in deny]}}
    name = model[4:]
    tmp = folder / "work" / "tmp"
    env = {"ANTHROPIC_BASE_URL": base, "ANTHROPIC_MODEL": name, "ANTHROPIC_SMALL_FAST_MODEL": name,
           "ANTHROPIC_DEFAULT_HAIKU_MODEL": name, "ANTHROPIC_DEFAULT_SONNET_MODEL": name,
           "ANTHROPIC_DEFAULT_OPUS_MODEL": name, "CLAUDE_CODE_SUBAGENT_MODEL": name,
           "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
           "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(a.context),
           "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000", "SCALE_WORKSPACE": str(folder / "work" / "scale-workspace"),
           "TMPDIR": str(tmp), "CLAUDE_CODE_TMPDIR": str(tmp)}
    cmd = ["claude", "--bare", "-p", f"Read {prompt} and follow it exactly.", "--model", name,
           "--settings", json.dumps(settings), "--permission-mode", "acceptEdits",
           "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep", "--max-turns", str(a.max_turns),
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    return run, folder, cmd, env, settings


def host(a):
    run, folder, cmd, env, settings = plan(a)
    if a.dry_run:
        print(json.dumps({"cmd": cmd, "env": env, "settings": settings, "cwd": str(folder)}))
        return
    if len(env["TMPDIR"]) > TMP_MAX:   # the session would start, every command fail, and the session still "succeed"
        curate_run.die(f"the scratch folder {env['TMPDIR']} is {len(env['TMPDIR'])} characters long; the sandbox needs "
                       f"it at {TMP_MAX} or fewer for its sockets, or every command fails: prepare the run in a folder "
                       "with a shorter path (a short symbolic link to it works) and hand the source out again")
    (folder / "work" / "tmp").mkdir(parents=True, exist_ok=True)
    n = len(list((folder / "work").glob(f"host-{a.role}-*.jsonl"))) + 1
    out = folder / "work" / f"host-{a.role}-{n}.jsonl"
    full = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")} | env
    with open(out, "w", encoding="utf-8") as so, open(out.with_suffix(".err"), "w", encoding="utf-8") as se:
        code = subprocess.run(cmd, cwd=folder, env=full, stdin=subprocess.DEVNULL, stdout=so, stderr=se).returncode
    end = {}
    for line in out.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "result":
            end = d
    print(json.dumps({"id": a.id, "role": a.role, "model": run.models.get("curator"), "exit": code,
                      "turns": end.get("num_turns"), "subtype": end.get("subtype"),
                      "result": str(end.get("result") or "")[:300], "transcript": str(out)}))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run", help="the run folder (curate_run.py prepare --curator api:<model>)")
    p.add_argument("--id", help="the source id of the hand-out")
    p.add_argument("--role", choices=ROLES, default="curate")
    p.add_argument("--max-turns", type=int, default=300)
    p.add_argument("--context", type=int, default=200000, help="the context the host compacts at, in tokens")
    p.add_argument("--deny", action="append", default=[], help="a further folder the curator may not read")
    p.add_argument("--dry-run", action="store_true", help="print the command, environment and settings; run nothing")
    p.add_argument("--key", help="print the key of this name (the host's apiKeyHelper)")
    p.add_argument("--key-env", help="with --key: the environment variable that holds it")
    a = p.parse_args()
    if a.key:
        key = curate_run._api_key({"key_name": a.key, "key_env": a.key_env})
        if not key:
            curate_run.die(f"no key: add `{a.key}: <key>` to ~/.scale/sources/keys.txt")
        print(key)
        return
    if not (a.run and a.id):
        p.error("--run and --id are needed (or --key)")
    host(a)


if __name__ == "__main__":
    main()
