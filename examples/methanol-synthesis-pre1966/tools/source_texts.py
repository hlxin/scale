"""Assemble per-source text files from the GALAXY curation kit, for SCALE's verbatim excerpt check.

The kit keeps, for each of the 60 sources, the page texts it read (``work/papers/NN/``): native
PDF text, reading-order and column text, OCR and visual transcriptions. They are not
redistributable, so this script writes them to a local directory outside the repository and
prints the ``--source-text`` arguments for ``scale graph validate``.

Line-end hyphenation is also joined ("synthe-\\nsis" -> "synthesis"), the one normalization the
kit applied beyond whitespace when it verified its quotes.

Usage::

    python source_texts.py KIT_DIR OUT_DIR > source-text.args
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep examples/ free of compiled files
sys.path.insert(0, str(Path(__file__).parent))
from galaxy_to_scale import P, slug  # noqa: E402


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


def main(kit: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for d in sorted((kit / "work/papers").iterdir()):
        meta = json.loads((d / "source.json").read_text(encoding="utf-8"))
        parts = [p.read_text(encoding="utf-8", errors="ignore") for p in sorted(d.glob("*.txt"))
                 if p.name != "checklist.txt"]
        if (d / "pages.json").exists():
            parts += list(strings(json.loads((d / "pages.json").read_text(encoding="utf-8"))))
        text = "\n\f\n".join(parts)
        text += "\n\f\n" + re.sub(r"-\s*\n\s*", "", text)
        sid = f"{P}/source/{slug(meta['source_id'])}"
        path = out / f"{d.name}.txt"
        path.write_text(text, encoding="utf-8")
        print(f"--source-text={sid}={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
