# CLAUDE.md

## What this is

`pygsi` is a pip-installable Python library for receiving live Counter-Strike 2 Game State Integration (GSI) data. CS2 sends HTTP POST payloads to a local or remote server whenever game state changes. This library parses those payloads into strongly-typed Pydantic models and fires async event handlers on specific in-game transitions.

## Architecture

Three layers:

- **`models.py`** — Public API types. These are the types library users import and interact with directly (`GameState`, `RoundState`, `PlayerState`, etc.).
- **`_payload.py`** — Internal only. Parses raw CS2 JSON into public types. Exists because CS2 sends some field names that differ from our public API (e.g. `win_team` → `winning_team`). All models here use `extra='ignore'` so unknown or future CS2 fields never break parsing.
- **`_payload.py`** also parses the `provider` block (`provider.steamid`) which identifies the CS2 client that sent the payload. This is used by the server to route payloads to the correct player's state and detect spectating.
- **`server.py`** — `GSIServer` class. Owns a FastAPI app, maintains per-player `GameState` in memory, diffs old vs new state to detect transitions, and dispatches async event handlers. Supports tracking one or multiple players.

## Critical constraints

**Active players only, not spectators or observers.**
The following CS2 GSI components return no data for active players and are intentionally out of scope:
- `allplayers`, `allplayers_state`, `allplayers_match_stats`, `allplayers_weapons`, `allplayers_position`
- `bomb` (position/carrier), `allgrenades`, `phase_countdowns`, `player_position`

Do not add support for these without explicitly confirming the use case is observer/spectator mode.

**Always return 200 OK to CS2.**
The CS2 client stops sending updates if it receives a non-2xx response. The server must return 200 even on validation errors or exceptions. This is enforced in `server.py`'s `_build_app` via the `RequestValidationError` handler and the catch-all `try/except` in the `receive` route.

**Filter non-target player data immediately.**
When a player dies and spectates a teammate, CS2 may send that teammate's data in the `player` block. Detection uses `provider.steamid` (always the CS2 client owner) vs `player.steamid` (changes to spectated player). This is filtered out in `_handle_payload` before state is stored or any events fire. Each player's state `.player` always refers to that tracked player or is `None`.

**Multi-player support via `provider.steamid` routing.**
`GSIServer` accepts one or more player IDs. Each CS2 client's payload is routed to the correct player's state using `provider.steamid`. Payloads from unknown players (not in `player_ids`) are silently ignored. Per-player state is fully independent — no cross-contamination even when players are in the same match and spectating each other.

**Async handlers only.**
Event handlers must be `async def`. There is no support for synchronous handlers.

## Event handlers

All handlers receive `(player_id, old, new)` — the steamid of the player whose payload triggered the event, followed by typed slices of state. `old` is `None` if no prior state exists.

| Event | Trigger | Handler types |
|---|---|---|
| `on_round_start` | `round.phase`: `freezetime` → `live` | `(str, RoundState \| None, RoundState)` |
| `on_round_end` | `round.phase`: `live` → `over` | `(str, RoundState \| None, RoundState)` |
| `on_bomb_planted` | `round.bomb` → `planted` | `(str, RoundState \| None, RoundState)` |
| `on_bomb_defused` | `round.bomb` → `defused` | `(str, RoundState \| None, RoundState)` |
| `on_bomb_exploded` | `round.bomb` → `exploded` | `(str, RoundState \| None, RoundState)` |
| `on_local_player_kill` | `player.match_stats.kills` increases | `(str, PlayerMatchStats \| None, PlayerMatchStats)` |
| `on_local_player_death` | `player.state.health` → `0` | `(str, PlayerState \| None, PlayerState)` |
| `on_state_update` | Every valid payload | `(str, GameState \| None, GameState)` |

Kill victim information is not available — CS2 does not expose it to active players.

## Development

```bash
uv sync --group dev        # install dependencies
uv run ruff format src/    # format
uv run ruff check src/     # lint
uv run mypy src/           # type check
```

mypy is configured with `strict = true`. All functions must have type annotations and return types.

## Testing

```bash
uv sync --group test           # install test dependencies
uv run pytest tests/ -v        # run tests
```

Integration tests live in `tests/` and use real CS2 GSI payloads captured from a practice match (`tests/fixtures.json`). Tests exercise the full stack via FastAPI's in-process ASGI transport (`httpx.AsyncClient` + `ASGITransport`) — no real server or port needed.

**Stack:** pytest, pytest-asyncio (auto mode), httpx.

**What's tested:**
- **State parsing** — all model fields correctly parsed from raw JSON (map, round, player state, match stats, enums)
- **Payload filtering** — warmup/menu payloads ignored, spectating teammate nulls player, filtered payloads don't wipe existing state
- **State transitions** — state updates correctly across sequential payloads
- **Event handlers** — all 8 event types fire on correct transitions with correct `(player_id, old, new)` arguments
- **Edge cases** — events not fired without required prior state, death not re-fired when already dead, bomb exploded requires prior planted
- **Multiple events** — single payload can trigger multiple events simultaneously, multiple handlers per event
- **Multi-player** — per-player state tracking, events fire with correct player_id, unknown players ignored, `gsi.state` raises for multi-player setups, spectating routes correctly via provider.steamid
- **Error isolation** — failing handler doesn't block others, server always returns 200
- **HTTP behavior** — always returns 200 even on invalid/empty payloads

**Adding tests for new events:** add fixture payloads to `tests/fixtures.json` (strip `previously`/`added` keys from raw CS2 JSON), then add test cases following the existing pattern in `tests/test_integration.py`.

## Adding new events

1. Add the handler registration method to `GSIServer` in `server.py` following the existing pattern.
2. Add the detection logic in a `_check_*` method and call it from `_fire_events`.
3. Add the event key to `self._handlers` in `__init__`.
4. Export any new public types from `__init__.py`.
5. Document the event in `README.md`.

Only add events for data that is available to active players (see constraints above).

## Examples

`example/` contains runnable examples and a GSI config file with a README for local setup:
- `simple.py` — registers all event handlers and logs every event to the console.
