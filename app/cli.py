"""Kommandozeile im Container.

    docker compose exec fitpath python -m app.cli link [Gerätename]
        Einmal-Anmeldelink (15 Minuten gültig) erzeugen und einmal anzeigen.
    docker compose exec fitpath python -m app.cli devices
        Verbundene Geräte auflisten.
    docker compose exec fitpath python -m app.cli revoke <id>
        Gerät abmelden.
    docker compose exec fitpath python -m app.cli rename <id> <Name>
        Gerät umbenennen.
    docker compose exec fitpath python -m app.cli import-bls [datei.csv.gz]
        BLS-Seed neu einlesen (Standard: mitgelieferte seed/bls40.csv.gz).
        Eigene Markierungen bleiben erhalten.
"""

import sys

from . import auth, db, foods


def main(argv: list) -> int:
    db.init()
    cmd = argv[0] if argv else ""
    with db.connect() as conn:
        if cmd == "link":
            url = auth.create_link(conn, " ".join(argv[1:]))
            print(f"Anmeldelink (einmalig, {auth.LINK_MINUTES} Minuten gültig):\n{url}")
            return 0
        if cmd == "devices":
            for r in conn.execute("SELECT id, name, created, last_seen FROM devices ORDER BY id"):
                print(f"{r['id']:>3}  {r['name']:<20} seit {r['created'][:10]}  zuletzt {(r['last_seen'] or '')[:16]}")
            return 0
        if cmd == "revoke" and len(argv) == 2:
            conn.execute("DELETE FROM push_subs WHERE device_id = ?", (int(argv[1]),))
            n = conn.execute("DELETE FROM devices WHERE id = ?", (int(argv[1]),)).rowcount
            print("abgemeldet" if n else "nicht gefunden")
            return 0
        if cmd == "rename" and len(argv) >= 3:
            n = conn.execute("UPDATE devices SET name = ? WHERE id = ?",
                             (" ".join(argv[2:])[:40], int(argv[1]))).rowcount
            print("umbenannt" if n else "nicht gefunden")
            return 0
        if cmd == "import-bls":
            n = foods.import_bls(conn, argv[1] if len(argv) > 1 else foods.SEED)
            print(f"{n} Lebensmittel eingelesen")
            return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
