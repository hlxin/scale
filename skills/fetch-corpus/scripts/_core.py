"""Puts index-sources' scripts on the import path (library module — not run directly).

fetch-corpus fetches what index-sources indexed: the same project, the same database and the same download helpers
(_common, _ledger, _download, _pdf, _mdpi, _vectors). It finds them in index-sources' scripts folder, beside this skill
as the repository holds it (skills/index-sources) or as `scale skills install` copies it (scale-index-sources), or
where INDEX_SOURCES_SCRIPTS points.
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CANDIDATES = [Path(os.environ["INDEX_SOURCES_SCRIPTS"])] if os.environ.get("INDEX_SOURCES_SCRIPTS") else []
_CANDIDATES += [_HERE.parents[1] / name / "scripts" for name in ("index-sources", "scale-index-sources")]

for _c in _CANDIDATES:
    if (_c / "_common.py").is_file():
        INDEX_SOURCES = _c
        break
else:
    sys.exit("ERROR: fetch-corpus needs the index-sources skill beside it (its scripts hold the shared core); "
             "looked in: " + ", ".join(str(c) for c in _CANDIDATES))

if str(INDEX_SOURCES) not in sys.path:
    sys.path.insert(1, str(INDEX_SOURCES))
