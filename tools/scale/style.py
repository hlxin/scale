"""Format and naming rules (see docs/style.md).

* **YAML** is for human-written, line-reviewed files (specifications, profiles, migrations,
  competency questions, configuration). It must be *block style*: no flow mappings
  (``{a: b}``) and no flow sequences holding mappings or sequences, because unquoted commas,
  colons or question marks inside them silently change meaning. Ambiguous YAML 1.1 scalars
  (``yes``/``no``/``on``/``off``), duplicate keys and tab indentation are rejected too.
* **JSON** is for machine-written documents (scale-graph documents, patches, gap reports, logs,
  approvals, reports), stored in canonical form (``util.dump_canonical``).
* **Names** in scale-graph schemas: labels PascalCase, edge types UPPER_SNAKE_CASE, properties
  snake_case.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import layout
from .util import ScaleError, dump_canonical, load_doc

PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# Established scientific symbols kept as written (documented in docs/style.md).
NAME_EXCEPTIONS = {"pH"}
AMBIGUOUS_BOOL = re.compile(r"^(y|Y|yes|Yes|YES|n|N|no|No|NO|on|On|ON|off|Off|OFF)$")


# ---------------------------------------------------------------- YAML lint

class _DupKeyLoader(yaml.SafeLoader):
    pass


def lint_yaml_text(text: str, name: str = "<yaml>") -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if line[: len(line) - len(line.lstrip())].count("\t"):
            problems.append(f"{name}:{i}: tab in indentation")
    try:
        nodes = list(yaml.compose_all(text, Loader=_DupKeyLoader))
    except yaml.YAMLError as exc:
        return problems + [f"{name}: not valid YAML: {str(exc).splitlines()[0]}"]

    def walk(node, in_seq=False):
        line = node.start_mark.line + 1
        if isinstance(node, yaml.MappingNode):
            if node.flow_style and node.value:
                problems.append(f"{name}:{line}: flow mapping {{…}}; use block style")
            seen = set()
            for k, v in node.value:
                key = getattr(k, "value", None)
                if key in seen:
                    problems.append(f"{name}:{k.start_mark.line + 1}: duplicate key {key!r}")
                seen.add(key)
                walk(k)
                walk(v)
        elif isinstance(node, yaml.SequenceNode):
            if node.flow_style and any(not isinstance(v, yaml.ScalarNode) for v in node.value):
                problems.append(f"{name}:{line}: flow sequence [...] containing mappings or sequences; use block style")
            for v in node.value:
                if isinstance(v, yaml.ScalarNode):
                    walk(v, in_seq=True)
                    continue
                # "- some prose with `a: b` inside" silently becomes a one-key mapping
                if isinstance(v, yaml.MappingNode) and not v.flow_style and len(v.value) == 1:
                    k, val = v.value[0]
                    if (isinstance(k, yaml.ScalarNode) and k.style is None and isinstance(val, yaml.ScalarNode)
                            and (len(k.value.split()) > 3 or "`" in k.value)):
                        problems.append(f"{name}:{v.start_mark.line + 1}: list item parsed as a mapping at ': '; quote the item")
                walk(v)
        elif isinstance(node, yaml.ScalarNode):
            if node.style is None and in_seq and node.value in ("null", "Null", "NULL", "~"):
                problems.append(f"{name}:{line}: list item {node.value!r} reads as null (no value); quote it if it is a word")
            if node.style is None and AMBIGUOUS_BOOL.match(node.value or ""):
                problems.append(f"{name}:{line}: ambiguous scalar {node.value!r} (YAML 1.1 boolean); quote it")

    for n in nodes:
        if n is not None:
            walk(n)
    return problems


def lint_yaml_file(path: Path) -> list[str]:
    return lint_yaml_text(path.read_text(encoding="utf-8"), str(path))


LINT_TARGETS = ["scale-release.yaml", "core", "domain", "governance", "tools/skills", ".github",
                "docs/implementation-status.yaml"]


def yaml_files(root: Path, targets: list[str] | None = None) -> list[Path]:
    """YAML files under the targets, minus archived releases and local material
    (``layout.is_excluded``). A missing target is an error: a renamed directory must not leave the
    style check silently passing over nothing."""
    out = []
    for t in targets or LINT_TARGETS:
        p = root / t
        if not p.exists():
            raise ScaleError(f"lint target {t} does not exist under {root}")
        cands = [p] if p.is_file() else [*p.rglob("*.yaml"), *p.rglob("*.yml")]
        out += [c for c in cands if not layout.is_excluded(c.relative_to(root))]
    return sorted(set(out))


# ---------------------------------------------------------------- naming

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


def naming_problems(spec: dict) -> list[str]:
    """Naming rules of an assembled scale-graph schema (docs/style.md): labels PascalCase, edge types
    UPPER_SNAKE_CASE, properties snake_case (the established symbol pH allowed, alone and as a token)."""
    problems = []

    def need(kind, name, rx, where):
        normalized = "_".join("ph" if t in NAME_EXCEPTIONS else t for t in name.split("_")) if rx is SNAKE else name
        if name not in NAME_EXCEPTIONS and not rx.match(normalized):
            want = {id(PASCAL): "PascalCase", id(SNAKE): "snake_case", id(UPPER_SNAKE): "UPPER_SNAKE_CASE"}[id(rx)]
            problems.append(f"{where}: {kind} {name!r} should be {want}")

    for lab, d in sorted({**(spec.get("abstract") or {}), **spec["nodes"]}.items()):
        need("label", lab, PASCAL, f"scale-graph {spec.get('version')}")
        for k in (d.get("properties") or {}):
            need("property", k, SNAKE, lab)
    for e, d in sorted(spec["edges"].items()):
        need("edge type", e, UPPER_SNAKE, f"scale-graph {spec.get('version')}")
        for k in (d.get("properties") or {}):
            need("property", k, SNAKE, e)
    return problems


# ---------------------------------------------------------------- canonical JSON

def fmt_file(path: Path, check: bool = False) -> str | None:
    """Rewrite a JSON document in canonical form. Returns a message if it was (or would be) changed."""
    text = path.read_text(encoding="utf-8")
    canon = dump_canonical(load_doc(path))
    if text == canon:
        return None
    if not check:
        path.write_text(canon, encoding="utf-8")
    return f"{path}: {'not canonical' if check else 'reformatted'}"


def machine_yaml_docs(root: Path) -> list[Path]:
    """YAML files that hold machine-style documents (scale-graph documents, patches) and should be JSON."""
    out = []
    targets = ["core/examples"] + [str(p.relative_to(root)) for d in layout.domain_dirs(root)
                                   for p in (d / layout.DOMAIN_EXAMPLES, d / "tests") if p.is_dir()]
    for p in yaml_files(root, targets):
        try:
            d = load_doc(p)
        except Exception:
            continue
        if isinstance(d, dict) and ((isinstance(d.get("graph"), dict) and isinstance(d.get("nodes"), list)) or "resolves" in d):
            out.append(p)
    return out


# ---------------------------------------------------------------- documentation links

MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
MD_REFDEF = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M)


def markdown_files(root: Path) -> list[Path]:
    """The live Markdown files: everything except releases, local
    material (``layout.is_excluded``) and hidden directories other than ``.github``."""
    out = []
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        hidden = any(x.startswith(".") and x != ".github" for x in rel.parts[:-1])
        if not hidden and not layout.is_excluded(rel):
            out.append(p)
    return sorted(out)


def _exists(root: Path, f: Path, path: str) -> bool:
    return (f.parent / path).exists()


def broken_links(root: Path) -> list[str]:
    """Relative links (and images) in live Markdown files whose target does not exist. Links inside
    code (fenced blocks, inline code) are text, not links."""
    problems = []
    for f in markdown_files(root):
        text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), f.read_text(encoding="utf-8"), flags=re.S)
        text = re.sub(r"`[^`\n]*`", "", text)
        for m in [*MD_LINK.finditer(text), *MD_REFDEF.finditer(text)]:
            target = m.group(1)
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith(("#", "/")):
                continue                    # absolute URLs, anchors on the same page, site-absolute paths
            path = target.split("#")[0].split("?")[0]
            if path and not _exists(root, f, path):
                line = text[:m.start()].count("\n") + 1
                problems.append(f"{f.relative_to(root)}:{line}: {target} does not exist")
    return problems
