"""
pygsi capture — records every GSI payload to a local DuckDB database.

Stores each GameState as a JSON column alongside a timestamp.
Query the data later with SQL:

    import duckdb
    con = duckdb.connect("gsi_capture.duckdb")
    con.sql("SELECT ts, payload->'$.map.name' AS map FROM payloads ORDER BY ts DESC LIMIT 10").show()

Usage:
    1. Copy gamestate_integration_pygsi.cfg into your CS2 cfg directory.
    2. Replace STEAM_ID below with your SteamID64.
    3. Install duckdb:  uv pip install duckdb
    4. Run:  uv run python examples/capture/capture.py
    5. Launch CS2 and join a match.
"""

import logging
from datetime import datetime, timezone

import duckdb

from pygsi import GameState, GSIServer

# ── Config ────────────────────────────────────────────────────────────────────
STEAM_ID = "76561198XXXXXXXXX"
PORT = 4213
DB_PATH = "gsi_capture.duckdb"
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pygsi.capture")

con = duckdb.connect(DB_PATH)
con.execute("""
    CREATE TABLE IF NOT EXISTS payloads (
        ts   TIMESTAMPTZ NOT NULL,
        payload JSON NOT NULL
    )
""")

gsi = GSIServer(player_id=STEAM_ID, port=PORT)


@gsi.on_state_update
async def capture(old: GameState | None, new: GameState) -> None:
    ts = datetime.now(timezone.utc)
    json_str = new.model_dump_json()
    con.execute("INSERT INTO payloads VALUES (?, ?)", [ts, json_str])
    log.info("Captured payload (%d bytes)", len(json_str))


if __name__ == "__main__":
    log.info("Recording to %s", DB_PATH)
    log.info("Listening for CS2 GSI on http://127.0.0.1:%d", PORT)
    log.info("Waiting for CS2 payloads...")
    try:
        gsi.run()
    finally:
        con.close()
