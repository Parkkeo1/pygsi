import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ._payload import GSIPayload
from .models import GameState, PlayerMatchStats, PlayerState, RoundState

logger = logging.getLogger(__name__)

Handler = Callable[..., Coroutine[Any, Any, None]]

# Union of all state slices passed to event handlers
_Slice = GameState | RoundState | PlayerMatchStats | PlayerState


class GSIServer:
    """
    Receives live CS2 Game State Integration updates over HTTP and fires
    typed async event handlers when game state transitions occur.

    Usage:
        gsi = GSIServer(player_id="76561198XXXXXXX", port=4000)

        @gsi.on_round_start
        async def handle(old: RoundState | None, new: RoundState):
            print(f"Round started on {gsi.state.map.name}")

        gsi.run()
    """

    def __init__(self, player_id: str, port: int = 4213, host: str = "0.0.0.0") -> None:
        self.player_id = player_id
        self.port = port
        self.host = host

        self._state: GameState | None = None
        self._handlers: dict[str, list[Handler]] = {
            "on_round_start": [],
            "on_round_end": [],
            "on_bomb_planted": [],
            "on_bomb_defused": [],
            "on_bomb_exploded": [],
            "on_local_player_kill": [],
            "on_local_player_death": [],
            "on_state_update": [],
        }
        self._app = self._build_app()

    @property
    def state(self) -> GameState | None:
        """The most recently received full game state. None before first update."""
        return self._state

    # --- Event registration decorators ---

    def on_round_start(self, fn: Handler) -> Handler:
        """Fires when round phase transitions from freezetime to live.

        Handler signature: async def handler(old: RoundState | None, new: RoundState)
        """
        self._handlers["on_round_start"].append(fn)
        return fn

    def on_round_end(self, fn: Handler) -> Handler:
        """Fires when round phase transitions from live to over.

        Handler signature: async def handler(old: RoundState | None, new: RoundState)
        """
        self._handlers["on_round_end"].append(fn)
        return fn

    def on_bomb_planted(self, fn: Handler) -> Handler:
        """Fires when the bomb is planted.

        Handler signature: async def handler(old: RoundState | None, new: RoundState)
        """
        self._handlers["on_bomb_planted"].append(fn)
        return fn

    def on_bomb_defused(self, fn: Handler) -> Handler:
        """Fires when the bomb is defused.

        Handler signature: async def handler(old: RoundState | None, new: RoundState)
        """
        self._handlers["on_bomb_defused"].append(fn)
        return fn

    def on_bomb_exploded(self, fn: Handler) -> Handler:
        """Fires when the bomb explodes.

        Handler signature: async def handler(old: RoundState | None, new: RoundState)
        """
        self._handlers["on_bomb_exploded"].append(fn)
        return fn

    def on_local_player_kill(self, fn: Handler) -> Handler:
        """Fires when the local player registers a kill.

        Handler signature:
            async def handler(old: PlayerMatchStats | None, new: PlayerMatchStats)
        """
        self._handlers["on_local_player_kill"].append(fn)
        return fn

    def on_local_player_death(self, fn: Handler) -> Handler:
        """Fires when the local player's health reaches 0.

        Handler signature: async def handler(old: PlayerState | None, new: PlayerState)
        """
        self._handlers["on_local_player_death"].append(fn)
        return fn

    def on_state_update(self, fn: Handler) -> Handler:
        """Fires on every valid payload after state is stored.

        Handler signature: async def handler(old: GameState | None, new: GameState)
        """
        self._handlers["on_state_update"].append(fn)
        return fn

    # --- Server ---

    def run(self) -> None:
        """Start the GSI server. Blocks until interrupted."""
        uvicorn.run(self._app, host=self.host, port=self.port)

    # --- Internal ---

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _(request: Request, exc: RequestValidationError) -> JSONResponse:
            return JSONResponse(status_code=200, content={"status": "ok"})

        @app.post("/")
        async def receive(request: Request) -> JSONResponse:
            try:
                body = await request.json()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Raw payload:\n%s", json.dumps(body, indent=2)
                    )
                payload = GSIPayload.model_validate(body)
                await self._handle_payload(payload)
            except Exception as e:
                logger.debug("Failed to process GSI payload: %s", e)
            return JSONResponse(status_code=200, content={"status": "ok"})

        return app

    async def _handle_payload(self, payload: GSIPayload) -> None:
        prev_state = self._state
        new_state = payload.to_game_state()
        if new_state.player is not None and new_state.player.steamid != self.player_id:
            new_state = new_state.model_copy(update={"player": None})
        self._state = new_state
        await self._fire_events(prev_state, self._state)

    async def _fire_events(self, prev: GameState | None, curr: GameState) -> None:
        await self._dispatch("on_state_update", prev, curr)
        await self._check_round_events(prev, curr)
        await self._check_bomb_events(prev, curr)
        await self._check_player_events(prev, curr)

    async def _check_round_events(
        self, prev: GameState | None, curr: GameState
    ) -> None:
        if curr.round is None:
            return
        prev_round = prev.round if prev else None
        prev_phase = prev_round.phase if prev_round else None

        if prev_phase != "live" and curr.round.phase == "live":
            await self._dispatch("on_round_start", prev_round, curr.round)
        elif prev_phase == "live" and curr.round.phase == "over":
            await self._dispatch("on_round_end", prev_round, curr.round)

    async def _check_bomb_events(self, prev: GameState | None, curr: GameState) -> None:
        if curr.round is None:
            return
        prev_round = prev.round if prev else None
        prev_bomb = prev_round.bomb if prev_round else None
        curr_bomb = curr.round.bomb

        if prev_bomb != "planted" and curr_bomb == "planted":
            await self._dispatch("on_bomb_planted", prev_round, curr.round)
        elif prev_bomb == "planted" and curr_bomb == "defused":
            await self._dispatch("on_bomb_defused", prev_round, curr.round)
        elif prev_bomb == "planted" and curr_bomb == "exploded":
            await self._dispatch("on_bomb_exploded", prev_round, curr.round)

    async def _check_player_events(
        self, prev: GameState | None, curr: GameState
    ) -> None:
        if curr.player is None:
            return

        prev_player = prev.player if prev else None

        curr_kills = curr.player.match_stats.kills
        prev_kills = prev_player.match_stats.kills if prev_player else None
        if prev_kills is not None and curr_kills > prev_kills:
            await self._dispatch(
                "on_local_player_kill",
                prev_player.match_stats if prev_player else None,
                curr.player.match_stats,
            )

        curr_health = curr.player.state.health
        prev_health = prev_player.state.health if prev_player else None
        if prev_health is not None and prev_health > 0 and curr_health == 0:
            await self._dispatch(
                "on_local_player_death",
                prev_player.state if prev_player else None,
                curr.player.state,
            )

    async def _dispatch(self, event: str, old: _Slice | None, new: _Slice) -> None:
        for handler in self._handlers[event]:
            try:
                await handler(old, new)
            except Exception as e:
                logger.exception(
                    "Error in %s handler '%s': %s", event, handler.__name__, e
                )
