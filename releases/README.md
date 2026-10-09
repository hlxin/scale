# Releases

Official SCALE releases, one directory each (`vX.Y.Z/`), built by a person with
`scale release build vX.Y.Z` from the repository head: an immutable, checksummed snapshot of the science
kernel, the catalysis domain's schema (its manifest, the catalysis file and any frozen versions), the
skills and the spec document of every schema version, with its digest
([governance/release-process.md](../governance/release-process.md)). Nothing inside a release is edited
afterwards; `scale release verify` checks the digests.

No release has been built yet. The first will be **v0.1.0**, binding schema version 0.1.0 (the science
kernel and the catalysis domain together; its spec digest is in the [README](../README.md#schema-versions)
and the [CHANGELOG](../CHANGELOG.md)).
