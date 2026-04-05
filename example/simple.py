"""
pygsi example — logs every GSI event to the console.

Usage:
    1. Copy gamestate_integration_pygsi.cfg into your CS2 cfg directory.
    2. Replace STEAM_ID below with your SteamID64.
    3. Run:  uv run python example/simple.py
    4. Launch CS2 and join a match.
"""

import logging

from pygsi import (
    GSIServer,
    PlayerMatchStats,
    PlayerState,
    RoundState,
)

# ── Config ────────────────────────────────────────────────────────────────────
# Replace with your SteamID64.
# Find yours at https://steamid.io or by typing `status` in the CS2 console.
STEAM_ID = "76561198XXXXXXXXX"
PORT = 4213
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Send debug logs (raw payloads) to a separate file
_debug_handler = logging.FileHandler("gsi_debug.log")
_debug_handler.setLevel(logging.DEBUG)
_debug_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
logging.getLogger("pygsi.server").addHandler(_debug_handler)
logging.getLogger("pygsi.server").setLevel(logging.DEBUG)

gsi = GSIServer(player_id=STEAM_ID, port=PORT)


# ── Round events ──────────────────────────────────────────────────────────────


@gsi.on_round_start
async def round_start(old: RoundState | None, new: RoundState) -> None:
    map_name = gsi.state.map.name if gsi.state and gsi.state.map else "unknown"
    round_num = gsi.state.map.round if gsi.state and gsi.state.map else "?"
    log.info(">>> ROUND %s START on %s", round_num, map_name)


@gsi.on_round_end
async def round_end(old: RoundState | None, new: RoundState) -> None:
    winner = new.winning_team or "unknown"
    log.info("<<< ROUND END — winner: %s", winner)


# ── Bomb events ───────────────────────────────────────────────────────────────


@gsi.on_bomb_planted
async def bomb_planted(old: RoundState | None, new: RoundState) -> None:
    log.info("*** BOMB PLANTED")


@gsi.on_bomb_defused
async def bomb_defused(old: RoundState | None, new: RoundState) -> None:
    log.info("*** BOMB DEFUSED")


@gsi.on_bomb_exploded
async def bomb_exploded(old: RoundState | None, new: RoundState) -> None:
    log.info("*** BOMB EXPLODED")


# ── Player events ─────────────────────────────────────────────────────────────


@gsi.on_local_player_kill
async def player_kill(old: PlayerMatchStats | None, new: PlayerMatchStats) -> None:
    log.info(
        "+++ KILL  (total K/D/A: %d/%d/%d)",
        new.kills,
        new.deaths,
        new.assists,
    )


@gsi.on_local_player_death
async def player_death(old: PlayerState | None, new: PlayerState) -> None:
    log.info("--- DEATH")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Listening for CS2 GSI on http://127.0.0.1:%d", PORT)
    log.info("Player filter: %s", STEAM_ID)
    log.info("Waiting for CS2 payloads...")
    gsi.run()
