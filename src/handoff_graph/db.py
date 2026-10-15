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
    return "hg:" + repo.replace("/", ":")


def connect():
    """Local FalkorDB by default; set HG_TARGET=cloud to use the FALKORDB_CLOUD_* settings."""
    prefix = "FALKORDB_CLOUD_" if os.getenv("HG_TARGET") == "cloud" else "FALKORDB_"
    return FalkorDB(
        host=os.getenv(prefix + "HOST") or "localhost",
        port=int(os.getenv(prefix + "PORT") or "6380"),
        username=os.getenv(prefix + "USERNAME") or None,
        password=os.getenv(prefix + "PASSWORD") or None,
    )


def get_graph(repo: str = "microsoft/vscode"):
    return connect().select_graph(graph_name(repo))
