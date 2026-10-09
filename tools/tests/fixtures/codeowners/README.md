# CODEOWNERS fixture

`CODEOWNERS` is a copy of the repository's `.github/CODEOWNERS`. `tools/tests/test_codeowners.py` evaluates
it (last matching pattern wins) to show whose review a change needs, e.g. that a catalysis-only proposal and a
core change both go to the owner, and checks that its rules still equal those of `.github/CODEOWNERS`.
