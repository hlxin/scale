"""An outage (the computer offline, DNS down, the proxy down) costs no source a try and does not spend the day's
EZproxy visits: OUTAGE_RUN network or proxy errors in a row are given back, in the outcomes log and in a running
queue, and the runner waits 15 min, then 30, then an hour while it lasts. No network.

    python -m pytest tests          (from the skill folder; needs index-sources beside it)
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INDEX = HERE.parents[1] / "index-sources" / "scripts"
sys.path.insert(0, str(INDEX))
sys.path.insert(0, str(SCRIPTS))


def test_an_outage_in_the_outcomes_log_costs_no_source_a_try(tmp_path):
    from _common import Project
    from download_paywalled import retry_counts
    proj = Project(tmp_path / "project")
    proj.ez.mkdir(parents=True, exist_ok=True)
    rows = ([{"kind": "pdf", "id": 1, "outcome": "network_error"}]                  # one error alone: it counts
            + [{"kind": "pdf", "id": 1, "outcome": "valid_pdf"}]
            + [{"kind": "pdf", "id": i % 4 + 2, "outcome": "network_error"} for i in range(12)]   # an outage
            + [{"kind": "si", "id": 9, "outcome": "blocked"}])
    (proj.ez / "outcomes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    tries = retry_counts(proj)
    assert tries[1] == 1 and tries[("si", 9)] == 1 and all(tries[i] == 0 for i in (2, 3, 4, 5))


def test_a_running_queue_waits_through_an_outage_and_gives_its_tries_back():
    from download_paywalled import NET_ERRORS, OUTAGE_RUN, Outage
    outage, tries = Outage(), Counter()

    def visit(key, outcome):                       # as the runner does: count the try, then ask how long to wait
        if outcome in NET_ERRORS:
            tries[key] += 1
        return outage.note(outcome, key, tries)

    waits = [visit(k, "network_error") for k in (1, 2, ("si", 3))]
    assert waits == [0] * (OUTAGE_RUN - 1) + [900] and sum(tries.values()) == 0
    assert [visit(k, "ez_server_error") for k in (4, 5, 6)][-1] == 1800                # still down: longer
    assert [visit(k, "network_error") for k in (1, 2, 3)][-1] == 3600
    assert [visit(k, "network_error") for k in (1, 2, 3)][-1] == 3600                  # an hour at most
    assert visit(7, "valid_pdf") == 0 and sum(tries.values()) == 0                     # back: nothing was spent
    assert [visit(k, "network_error") for k in (8, 9)] == [0, 0] and tries[8] == tries[9] == 1   # two alone count
    assert visit(10, "blocked") == 0 and visit(8, "network_error") == 0 and tries[8] == 2
