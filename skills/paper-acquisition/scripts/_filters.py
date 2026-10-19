"""Saved filters: a selection of papers kept in papers.db and refreshed as the database evolves (library module).

A filter is stored with its definition (table `filters`) and its papers (`filter_members`: paper_id, label, level), and
re-runs after every sync that adds or removes papers or changes their text, topics or retraction. The definition is
JSON and holds every expression it needs, so the database carries it to whoever receives the file:

  {"description": "...",
   "exclude": {"non_papers": true, "retracted": true},
   "groups": {"<label>": [<rule>, <rule> ...], ...},          a paper is in a group when it passes every rule
   "export": {"table": "co2_selection", "label_column": "driver"}}    (optional: how filters.py export names them)

  <rule> = {"topics": [vocabulary ids], "fts": "<FTS5 expression>",
            "topics_if": [ids], "if_fts": "<FTS5 expression>",             optional: topics that count only with if_fts
            "competitors": [{"topics": [...], "fts": "..."}]}            optional: what rules the paper out

Levels, as consult.py reads them: strict = the rule's topics among the paper's Topic A/B/C, or its expression in the
title (plus topics_if among Topic A/B/C when if_fts matches anywhere); broad = strict, or the expression anywhere
(title, abstract, keywords). A competitor's topics among Topic A/B/C or its expression in the title rule a paper out at
both levels. A member is listed once per label: level `strict`, or `broad` when it passes only at the broad level.
"""
import json
import sqlite3

from _common import log, now_iso


class _Index:
    def __init__(self, con):
        self.con, self.cache = con, {}

    def fts(self, expr, title_only=False):
        if not expr:
            return set()
        key = ("fts", expr, title_only)
        if key not in self.cache:
            e = f"{{title}} : ({expr})" if title_only else expr
            self.cache[key] = {r[0] for r in self.con.execute("SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?", (e,))}
        return self.cache[key]

    def topic(self, terms):
        if not terms:
            return set()
        key = ("topic", tuple(sorted(terms)))
        if key not in self.cache:
            self.cache[key] = {r[0] for r in self.con.execute(
                f"SELECT paper_id FROM paper_subjects WHERE kind='main' AND term IN ({','.join('?' * len(terms))})",
                list(terms))}
        return self.cache[key]

    def rule(self, r, level):
        ids = self.topic(r.get("topics")) | self.fts(r.get("fts"), True)
        if r.get("topics_if"):
            ids |= self.topic(r["topics_if"]) & self.fts(r.get("if_fts"))
        if level == "broad":
            ids |= self.fts(r.get("fts"))
        for c in r.get("competitors") or []:
            ids -= self.fts(c.get("fts"), True) | self.topic(c.get("topics"))
        return ids


def evaluate(con, definition):
    """[(paper_id, label, level)] for a definition, over the papers now in the database."""
    idx = _Index(con)
    ex = definition.get("exclude") or {}
    where = [w for w, on in (("COALESCE(is_non_paper,0)=1", ex.get("non_papers")),
                             ("COALESCE(is_retracted,0)=1", ex.get("retracted"))) if on]
    excluded = {r[0] for r in con.execute(f"SELECT id FROM papers WHERE {' OR '.join(where)}")} if where else set()
    out = []
    for label, rules in (definition.get("groups") or {}).items():
        strict = set.intersection(*[idx.rule(r, "strict") for r in rules]) - excluded if rules else set()
        broad = set.intersection(*[idx.rule(r, "broad") for r in rules]) - excluded if rules else set()
        out += [(pid, label, "strict") for pid in sorted(strict)]
        out += [(pid, label, "broad") for pid in sorted(broad - strict)]
    return out


def define(con, name, definition, description=None):
    now = now_iso()
    con.execute("INSERT INTO filters(name, description, definition, created_at, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description, definition=excluded.definition, "
                "updated_at=excluded.updated_at",
                (name, description or definition.get("description"), json.dumps(definition, ensure_ascii=False), now, now))


def refresh(con, names=None):
    """Re-run the saved filters (all, or the named ones); {name: papers}."""
    try:
        rows = con.execute("SELECT name, definition FROM filters" +
                           (f" WHERE name IN ({','.join('?' * len(names))})" if names else ""),
                           list(names or [])).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for name, definition in rows:
        try:
            members = evaluate(con, json.loads(definition))
        except sqlite3.OperationalError as e:            # no full-text index, or an expression it does not parse
            log(f"filter {name}: not refreshed ({e})")
            continue
        with con:
            con.execute("DELETE FROM filter_members WHERE filter=?", (name,))
            con.executemany("INSERT INTO filter_members VALUES (?,?,?,?)", [(name, *m) for m in members])
            n = len({m[0] for m in members})
            con.execute("UPDATE filters SET refreshed_at=?, members=? WHERE name=?", (now_iso(), n, name))
        out[name] = n
    return out
