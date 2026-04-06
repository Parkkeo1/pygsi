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
# Replace with your SteamID64(s).
# Find yours at https://steamid.io or by typing `status` in the CS2 console.
STEAM_IDS = ["76561198XXXXXXXXX"]
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
_debug_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
)
logging.getLogger("pygsi.server").addHandler(_debug_handler)
logging.getLogger("pygsi.server").setLevel(logging.DEBUG)

gsi = GSIServer(player_ids=STEAM_IDS, port=PORT)


# ── Round events ──────────────────────────────────────────────────────────────


@gsi.on_round_start
async def round_start(player_id: str, old: RoundState | None, new: RoundState) -> None:
    state = gsi.states[player_id]
    map_name = state.map.name if state and state.map else "unknown"
    round_num = state.map.round if state and state.map else "?"
    log.info("[%s] >>> ROUND %s START on %s", player_id, round_num, map_name)


@gsi.on_round_end
async def round_end(player_id: str, old: RoundState | None, new: RoundState) -> None:
    winner = new.winning_team or "unknown"
    log.info("[%s] <<< ROUND END — winner: %s", player_id, winner)


# ── Bomb events ───────────────────────────────────────────────────────────────


@gsi.on_bomb_planted
async def bomb_planted(player_id: str, old: RoundState | None, new: RoundState) -> None:
    log.info("[%s] *** BOMB PLANTED", player_id)


@gsi.on_bomb_defused
async def bomb_defused(player_id: str, old: RoundState | None, new: RoundState) -> None:
    log.info("[%s] *** BOMB DEFUSED", player_id)


@gsi.on_bomb_exploded
async def bomb_exploded(
    player_id: str, old: RoundState | None, new: RoundState
) -> None:
    log.info("[%s] *** BOMB EXPLODED", player_id)


# ── Player events ─────────────────────────────────────────────────────────────


@gsi.on_local_player_kill
async def player_kill(
    player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats
) -> None:
    log.info(
        "[%s] +++ KILL  (total K/D/A: %d/%d/%d)",
        player_id,
        new.kills,
        new.deaths,
        new.assists,
    )


@gsi.on_local_player_death
async def player_death(
    player_id: str, old: PlayerState | None, new: PlayerState
) -> None:
    log.info("[%s] --- DEATH", player_id)


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Listening for CS2 GSI on http://127.0.0.1:%d", PORT)
    log.info("Tracking players: %s", STEAM_IDS)
    log.info("Waiting for CS2 payloads...")
    gsi.run()
