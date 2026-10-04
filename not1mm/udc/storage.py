"""Atomic user catalog and content-addressed, per-journal SQLite snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import ENGINE_VERSION, SUPPORTED_ENGINE_VERSIONS
from .engine import Engine, geography
from .model import UdcError, parse


def digest(data):
    return hashlib.sha256(data).hexdigest()


def jsonbytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode()


def read_bundle(path, encoding=None, extra=(), geo=None):
    path = Path(path)
    definition = parse(path.read_bytes(), encoding)
    resources = {}
    candidates = list(path.parent.iterdir()) + list(map(Path, extra))
    for name in definition.dependencies:
        matches = [
            p
            for p in candidates
            if p.is_file() and p.name.casefold() == name.casefold()
        ]
        if not matches:
            raise UdcError(f"Missing dependency: {name}; select the original file")
        values = {p.read_bytes() for p in matches}
        if len(values) != 1:
            raise UdcError(f"Ambiguous dependency: {name}")
        resources[name] = values.pop()
    if geo is None:
        from not1mm import fsutils

        geo = fsutils.APP_DATA_PATH / "cty.json"
    geo = Path(geo)
    # Keep the original custom CTY file as a separate exportable dependency.
    resources[geo.name] = geo.read_bytes()
    table = geography(resources[geo.name])
    Engine(
        definition, resources, {}, {}, table
    )  # validates dependencies before installation
    return Bundle(path.name, definition, resources, geo.name)


class Bundle:
    def __init__(
        self,
        filename,
        definition,
        resources,
        geography_name,
        engine_version=ENGINE_VERSION,
    ):
        self.filename = filename
        self.definition = definition
        self.resources = dict(resources)
        self.geography_name = geography_name
        self.engine_version = engine_version

    def payload(self):
        return {
            "filename": self.filename,
            "encoding": self.definition.encoding,
            "geography": self.geography_name,
            "engine": self.engine_version,
            "files": {name: digest(data) for name, data in self.files().items()},
        }

    def files(self):
        return {self.filename: self.definition.original, **self.resources}

    def engine(self, station, settings):
        return Engine(
            self.definition,
            self.resources,
            station,
            settings,
            geography(self.resources[self.geography_name]),
            engine_version=self.engine_version,
        )

    def export(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in self.files().items():
            target = directory / name
            if target.exists() and target.read_bytes() != data:
                raise UdcError(f"Export would overwrite a different file: {name}")
        for name, data in self.files().items():
            (directory / name).write_bytes(data)


def unpack(payload, read, current_engine=False):
    if payload["engine"] not in SUPPORTED_ENGINE_VERSIONS:
        raise UdcError(
            f"Journal requires UDC engine {payload['engine']}; available {ENGINE_VERSION}"
        )
    files = {}
    for name, sha in payload["files"].items():
        if Path(name).name != name or name in (".", ".."):
            raise UdcError("Invalid resource filename in snapshot")
        if not re_hash(sha):
            raise UdcError("Invalid resource hash in snapshot")
        data = read(sha)
        if digest(data) != sha:
            raise UdcError(f"Resource checksum mismatch: {name}")
        files[name] = data
    data = files.pop(payload["filename"])
    return Bundle(
        payload["filename"],
        parse(
            data,
            payload["encoding"],
            engine_version=ENGINE_VERSION if current_engine else payload["engine"],
        ),
        files,
        payload["geography"],
        ENGINE_VERSION if current_engine else payload["engine"],
    )


class Catalog:
    def __init__(self, root):
        self.root = Path(root)

    def install(self, bundle):
        self.root.mkdir(parents=True, exist_ok=True)
        payload = bundle.payload()
        revision = digest(jsonbytes(payload))
        target = self.root / revision
        temp = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
        try:
            for name, data in bundle.files().items():
                (temp / payload["files"][name]).write_bytes(data)
            (temp / "manifest.json").write_bytes(jsonbytes(payload))
            if not target.exists():
                os.replace(temp, target)
            ref = self.root / (bundle.definition.identifier.replace(":", "-") + ".json")
            fd, filename = tempfile.mkstemp(prefix=".ref-", dir=self.root)
            with os.fdopen(fd, "w") as stream:
                json.dump({"revision": revision}, stream)
            os.replace(filename, ref)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        return bundle.definition.identifier

    def load(self, identifier):
        if not identifier.startswith("udc:") or len(identifier) != 28:
            raise UdcError(f"Invalid user contest ID: {identifier}")
        try:
            ref = json.loads(
                (self.root / (identifier.replace(":", "-") + ".json")).read_text()
            )
            path = self.root / ref["revision"]
            if not re_hash(ref["revision"]):
                raise UdcError("Invalid revision")
            return unpack(
                json.loads((path / "manifest.json").read_bytes()),
                lambda sha: (path / sha).read_bytes(),
                current_engine=True,
            )
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise UdcError(f"Cannot load user contest {identifier}: {exc}") from exc

    def entries(self):
        entries = []
        for ref in sorted(self.root.glob("udc-*.json")):
            identifier = ref.stem.replace("udc-", "udc:", 1)
            bundle = self.load(identifier)
            entries.append((identifier, bundle.definition.label))
        return entries


def re_hash(value):
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class Snapshots:
    def __init__(self, connection):
        self.conn = connection

    def exists(self):
        return bool(
            self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='UdcJournal'"
            ).fetchone()
        )

    def migrate(self):
        if self.exists():
            return
        if self.conn.in_transaction:
            raise UdcError(
                "Finish the pending database transaction before UDC migration"
            )
        # sqlite backup API captures committed WAL data too. Never copy only the db file.
        row = self.conn.execute("PRAGMA database_list").fetchone()
        filename = row["file"] if isinstance(row, dict) else row[2]
        if filename:
            backup = (
                filename
                + ".pre-udc-"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                + ".bak"
            )
            with sqlite3.connect(backup) as destination:
                self.conn.backup(destination)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            self._isolate_contact_keys()
            self.conn.execute(
                "CREATE TABLE UdcResource (Sha256 TEXT PRIMARY KEY, Content BLOB NOT NULL)"
            )
            self.conn.execute(
                "CREATE TABLE UdcJournal (ContestNR INTEGER PRIMARY KEY, Manifest TEXT NOT NULL, Station TEXT NOT NULL)"
            )

    def _isolate_contact_keys(self):
        # The legacy TS+Call key couples independent journals and discards a
        # second QSO within the same second. Preserve every existing contact value while extending the key with journal number and contact UUID.
        info = self.conn.execute("PRAGMA table_info(DXLOG)").fetchall()

        def item(row, key, index):
            return row[key] if isinstance(row, dict) else row[index]

        keys = [
            item(r, "name", 1)
            for r in sorted(info, key=lambda r: item(r, "pk", 5))
            if item(r, "pk", 5)
        ]
        if keys == ["TS", "Call", "ContestNR", "ID"]:
            return
        if keys != ["TS", "Call"]:
            raise UdcError(
                "Unrecognized DXLOG primary key; automatic migration refused"
            )
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='DXLOG'"
        ).fetchone()
        sql = row["sql"] if isinstance(row, dict) else row[0]
        schema = re.sub(
            r'(?i)CREATE TABLE (?:IF NOT EXISTS )?[`"\[]?DXLOG[`"\]]?',
            "CREATE TABLE UdcDxlogMigration",
            sql,
            count=1,
        )
        schema, n = re.subn(
            r'(?i)PRIMARY KEY\s*\(\s*[`"\[]?TS[`"\]]?\s*,\s*[`"\[]?Call[`"\]]?\s*\)',
            "PRIMARY KEY (TS, Call, ContestNR, ID)",
            schema,
            count=1,
        )
        if n != 1:
            raise UdcError("Unrecognized DXLOG schema; automatic migration refused")
        extras = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name='DXLOG' AND type IN ('index','trigger') AND sql IS NOT NULL"
        ).fetchall()
        self.conn.execute(schema)
        self.conn.execute("INSERT INTO UdcDxlogMigration SELECT * FROM DXLOG")
        if self.conn.execute(
            "SELECT * FROM DXLOG EXCEPT SELECT * FROM UdcDxlogMigration"
        ).fetchone():
            raise UdcError("DXLOG migration would change contact values")
        self.conn.execute("DROP TABLE DXLOG")
        self.conn.execute("ALTER TABLE UdcDxlogMigration RENAME TO DXLOG")
        for row in extras:
            self.conn.execute(row["sql"] if isinstance(row, dict) else row[0])

    def create(self, nr, bundle, station):
        self.migrate()
        with self.conn:
            for data in bundle.files().values():
                self.conn.execute(
                    "INSERT OR IGNORE INTO UdcResource VALUES (?,?)",
                    (digest(data), data),
                )
            self.conn.execute(
                "INSERT INTO UdcJournal VALUES (?,?,?)",
                (nr, jsonbytes(bundle.payload()).decode(), jsonbytes(station).decode()),
            )

    def load(self, nr):
        if not self.exists():
            return None
        row = self.conn.execute(
            "SELECT Manifest,Station FROM UdcJournal WHERE ContestNR=?", (nr,)
        ).fetchone()
        if row is None:
            return None
        manifest, station = (
            (row["Manifest"], row["Station"]) if isinstance(row, dict) else row
        )

        def read(sha):
            value = self.conn.execute(
                "SELECT Content FROM UdcResource WHERE Sha256=?", (sha,)
            ).fetchone()
            if value is None:
                raise UdcError(f"Missing resource: {sha}")
            return value["Content"] if isinstance(value, dict) else value[0]

        return unpack(json.loads(manifest), read), json.loads(station)


def engine_for(db, nr):
    snapshot = Snapshots(db.conn).load(nr)
    if snapshot:
        bundle, station = snapshot
        settings = db.fetch_contest_by_id(nr)
        return bundle.engine(station, settings)
    settings = db.fetch_contest_by_id(nr)
    if settings and settings.get("ContestName", "").startswith("udc:"):
        raise UdcError(
            "UDC journal snapshot is missing; cannot use external rules as a substitute"
        )
    return None


def mutate(db, operation, contact):
    """Return False for legacy plugins; UDC changes are validated and committed atomically."""
    old = None
    if operation != "insert":
        old = db.conn.execute(
            "SELECT * FROM DXLOG WHERE ID=?", (contact["ID"],)
        ).fetchone()
        if old is None:
            return False
    nr = (old or contact).get("ContestNR")
    engine = engine_for(db, nr)
    if engine is None:
        return False
    if (
        operation == "insert"
        and db.conn.execute(
            "SELECT 1 FROM DXLOG WHERE ID=?", (contact.get("ID"),)
        ).fetchone()
    ):
        raise UdcError("A contact with this UUID already exists")
    q = {**db.empty_contact, **(old or {}), **contact}
    if str(q.get("ContestNR")) != str(nr):
        raise UdcError("A QSO cannot move between journal snapshots")
    rows = db.conn.execute(
        "SELECT * FROM DXLOG WHERE ContestNR=? ORDER BY TS,ID", (nr,)
    ).fetchall()
    proposed = [r for r in rows if operation == "insert" or r["ID"] != q["ID"]]
    if operation != "delete":
        proposed.append(q)
    result = engine.evaluate(proposed)
    columns = {
        r["name"] for r in db.conn.execute("PRAGMA table_info(DXLOG)").fetchall()
    }
    with db.conn:
        if operation == "delete":
            db.conn.execute(
                "DELETE FROM DXLOG WHERE ID=? AND ContestNR=?", (q["ID"], nr)
            )
        for row in result.contacts:
            clean = {k: v for k, v in row.items() if k in columns}
            if operation == "insert" and row["ID"] == q["ID"]:
                names = list(clean)
                db.conn.execute(
                    "INSERT INTO DXLOG ("
                    + ",".join(names)
                    + ") VALUES ("
                    + ",".join("?" for _ in names)
                    + ")",
                    list(clean.values()),
                )
            else:
                names = [k for k in clean if k != "ID"]
                db.conn.execute(
                    "UPDATE DXLOG SET "
                    + ",".join(k + "=?" for k in names)
                    + " WHERE ID=? AND ContestNR=?",
                    [clean[k] for k in names] + [row["ID"], nr],
                )
    return True


def insert_batch(db, contacts):
    if not contacts:
        return
    nr = contacts[0]["ContestNR"]
    if any(q["ContestNR"] != nr for q in contacts):
        raise UdcError("Mixed journals in import")
    engine = engine_for(db, nr)
    if engine is None:
        raise UdcError("UDC import requires a journal snapshot")
    existing = db.conn.execute(
        "SELECT * FROM DXLOG WHERE ContestNR=?", (nr,)
    ).fetchall()
    result = engine.evaluate(
        [*existing, *[dict(db.empty_contact, **q) for q in contacts]]
    )
    incoming = {q["ID"] for q in contacts}
    if len(incoming) != len(contacts) or any(
        db.conn.execute("SELECT 1 FROM DXLOG WHERE ID=?", (uid,)).fetchone()
        for uid in incoming
    ):
        raise UdcError("Duplicate contact UUID in ADIF import")
    columns = {
        r["name"] for r in db.conn.execute("PRAGMA table_info(DXLOG)").fetchall()
    }
    with db.conn:
        for q in result.contacts:
            clean = {k: v for k, v in q.items() if k in columns}
            names = list(clean)
            if q["ID"] in incoming:
                db.conn.execute(
                    "INSERT INTO DXLOG ("
                    + ",".join(names)
                    + ") VALUES ("
                    + ",".join("?" for _ in names)
                    + ")",
                    list(clean.values()),
                )
            else:
                db.conn.execute(
                    "UPDATE DXLOG SET "
                    + ",".join(k + "=?" for k in names)
                    + " WHERE ID=? AND ContestNR=?",
                    list(clean.values()) + [q["ID"], nr],
                )


def create_journal(db, settings, bundle, station):
    """Create the contest and snapshot together, after a recoverable schema backup."""
    Snapshots(db.conn).migrate()
    fields = {
        r["name"]
        for r in db.conn.execute("PRAGMA table_info(ContestInstance)").fetchall()
    }
    if not set(settings) <= fields:
        raise UdcError("Unknown journal setting")
    with db.conn:
        for data in bundle.files().values():
            db.conn.execute(
                "INSERT OR IGNORE INTO UdcResource VALUES (?,?)", (digest(data), data)
            )
        db.conn.execute(
            "INSERT INTO UdcJournal VALUES (?,?,?)",
            (
                settings["ContestNR"],
                jsonbytes(bundle.payload()).decode(),
                jsonbytes(station).decode(),
            ),
        )
        names = list(settings)
        db.conn.execute(
            "INSERT INTO ContestInstance ("
            + ",".join(names)
            + ") VALUES ("
            + ",".join("?" for _ in names)
            + ")",
            list(settings.values()),
        )
