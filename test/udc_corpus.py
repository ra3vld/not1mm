"""Locate optional third-party acceptance data without storing it in the repo."""

import os
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPOSITORY.parent / "not1mm-external-data" / "udc"


def corpus_root():
    """Use an explicit external directory or the sibling private data directory."""
    path = (
        Path(os.environ.get("NOT1MM_UDC_CORPUS", DEFAULT_CORPUS))
        .expanduser()
        .resolve()
    )
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("NOT1MM_UDC_CORPUS must be outside the repository")
    return path


def require_corpus():
    path = corpus_root()
    if not path.is_dir():
        raise FileNotFoundError(
            f"External UDC corpus missing: {path}. "
            "Set NOT1MM_UDC_CORPUS to your private corpus directory; "
            "third-party files are not bundled or downloaded automatically."
        )
    return path
