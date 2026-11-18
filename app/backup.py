"""Tägliche SQLite-Sicherung nach /data/backup.

Ein Datei-Backup des Daten-Ordners kann die laufende DB mitten im Schreiben erwischen.
Die Kopie per SQLite-Backup-API ist immer konsistent. Behalten werden
die letzten KEEP Tage.
"""

import asyncio
import glob
import os
import sqlite3

from . import db

BACKUP_DIR = os.path.join(db.DATA_DIR, "backup")
KEEP = 14
HOUR, MINUTE = 23, 20


def run() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    day = db.local(db.now_utc()).date().isoformat()
    target = os.path.join(BACKUP_DIR, f"fitpath-{day}.db")
    tmp = target + ".tmp"
    src = sqlite3.connect(db.DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, target)
    for old in sorted(glob.glob(os.path.join(BACKUP_DIR, "fitpath-*.db")))[:-KEEP]:
        os.remove(old)
    return target


def _done_today() -> bool:
    day = db.local(db.now_utc()).date().isoformat()
    return os.path.exists(os.path.join(BACKUP_DIR, f"fitpath-{day}.db"))


async def loop() -> None:
    # Beim Start sofort sichern, falls es heute noch keine Kopie gibt
    await asyncio.sleep(30)
    while True:
        try:
            loc = db.local(db.now_utc())
            if not _done_today() and ((loc.hour, loc.minute) >= (HOUR, MINUTE) or not glob.glob(
                    os.path.join(BACKUP_DIR, "fitpath-*.db"))):
                print(f"Sicherung: {await asyncio.to_thread(run)}", flush=True)
        except Exception as exc:
            print(f"Sicherung fehlgeschlagen: {exc}", flush=True)
        await asyncio.sleep(300)
