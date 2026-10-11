import json
import re

from conftest import DRIVING_FORCE_EXAMPLES, FIXTURES, REPO
from scale.cli import main
from scale.util import load_yaml


def test_cli_core_commands(tmp_path, capsys):
    ex = DRIVING_FORCE_EXAMPLES / "electro.json"
    assert main(["--repo", str(REPO), "graph", "validate", str(ex)]) in (0, None)
    try:
        main(["--repo", str(REPO), "graph", "validate", str(FIXTURES / "invalid/dangling-link.json")])
        raise AssertionError("an invalid document must fail")
    except SystemExit as exc:
        assert exc.code == 1
    assert main(["--repo", str(REPO), "release", "verify"]) == 0
    assert main(["--repo", str(REPO), "graph", "verify"]) == 0
    assert main(["--repo", str(REPO), "domains", "cq", "catalysis"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(REPO), "release", "list"]) == 0
    from scale.releases import list_releases
    assert [r["release"] for r in json.loads(capsys.readouterr().out)] == list_releases(REPO)   # none before the first
    out = tmp_path / "catalogue.md"
    assert main(["--repo", str(REPO), "catalogue", str(ex), "--out", str(out), "--github-repo", "o/r"]) in (0, None)
    assert "## CatalyticTest" in out.read_text()


def test_the_record_format_commands_are_gone():
    from scale.cli import build_parser
    import argparse
    cmds = next(a.choices for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert not {"init", "lock", "profile", "validate", "curate", "query", "transform", "export", "migrate", "upgrade",
                "agent", "import", "demo", "mappings"} & set(cmds)
    assert set(next(a.choices for a in cmds["release"]._actions if isinstance(a, argparse._SubParsersAction))) == {
        "list", "build", "verify"}


def test_inventory_references_real_tests():
    inv = load_yaml(REPO / "docs/implementation-status.yaml")
    statuses = {c["status"] for c in inv["capabilities"]}
    assert statuses <= {"functioning", "mocked", "planned"}
    from scale import layout
    names = set()
    for d in layout.TEST_DIRS:                         # every testpath; each must hold tests
        files = sorted(REPO.glob(f"{d}/test_*.py"))
        assert files, f"no test files in {d}"
        for p in files:
            names |= set(re.findall(r"^def (test_\w+)", p.read_text(), re.M))
    assert names
    for c in inv["capabilities"]:
        if c["status"] == "functioning":
            assert c.get("tests"), f"{c['name']} is marked functioning without tests"
            for t in c["tests"]:
                assert t in names, f"{c['name']} cites missing test {t}"


def test_inventory_page_is_generated_from_the_yaml():
    from scale.cli import inventory_markdown
    assert (REPO / "docs/implementation-status.md").read_text() == inventory_markdown(load_yaml(REPO / "docs/implementation-status.yaml"))


def test_documented_install_command_pins_the_current_version():
    import re
    from scale import __version__
    pins = set(re.findall(r"scale-catal@([\d.]+)", (REPO / "docs/integrate.md").read_text()))
    assert pins == {__version__}, pins
    assert set(re.findall(r"scale-catal@([\d.]+)", (REPO / "README.md").read_text())) <= {__version__}



def test_check_runs_the_ci_checks(capsys):
    assert main(["--repo", str(REPO), "check", "--fast"]) == 0
    out = capsys.readouterr().out
    assert "invalid scale-catal fixtures are rejected for their stated reasons" in out
    assert "competency questions answer as expected" in out and out.rstrip().endswith("all checks passed")


def test_check_reports_every_failure_and_keeps_going(monkeypatch, capsys):
    import sys
    from scale import devcheck
    steps = [{"name": "breaks", "cmds": [[sys.executable, "-c", "print('boom'); raise SystemExit(4)"]]},
             {"name": "should fail but passes", "expect_errors": ["some error"], "cmds": [[sys.executable, "-c", "pass"]]},
             {"name": "fails for another reason", "expect_errors": ["some error"],
              "cmds": [[sys.executable, "-c", "import json; print(json.dumps({'errors': [{'message': 'other'}]})); raise SystemExit(1)"]]},
             {"name": "fine", "cmds": [[sys.executable, "-c", "pass"]]}]
    monkeypatch.setattr(devcheck, "check_steps", lambda *a, **k: steps)
    assert main(["--repo", str(REPO), "check"]) == 1
    out = capsys.readouterr().out
    assert "FAIL breaks" in out and "boom" in out and "exit 4" in out
    assert "FAIL should fail but passes" in out and "expected exit 1 with an error containing 'some error'" in out
    assert "FAIL fails for another reason" in out
    assert "ok   fine" in out and "some checks failed" in out


def test_every_cli_command_is_in_the_command_reference():
    """DOC-1: each `scale <cmd> [<sub>]` the parser defines appears in docs/commands.md (the `a\\|b` shorthand
    counts: `scale release list\\|diff` documents both)."""
    import argparse
    from scale.cli import build_parser

    def subs(p):
        return next((a.choices for a in p._actions if isinstance(a, argparse._SubParsersAction)), {})

    text = (REPO / "docs/commands.md").read_text(encoding="utf-8")
    documented: dict[str, set[str]] = {}
    for m in re.finditer(r"\bscale ([a-z][a-z-]*)([^`\n]*)", text):
        documented.setdefault(m.group(1), set()).update(re.split(r"\\?\||\s+", m.group(2)))
    missing = []
    for cmd, sp in subs(build_parser()).items():
        if cmd not in documented:
            missing.append(f"scale {cmd}")
        missing += [f"scale {cmd} {s}" for s in subs(sp) if s not in documented.get(cmd, set())]
    assert missing == []


def test_check_warns_when_prose_names_an_old_schema_version():
    """`scale check` warns (never fails: the apply-proposals workflow raises the version and runs the check) when a
    sentence names another version than the manifest, or when the sentence is gone."""
    from scale import devcheck
    versions = {"head": "0.2.0"}
    current = {"README.md": "The schema is at **0.2.0**, the first",
               "docs/architecture.md": "The schema is at 0.2.0, kernel and catalysis together;",
               "docs/implementation-status.yaml": "one version for the kernel and the catalysis domain, at 0.2.0",
               "domain/README.md": "| schema version | 0.2.0 (kernel and catalysis together) |",
               "core/README.md": "the schema is at 0.2.0 (kernel and catalysis together)"}
    assert devcheck.stale_version_texts(current, versions) == []
    stale = dict(current, **{"domain/README.md": "| schema version | 0.1.0 (kernel and catalysis together) |",
                             "core/README.md": None})
    msgs = devcheck.stale_version_texts(stale, versions)
    assert "versions in prose: domain/README.md says head version 0.1.0; it is 0.2.0" in msgs
    assert any("core/README.md no longer has the sentence" in m for m in msgs) and len(msgs) == 2
    step = next(s for s in devcheck.check_steps(REPO, fast=True) if s.get("warning") is devcheck.version_text_warnings)
    assert step["cmds"] == [] and isinstance(devcheck.version_text_warnings(REPO), list)
