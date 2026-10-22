"""The topic vocabulary is the domain's, not the skill's: a path given, $INDEX_SOURCES_VOCAB, the project's
.scripts/vocab.json, else SCALE's catalysis vocabulary in graphs/catal-commons/literature/ (a checkout of hlxin/scale).

    python -m pytest skills/index-sources/tests
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _topics  # noqa: E402

COMMONS = HERE.parents[2] / "graphs" / "catal-commons" / "literature" / "vocabulary.json"
TERM = {"id": "x", "label": "X", "name": "X", "facet": "reaction", "synonyms": ["xylo"], "related": [], "weight": 1.0}


def _vocab(path):
    path.write_text(json.dumps({"name": path.stem, "terms": [TERM]}))
    return path


def test_the_catalysis_vocabulary_lives_with_the_commons_not_the_skill():
    assert _topics.COMMONS == COMMONS and COMMONS.is_file()
    assert not (HERE.parent / "vocab").exists()
    assert _topics.Vocab().name == "catalysis"


def test_a_path_the_environment_and_the_project_come_before_the_commons(tmp_path, monkeypatch):
    proj = SimpleNamespace(scr=tmp_path / ".scripts")
    proj.scr.mkdir()
    monkeypatch.delenv("INDEX_SOURCES_VOCAB", raising=False)
    assert _topics.vocab_path(proj) == COMMONS
    own = _vocab(proj.scr / "vocab.json")
    assert _topics.vocab_path(proj) == own
    env = _vocab(tmp_path / "env.json")
    monkeypatch.setenv("INDEX_SOURCES_VOCAB", str(env))
    assert _topics.vocab_path(proj) == env
    given = _vocab(tmp_path / "given.json")
    assert _topics.vocab_path(proj, given) == given


def test_without_any_vocabulary_it_says_where_to_put_one(tmp_path, monkeypatch):
    monkeypatch.delenv("INDEX_SOURCES_VOCAB", raising=False)
    monkeypatch.setattr(_topics, "COMMONS", tmp_path / "none.json")
    with pytest.raises(FileNotFoundError, match="vocab.json"):
        _topics.vocab_path(SimpleNamespace(scr=tmp_path))
