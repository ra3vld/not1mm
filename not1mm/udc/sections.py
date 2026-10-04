"""N1MM section lists: received spelling maps to the stored section value."""

import re

from .model import UdcError


def parse_sections(lines, filename):
    sections = {}
    for number, original in enumerate(lines, 2):
        line = original.split(";", 1)[0].strip().upper()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        elif "," in line:
            parts = [part.strip() for part in line.split(",") if part.strip()]
        else:
            parts = line.split()
        if not 1 <= len(parts) <= 2 or any(
            not re.fullmatch(r"[A-Z0-9_-]{1,32}", p) for p in parts
        ):
            raise UdcError(
                f"{filename}:{number}: expected section or spelling, section"
            )
        spelling, section = parts[0], parts[-1]
        for key in (spelling, section):
            if key in sections and sections[key] != section:
                raise UdcError(f"{filename}:{number}: ambiguous section spelling {key}")
            sections[key] = section
    if not sections:
        raise UdcError(f"{filename}: empty section list")
    return sections
