#!/usr/bin/env python3
"""Explicit online fixture refresh into a NEW directory, never during tests."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "destination", type=Path, help="New, empty directory for review"
    )
    args = parser.parse_args()
    args.destination = args.destination.expanduser().resolve()
    if args.destination == ROOT or ROOT in args.destination.parents:
        parser.error("Third-party corpus must be outside the repository")
    if args.destination.exists():
        parser.error("Destination must not already exist")
    args.destination.mkdir(parents=True)
    manifest = json.loads((ROOT / "test/fixtures/udc/provenance.json").read_text())
    report = []
    for entry in manifest:
        url = entry["url"]
        html = urllib.request.urlopen(url, timeout=60).read().decode("utf-8")
        form = re.search(
            r'<form[^>]+class="CMDM-downloadForm".*?</form>', html, re.S
        ).group()
        action = re.search(r'action="([^"]+)"', form)[1]
        if not action.startswith("https://n1mmwp.hamdocs.com/"):
            raise ValueError("Unexpected download origin: " + action)
        fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', form))
        data = urllib.request.urlopen(
            urllib.request.Request(action, urllib.parse.urlencode(fields).encode()),
            timeout=60,
        ).read()
        name = urllib.parse.unquote(action.rsplit("/", 1)[1])
        if Path(name).name != name:
            raise ValueError(name)
        folder = args.destination / Path(name).stem
        folder.mkdir(exist_ok=True)
        target = folder / name
        target.write_bytes(data)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(target) as archive:
                for member in archive.namelist():
                    if Path(member).name != member:
                        raise ValueError(member)
                    (folder / member).write_bytes(archive.read(member))
        sha = hashlib.sha256(data).hexdigest()
        pinned = next(
            (
                value
                for key, value in entry["files"].items()
                if key.endswith("/" + name)
            ),
            None,
        )
        report.append(
            {
                "url": url,
                "file": str(target),
                "sha256": sha,
                "matches_pin": sha == pinned,
            }
        )
    (args.destination / "download-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))
    if not all(item["matches_pin"] for item in report):
        raise SystemExit(
            "Upstream changed: review files, update independent expectations and provenance explicitly"
        )


if __name__ == "__main__":
    main()
