"""FalkorDB connection. One graph per repository (FalkorDB multigraph = one tenant per repo)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from falkordb import FalkorDB

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

QUERY_TIMEOUT_MS = 30_000


def graph_name(repo: str) -> str:
    return "bb:" + repo.replace("/", ":")


def connect():
    return FalkorDB(
        host=os.getenv("FALKORDB_HOST", "localhost"),
        port=int(os.getenv("FALKORDB_PORT", "6380")),
        username=os.getenv("FALKORDB_USERNAME") or None,
        password=os.getenv("FALKORDB_PASSWORD") or None,
    )


def get_graph(repo: str = "microsoft/vscode"):
    return connect().select_graph(graph_name(repo))
