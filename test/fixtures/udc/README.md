# External UDC acceptance corpus

Only source metadata and SHA-256 pins are stored here. Original third-party
definitions, section lists, geography, readme files and archives are kept outside
the repository because their redistribution permissions have not been established.
Putting a source URL or an author in `provenance.json` does not grant permission
to redistribute the corresponding files.

By default the offline acceptance tests read `../not1mm-external-data/udc`
relative to the repository root. Override this with `NOT1MM_UDC_CORPUS` pointing
to an existing private directory outside the checkout. Preserve the relative
paths recorded in the manifests.

```sh
export NOT1MM_UDC_CORPUS=/path/to/private/udc
PYTHONPATH=.:test python3 -m pytest test/test_udc_engine.py test/test_udc_invariants.py test/test_udc_sections_operating.py test/test_udc_call_history.py -q
```

When the external directory is absent, corpus-dependent unit tests report a
skip with setup instructions. Pure synthetic runtime tests still run. Once the
directory exists, missing or changed payloads fail rather than silently skip.
Qt acceptance scripts require the external directory. Tests never download files.

`tools/fetch_udc_corpus.py NEW_EXTERNAL_DIRECTORY` explicitly retrieves the
internet subset for private review and compares the pins. It refuses destinations
inside the repository. Files without a download URL must be supplied separately;
the geography pin identifies the upstream Not1MM country data. Permissions still need
to be checked before sharing any retrieved or exported bundle.

The demonstrations in `examples/udc`, including the tutorial UDC/SEC/HLP files,
were authored for this project and are
covered by the project's GPL license; they are separate from this third-party corpus.

Earlier local development branches still contain these payloads in their Git
history. The integrated `main` starts from upstream history plus a clean squash
of the current changes. Publish `main` explicitly; do not publish old branches
or tags. See [Development and upstream updates](../../../docs/development.md).
