"""A command's output is UTF-8 whatever code page the platform gives a pipe (issue #96)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from conftest import REPO, RUN_SCALE

NAME = "Co/γ-Al2O3, W/F 5.1 gcat h mol−1"


@pytest.mark.parametrize("encoding", ["cp1252", "gbk"])
@pytest.mark.parametrize("fmt", ["json", "markdown"])
def test_query_output_survives_a_narrow_code_page(tmp_path, encoding, fmt):
    doc = json.loads((REPO / "domain/examples/scale-catal/product-measurement-examples/selectivity-basis.json").read_text("utf-8"))
    next(n for n in doc["nodes"] if n["label"] == "CatalyticTest")["props"]["name"] = NAME
    (tmp_path / "doc.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "plan.yaml").write_text("question: Which tests are there?\nmatch: {label: CatalyticTest, as: t}\nreturn: [t.name]\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO), "graph", "query",
                           str(tmp_path / "doc.json"), str(tmp_path / "plan.yaml"), "--format", fmt],
                          capture_output=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin", "SCALE_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": encoding})
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert NAME in proc.stdout.decode("utf-8") or NAME.replace("/", "\\/") in proc.stdout.decode("utf-8")
