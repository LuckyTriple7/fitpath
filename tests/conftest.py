"""Testumgebung: eigene Datenbank in einem temporären Ordner."""

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="fitpath-test-")
os.environ["DATA_DIR"] = TMP
os.environ["COOKIE_SECURE"] = "false"
os.environ["PUBLIC_URL"] = "http://testserver"
os.environ["TZ"] = "Europe/Berlin"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
