# CLAUDE.md

## What this is

`pygsi` is a pip-installable Python library for receiving live Counter-Strike 2 Game State Integration (GSI) data. CS2 sends HTTP POST payloads to a local or remote server whenever game state changes. This library parses those payloads into strongly-typed Pydantic models and fires async event handlers on specific in-game transitions.

## Architecture

Three layers:

- **`models.py`** — Public API types. These are the types library users import and interact with directly (`GameState`, `RoundState`, `PlayerState`, etc.).
- **`_payload.py`** — Internal only. Parses raw CS2 JSON into public types. Exists because CS2 sends some field names that differ from our public API (e.g. `win_team` → `winning_team`). All models here use `extra='ignore'` so unknown or future CS2 fields never break parsing.
- **`server.py`** — `GSIServer` class. Owns a FastAPI app, maintains current `GameState` in memory, diffs old vs new state to detect transitions, and dispatches async event handlers.

## Critical constraints

**Active players only, not spectators or observers.**
The following CS2 GSI components return no data for active players and are intentionally out of scope:
- `allplayers`, `allplayers_state`, `allplayers_match_stats`, `allplayers_weapons`, `allplayers_position`
- `bomb` (position/carrier), `allgrenades`, `phase_countdowns`, `player_position`

Do not add support for these without explicitly confirming the use case is observer/spectator mode.

**Always return 200 OK to CS2.**
The CS2 client stops sending updates if it receives a non-2xx response. The server must return 200 even on validation errors or exceptions. This is enforced in `server.py`'s `_build_app` via the `RequestValidationError` handler and the catch-all `try/except` in the `receive` route.

**Filter non-target player data immediately.**
When a player dies and spectates a teammate, CS2 may send that teammate's data in the `player` block. This is filtered out in `_handle_payload` before state is stored or any events fire. `gsi.state.player` always refers to the target player (`player_id`) or is `None`.

**Async handlers only.**
Event handlers must be `async def`. There is no support for synchronous handlers.

## Event handlers

All handlers receive `(old, new)` typed slices of state. `old` is `None` if no prior state exists.

| Event | Trigger | Handler types |
|---|---|---|
| `on_round_start` | `round.phase`: `freezetime` → `live` | `(RoundState \| None, RoundState)` |
| `on_round_end` | `round.phase`: `live` → `over` | `(RoundState \| None, RoundState)` |
| `on_bomb_planted` | `round.bomb` → `planted` | `(RoundState \| None, RoundState)` |
| `on_bomb_defused` | `round.bomb` → `defused` | `(RoundState \| None, RoundState)` |
| `on_bomb_exploded` | `round.bomb` → `exploded` | `(RoundState \| None, RoundState)` |
| `on_local_player_kill` | `player.match_stats.kills` increases | `(PlayerMatchStats \| None, PlayerMatchStats)` |
| `on_local_player_death` | `player.state.health` → `0` | `(PlayerState \| None, PlayerState)` |

Kill victim information is not available — CS2 does not expose it to active players.

## Development

```bash
uv sync --group dev        # install dependencies
uv run ruff format src/    # format
uv run ruff check src/     # lint
uv run mypy src/           # type check
```

mypy is configured with `strict = true`. All functions must have type annotations and return types.

## Adding new events

1. Add the handler registration method to `GSIServer` in `server.py` following the existing pattern.
2. Add the detection logic in a `_check_*` method and call it from `_fire_events`.
3. Add the event key to `self._handlers` in `__init__`.
4. Export any new public types from `__init__.py`.
5. Document the event in `README.md`.

Only add events for data that is available to active players (see constraints above).

## Example

`example/` contains a runnable example (`example.py`), a CS2 GSI config file (`gamestate_integration_pygsi.cfg`), and a README with local setup instructions. The example registers all 7 event handlers and logs every event to the console. Default server port is `4213`.
