"""Local SQLite registrations. Photos and embeddings commit together."""

from __future__ import annotations

import csv
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "camera_data"
DATABASE = DATA_DIR / "registrations.sqlite3"
ULAANBAATAR = timezone(timedelta(hours=8))
PHOTO_COUNTS = {"human": 50}
VECTOR_SIZES = {"human": 128}


def local_now():
    return datetime.now(ULAANBAATAR)


def display_name(profile):
    return " ".join(filter(None, [profile["surname"], profile["name"]]))


def validate_details(details):
    kind = details.get("kind")
    if kind not in PHOTO_COUNTS:
        raise ValueError("Зөвхөн хүн бүртгэнэ. Амьтан илэрвэл дохио өгнө.")
    cleaned = {key: str(details.get(key, "")).strip() for key in
               ("surname", "name", "species", "note")}
    if not cleaned["name"]:
        raise ValueError("Нэрээ оруулна уу.")
    if not cleaned["surname"]:
        raise ValueError("Хүний овгийг оруулна уу.")
    cleaned["species"] = "person"
    if any(len(value) > 500 for value in cleaned.values()):
        raise ValueError("Талбар бүрт 500 хүртэл тэмдэгт оруулна уу.")
    return {"kind": kind, **cleaned}


class Store:
    def __init__(self, path=DATABASE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('human', 'animal')),
                    surname TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    species TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    photo BLOB NOT NULL,
                    vector BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS samples_profile ON samples(profile_id);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    similarity REAL,
                    profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def profiles(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT p.*, COUNT(s.id) AS photo_count FROM profiles p
                LEFT JOIN samples s ON s.profile_id=p.id
                WHERE p.kind='human'
                GROUP BY p.id ORDER BY p.updated_at DESC
            """)]

    def get_setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row is not None else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def save_registration(self, details, samples, profile_id=None):
        details = validate_details(details)
        kind = details["kind"]
        if len(samples) != PHOTO_COUNTS[kind]:
            raise ValueError(f"{PHOTO_COUNTS[kind]} зураг бүрэн авсны дараа хадгална.")
        rows = []
        for photo, vector in samples:
            vector = np.asarray(vector, dtype=np.float32).reshape(-1)
            if (vector.size != VECTOR_SIZES[kind] or not np.isfinite(vector).all()
                    or np.linalg.norm(vector) < 1e-8 or not photo):
                raise ValueError("Зураг эсвэл танилтын өгөгдөл буруу байна.")
            vector = vector / np.linalg.norm(vector)
            rows.append((photo, vector.astype(np.float32).tobytes()))
        now = local_now().isoformat(timespec="seconds")
        with self.connect() as db:
            if profile_id:
                old = db.execute("SELECT kind FROM profiles WHERE id=?", (profile_id,)).fetchone()
                if old is None or old["kind"] != kind:
                    raise ValueError("Бүртгэл олдсонгүй эсвэл төрөл өөр байна.")
                db.execute("""UPDATE profiles SET surname=?, name=?, species=?, note=?,
                           updated_at=? WHERE id=?""",
                           (details["surname"], details["name"], details["species"],
                            details["note"], now, profile_id))
                db.execute("DELETE FROM samples WHERE profile_id=?", (profile_id,))
            else:
                profile_id = uuid.uuid4().hex
                db.execute("INSERT INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (profile_id, kind, details["surname"], details["name"],
                            details["species"], details["note"], now, now))
            db.executemany("INSERT INTO samples(profile_id, photo, vector) VALUES (?, ?, ?)",
                           [(profile_id, photo, vector) for photo, vector in rows])
        return profile_id

    def edit(self, profile_id, details):
        details = validate_details(details)
        with self.connect() as db:
            row = db.execute("SELECT kind, species FROM profiles WHERE id=?", (profile_id,)).fetchone()
            if row is None:
                raise ValueError("Бүртгэл олдсонгүй.")
            if row["kind"] != details["kind"] or row["species"] != details["species"]:
                raise ValueError("Төрөл солихдоо шинээр зураг авч бүртгэнэ үү.")
            db.execute("UPDATE profiles SET surname=?, name=?, note=?, updated_at=? WHERE id=?",
                       (details["surname"], details["name"], details["note"],
                        local_now().isoformat(timespec="seconds"), profile_id))

    def delete(self, profile_id):
        with self.connect() as db:
            db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def photo(self, profile_id, index=0):
        with self.connect() as db:
            row = db.execute("SELECT photo FROM samples WHERE profile_id=? ORDER BY id LIMIT 1 OFFSET ?",
                             (profile_id, max(0, index))).fetchone()
            return bytes(row[0]) if row else None

    def gallery(self):
        """Only embeddings are loaded into the camera worker, never all photos."""
        with self.connect() as db:
            profiles = {row["id"]: dict(row) for row in db.execute("SELECT * FROM profiles WHERE kind='human'")}
            vectors = {}
            for row in db.execute("SELECT s.profile_id, s.vector FROM samples s "
                                  "JOIN profiles p ON p.id=s.profile_id WHERE p.kind='human'"):
                vectors.setdefault(row["profile_id"], []).append(
                    np.frombuffer(row["vector"], dtype=np.float32).copy())
        return [(profile, np.stack(vectors[key])) for key, profile in profiles.items() if key in vectors]

    def add_event(self, kind, label, confidence, similarity=None, profile_id=None):
        with self.connect() as db:
            # A registration may have been deleted while a frame was processing.
            if profile_id and not db.execute("SELECT 1 FROM profiles WHERE id=?", (profile_id,)).fetchone():
                profile_id = None
            db.execute("""INSERT INTO events(occurred_at, kind, label, confidence, similarity, profile_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                       (local_now().isoformat(timespec="seconds"), kind, label,
                        float(confidence), similarity, profile_id))

    def events(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def export_csv(self, path, table="profiles"):
        if table not in {"profiles", "events"}:
            raise ValueError("Экспортын төрөл буруу байна.")
        with self.connect() as db, Path(path).open("w", encoding="utf-8-sig", newline="") as file:
            condition = " WHERE kind='human'" if table == "profiles" else ""
            cursor = db.execute(f"SELECT * FROM {table}{condition} ORDER BY rowid DESC")
            writer = csv.writer(file)
            writer.writerow([column[0] for column in cursor.description])
            for row in cursor:
                # Keep user-entered names as text when CSV is opened in Excel.
                writer.writerow(["'" + value if isinstance(value, str) and
                                 value.startswith(("=", "+", "-", "@")) else value for value in row])
