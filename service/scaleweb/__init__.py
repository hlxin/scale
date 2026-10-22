"""The SCALE web service: one publication into a graph, from a PDF, a DOI or a link, and questions answered from it.

A small HTTP service in front of the scale-catal tools (``scale source start | check | finish``, ``describe``,
``query``, ``search``). A model curates the publication by the curate-corpus skill through those tools, and answers
questions by the query-graph skill; every check, query and search is the tools' own code, so an answer here is the
answer ``scale graph query`` gives. The page in ``site/`` is its interface. Nothing is kept: a job's folder is
deleted once its result is read or it expires, and the graph is returned with quotes capped by the source's rights.
Only GitHub accounts on the allowlist may start a job or ask a question (they spend the service's model budget).
"""

__all__ = ["app", "agent", "auth", "config", "fetch", "jobs"]
