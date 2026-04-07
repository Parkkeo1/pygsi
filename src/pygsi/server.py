import asyncio
import json
import logging
from collections.abc import Callable, Coroutine, Sequence
from enum import StrEnum
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ._payload import GSIPayload
from .models import (
    BombStatus,
    GameState,
    MapPhase,
    MapState,
    PlayerMatchStats,
    PlayerState,
    RoundPhase,
    RoundState,
)

logger = logging.getLogger(__name__)

Handler = Callable[..., Coroutine[Any, Any, None]]

# Union of all state slices passed to event handlers
_Slice = GameState | MapState | RoundState | PlayerMatchStats | PlayerState


class Event(StrEnum):
    ROUND_START = "on_round_start"
    ROUND_END = "on_round_end"
    BOMB_PLANTED = "on_bomb_planted"
    BOMB_DEFUSED = "on_bomb_defused"
    BOMB_EXPLODED = "on_bomb_exploded"
    LOCAL_PLAYER_KILL = "on_local_player_kill"
    LOCAL_PLAYER_DEATH = "on_local_player_death"
    STATE_UPDATE = "on_state_update"
    MATCH_END = "on_match_end"
    MAP_START = "on_map_start"


class GSIServer:
    """
    Receives live CS2 Game State Integration updates over HTTP and fires
    typed async event handlers when game state transitions occur.

    Supports tracking one or more players. Each player's state is tracked
    independently, and event handlers receive the player_id that triggered
    the event as the first argument.

    Usage:
        gsi = GSIServer(player_ids="76561198XXXXXXX", port=4000)

        @gsi.on_round_start
        async def handle(player_id: str, old: RoundState | None, new: RoundState):
            print(f"Round started for {player_id}")

        gsi.run()
    """

    def __init__(
        self, player_ids: str | Sequence[str], port: int = 4213, host: str = "0.0.0.0"
    ) -> None:
        if isinstance(player_ids, str):
            self._player_ids = frozenset({player_ids})
        else:
            self._player_ids = frozenset(player_ids)

        self.port = port
        self.host = host

        self._states: dict[str, GameState | None] = dict.fromkeys(
            self._player_ids
        )
        self._handlers: dict[Event, list[Handler]] = {event: [] for event in Event}
        self._app = self._build_app()

    @property
    def player_ids(self) -> frozenset[str]:
        """The set of player steamids being tracked."""
        return self._player_ids

    @property
    def states(self) -> dict[str, GameState | None]:
        """Per-player game state. Keyed by steamid."""
        return self._states

    @property
    def state(self) -> GameState | None:
        """Convenience accessor for single-player mode.

        Returns the tracked player's state. Raises RuntimeError if multiple
        players are configured — use ``states`` instead.
        """
        if len(self._player_ids) != 1:
            raise RuntimeError(
                "GSIServer.state is only available with a single player_id. "
                "Use GSIServer.states for multi-player."
            )
        return next(iter(self._states.values()))

    # --- Event registration decorators ---

    def on_round_start(self, fn: Handler) -> Handler:
        """Fires when round phase transitions from freezetime to live.

        Handler signature:
            async def handler(player_id: str, old: RoundState | None, new: RoundState)
        """
        self._handlers[Event.ROUND_START].append(fn)
        return fn

    def on_round_end(self, fn: Handler) -> Handler:
        """Fires when round phase transitions from live to over.

        Handler signature:
            async def handler(player_id: str, old: RoundState | None, new: RoundState)
        """
        self._handlers[Event.ROUND_END].append(fn)
        return fn

    def on_bomb_planted(self, fn: Handler) -> Handler:
        """Fires when the bomb is planted.

        Handler signature:
            async def handler(player_id: str, old: RoundState | None, new: RoundState)
        """
        self._handlers[Event.BOMB_PLANTED].append(fn)
        return fn

    def on_bomb_defused(self, fn: Handler) -> Handler:
        """Fires when the bomb is defused.

        Handler signature:
            async def handler(player_id: str, old: RoundState | None, new: RoundState)
        """
        self._handlers[Event.BOMB_DEFUSED].append(fn)
        return fn

    def on_bomb_exploded(self, fn: Handler) -> Handler:
        """Fires when the bomb explodes.

        Handler signature:
            async def handler(player_id: str, old: RoundState | None, new: RoundState)
        """
        self._handlers[Event.BOMB_EXPLODED].append(fn)
        return fn

    def on_local_player_kill(self, fn: Handler) -> Handler:
        """Fires when the tracked player registers a kill.

        Handler signature:
            async def handler(
                player_id: str,
                old: PlayerMatchStats | None,
                new: PlayerMatchStats,
            )
        """
        self._handlers[Event.LOCAL_PLAYER_KILL].append(fn)
        return fn

    def on_local_player_death(self, fn: Handler) -> Handler:
        """Fires when the tracked player's health reaches 0.

        Handler signature:
            async def handler(player_id: str, old: PlayerState | None, new: PlayerState)
        """
        self._handlers[Event.LOCAL_PLAYER_DEATH].append(fn)
        return fn

    def on_state_update(self, fn: Handler) -> Handler:
        """Fires on every valid payload after state is stored.

        Handler signature:
            async def handler(player_id: str, old: GameState | None, new: GameState)
        """
        self._handlers[Event.STATE_UPDATE].append(fn)
        return fn

    def on_map_start(self, fn: Handler) -> Handler:
        """Fires when a new map begins (first live payload after warmup or prior match).

        Handler signature:
            async def handler(player_id: str, old: MapState | None, new: MapState)
        """
        self._handlers[Event.MAP_START].append(fn)
        return fn

    def on_match_end(self, fn: Handler) -> Handler:
        """Fires when map phase transitions to gameover (match is over).

        Handler signature:
            async def handler(player_id: str, old: MapState | None, new: MapState)
        """
        self._handlers[Event.MATCH_END].append(fn)
        return fn

    # --- Server ---

    def run(self) -> None:
        """Start the GSI server. Blocks until interrupted."""
        uvicorn.run(self._app, host=self.host, port=self.port)

    # --- Internal ---

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def handle_validation_error(
            request: Request, exc: RequestValidationError
        ) -> JSONResponse:
            logger.error("Request validation error: %s", exc)
            return JSONResponse(status_code=200, content={"status": "ok"})

        @app.post("/")
        async def receive(request: Request) -> JSONResponse:
            try:
                body = await request.json()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Raw payload:\n%s", json.dumps(body, indent=2))

                payload = GSIPayload.model_validate(body)
                await self._handle_payload(payload)
            except Exception as e:
                logger.error("Failed to process GSI payload: %s", e)

            return JSONResponse(status_code=200, content={"status": "ok"})

        return app

    async def _handle_payload(self, payload: GSIPayload) -> None:
        new_state = payload.to_game_state()

        if new_state.map is None:
            return

        # Identify which player sent this payload via the provider block
        provider_id = payload.provider_steamid
        if provider_id is None or provider_id not in self._player_ids:
            return

        # Match end: fire event and stop — don't fire other events
        if new_state.map.phase == MapPhase.GAMEOVER:
            prev_state = self._states[provider_id]
            prev_map = prev_state.map if prev_state else None
            if prev_map is not None and prev_map.phase == MapPhase.LIVE:
                await self._dispatch(
                    Event.MATCH_END, provider_id, prev_map, new_state.map
                )
            self._states[provider_id] = new_state
            await self._dispatch(Event.STATE_UPDATE, provider_id, prev_state, new_state)
            return

        # Only process payloads during a live match (skip warmup, menu, etc.)
        if new_state.map.phase != MapPhase.LIVE:
            return

        # After death, CS2 sends the spectated teammate's data — null it out
        # so state.player is always the target player or None
        if new_state.player is not None and new_state.player.steamid != provider_id:
            new_state = new_state.model_copy(update={"player": None})

        prev_state = self._states[provider_id]
        self._states[provider_id] = new_state

        await self._fire_events(provider_id, prev_state, new_state)

    async def _fire_events(
        self, player_id: str, prev: GameState | None, curr: GameState
    ) -> None:
        await self._dispatch(Event.STATE_UPDATE, player_id, prev, curr)
        await self._handle_map_events(player_id, prev, curr)
        await self._handle_round_events(player_id, prev, curr)
        await self._handle_bomb_events(player_id, prev, curr)
        await self._handle_player_events(player_id, prev, curr)

    async def _handle_map_events(
        self, player_id: str, prev: GameState | None, curr: GameState
    ) -> None:
        assert curr.map is not None
        prev_map = prev.map if prev else None
        # Fire on the first LIVE payload after warmup (prev is None) or after a
        # previous match ended (prev_map.phase == GAMEOVER)
        if prev_map is None or prev_map.phase == MapPhase.GAMEOVER:
            await self._dispatch(Event.MAP_START, player_id, prev_map, curr.map)

    async def _handle_round_events(
        self, player_id: str, prev: GameState | None, curr: GameState
    ) -> None:
        if curr.round is None:
            return
        prev_round = prev.round if prev else None
        prev_phase = prev_round.phase if prev_round else None

        if prev_phase != RoundPhase.LIVE and curr.round.phase == RoundPhase.LIVE:
            await self._dispatch(Event.ROUND_START, player_id, prev_round, curr.round)
        elif prev_phase == RoundPhase.LIVE and curr.round.phase == RoundPhase.OVER:
            await self._dispatch(Event.ROUND_END, player_id, prev_round, curr.round)

    async def _handle_bomb_events(
        self, player_id: str, prev: GameState | None, curr: GameState
    ) -> None:
        if curr.round is None:
            return
        prev_round = prev.round if prev else None
        prev_bomb = prev_round.bomb if prev_round else None
        curr_bomb = curr.round.bomb

        if prev_bomb != BombStatus.PLANTED and curr_bomb == BombStatus.PLANTED:
            await self._dispatch(Event.BOMB_PLANTED, player_id, prev_round, curr.round)
        elif prev_bomb == BombStatus.PLANTED and curr_bomb == BombStatus.DEFUSED:
            await self._dispatch(Event.BOMB_DEFUSED, player_id, prev_round, curr.round)
        elif prev_bomb == BombStatus.PLANTED and curr_bomb == BombStatus.EXPLODED:
            await self._dispatch(Event.BOMB_EXPLODED, player_id, prev_round, curr.round)

    async def _handle_player_events(
        self, player_id: str, prev: GameState | None, curr: GameState
    ) -> None:
        if curr.player is None:
            return

        prev_player = prev.player if prev else None

        curr_kills = curr.player.match_stats.kills
        prev_kills = prev_player.match_stats.kills if prev_player else None
        if prev_kills is not None and curr_kills > prev_kills:
            await self._dispatch(
                Event.LOCAL_PLAYER_KILL,
                player_id,
                prev_player.match_stats if prev_player else None,
                curr.player.match_stats,
            )

        curr_health = curr.player.state.health
        prev_health = prev_player.state.health if prev_player else None
        if prev_health is not None and prev_health > 0 and curr_health == 0:
            await self._dispatch(
                Event.LOCAL_PLAYER_DEATH,
                player_id,
                prev_player.state if prev_player else None,
                curr.player.state,
            )

    async def _dispatch(
        self, event: Event, player_id: str, old: _Slice | None, new: _Slice
    ) -> None:
        async def _run(handler: Handler) -> None:
            try:
                await handler(player_id, old, new)
            except Exception as e:
                logger.exception(
                    "Error in %s handler '%s': %s", event, handler.__name__, e
                )

        await asyncio.gather(*(_run(h) for h in self._handlers[event]))
