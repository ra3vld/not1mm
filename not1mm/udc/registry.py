"""Stable contest identity; module plugins retain their existing stored IDs."""

import importlib
from xml.etree import ElementTree

from not1mm import fsutils

from .model import UdcError
from .storage import Catalog, Snapshots


def catalog():
    return Catalog(fsutils.USER_DATA_PATH / "user-contests")


def entries():
    root = ElementTree.parse(fsutils.APP_DATA_PATH / "new_contest.ui")
    combo = root.find(".//widget[@name='contest']")
    builtin = []
    for item in combo.findall("item"):
        label = item.find("property/string").text
        builtin.append((label.lower().replace(" ", "_"), label))
    return builtin + [(key, label + " [UDC]") for key, label in catalog().entries()]


class BuiltinContest:
    """Non-invasive adapter; old modules keep their established function signatures."""

    def __init__(self, identifier):
        self.module = importlib.import_module("not1mm.plugins." + identifier)

    def __getattr__(self, key):
        return getattr(self.module, key)

    def __setattr__(self, key, value):
        if key == "module":
            object.__setattr__(self, key, value)
        else:
            setattr(self.module, key, value)


def load(identifier, database=None, nr=None):
    if not identifier.startswith("udc:"):
        return BuiltinContest(identifier)
    if database is None:
        bundle = catalog().load(identifier)
        from .plugin import UdcContest

        return UdcContest(bundle, None, {}, {})
    snapshot = Snapshots(database.conn).load(nr)
    if snapshot is None:
        raise UdcError("User contest snapshot is missing")
    bundle, station = snapshot
    from .plugin import UdcContest

    return UdcContest(bundle, database, station, database.fetch_contest_by_id(nr))
