"""Peluncur LoketKecil, Python 3.10+ tanpa dependensi eksternal."""

import argparse
import os
import sqlite3
from pathlib import Path
import sys
from threading import Timer
import webbrowser

from loketkecil.database import Store
from loketkecil.http import Server
from loketkecil.validation import AppError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8764)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "data/loketkecil.sqlite3")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--preview", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--strictPort", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port harus 1–65535.")
    if args.preview and os.environ.get("SITES_MANAGED_LINUX_CONTAINER") != "1":
        parser.error("Mode pratinjau hanya tersedia di lingkungan pengujian terkelola.")
    try:
        store = Store(args.db)
        server = Server((args.host, args.port), store)
    except (OSError, sqlite3.Error, AppError) as exc:
        print(f"Belum dapat menjalankan LoketKecil: {exc}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"LoketKecil siap: {url}\nLayar panggilan: {url}display/\nTekan Ctrl+C untuk berhenti.", flush=True)
    if not args.no_browser:
        timer = Timer(.3, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLoketKecil dihentikan. Data tetap tersimpan.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
