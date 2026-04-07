# pygsi

A Python library to interface with CS2's [Game State Integration](https://developer.valvesoftware.com/wiki/Counter-Strike:_Global_Offensive_Game_State_Integration) (GSI). 

Provides a strongly-typed, event-driven API for consuming live GSI data for one or more active players during matches. Not designed for spectators or observers.

## Requirements

- Python 3.14+
- CS2 installed and running on the same machine (or configured to send GSI to your server's address)

## Installation

Install directly from the repository:

```bash
uv add git+https://github.com/Parkkeo1/pygsi
# or
pip install git+https://github.com/Parkkeo1/pygsi
```

For local development:

```bash
git clone https://github.com/Parkkeo1/pygsi
cd pygsi
uv sync --group dev
```


## CS2 Configuration

Create a file named `gamestate_integration_pygsi.cfg` in your CS2 cfg directory. Use the `game/csgo/cfg/` path, **not** the legacy `csgo/cfg/` directory:

```
Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/
```

Paste the following contents:

```
"pygsi"
{
    // replace with your remote server URL if not running locally
    "uri"           "http://127.0.0.1:4213"
    "timeout"       "5.0"
    "buffer"        "1"
    "throttle"      "1"
    "heartbeat"     "30.0"
    "data"
    {
        "provider"            "1"
        "map"                 "1"
        "round"               "1"
        "player_id"           "1"
        "player_state"        "1"
        "player_match_stats"  "1"
    }
}
```

Restart CS2 after adding the file.

## Quickstart

```python
from pygsi import GSIServer, RoundState, PlayerMatchStats, PlayerState

# Track a single player
gsi = GSIServer(player_ids="YOUR_STEAM_ID_64", port=4213)

# Or track multiple players publishing to the same server
# gsi = GSIServer(player_ids=["STEAM_ID_1", "STEAM_ID_2"], port=4213)


@gsi.on_round_start
async def handle_round_start(player_id: str, old: RoundState | None, new: RoundState) -> None:
    state = gsi.states[player_id]
    print(f"[{player_id}] Round started on {state.map.name}")


@gsi.on_round_end
async def handle_round_end(player_id: str, old: RoundState | None, new: RoundState) -> None:
    print(f"[{player_id}] Round over — winner: {new.winning_team}")


@gsi.on_bomb_planted
async def handle_bomb_planted(player_id: str, old: RoundState | None, new: RoundState) -> None:
    print(f"[{player_id}] Bomb planted!")


@gsi.on_local_player_kill
async def handle_kill(player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats) -> None:
    print(f"[{player_id}] Kill! Total this match: {new.kills}")


@gsi.on_local_player_death
async def handle_death(player_id: str, old: PlayerState | None, new: PlayerState) -> None:
    print(f"[{player_id}] You died.")


gsi.run()
```

Run your script, then launch CS2 and join a match. Events will fire in real time as the game progresses.

For a complete working example that logs all events, including the GSI config file and local setup instructions, see the [`example/`](example/) directory.


## API

### `GSIServer`

```python
GSIServer(player_ids: str | Sequence[str], port: int = 4213, host: str = "0.0.0.0")
```

| Parameter | Description |
|---|---|
| `player_ids` | One or more Steam ID 64s to track. Accepts a single string or a list. Payloads from other players are ignored. |
| `port` | Port to listen on. Must match the `uri` in your CS2 GSI config. Defaults to `4213`. |
| `host` | Host to bind to. Defaults to `0.0.0.0` (all interfaces). |

#### `gsi.states`

Per-player game state, keyed by steamid. Accessible at any time, not just inside event handlers.

```python
gsi.states["76561198XXXXXXX"].map.name        # e.g. "de_dust2"
gsi.states["76561198XXXXXXX"].player.name     # player name
```

Each value is `None` before the first update is received for that player.

#### `gsi.state`

Convenience accessor for single-player mode. Returns the tracked player's state. Raises `RuntimeError` if multiple players are configured — use `gsi.states` instead.

```python
gsi.state.map.name        # e.g. "de_dust2"
gsi.state.round.phase     # "freezetime" | "live" | "over"
```

#### `gsi.player_ids`

The `frozenset[str]` of player steamids being tracked.

#### `gsi.run()`

Starts the HTTP server. Blocks until interrupted.


### Event Handlers

Register handlers using decorators. All handlers must be `async` functions. Multiple handlers can be registered for the same event.

Each handler receives `player_id` (the steamid of the player whose payload triggered the event), the previous state (`old`), and the new state (`new`) for the relevant slice of game state. `old` is `None` if no prior state exists for that field.

#### Round events

```python
@gsi.on_round_start
async def handler(player_id: str, old: RoundState | None, new: RoundState) -> None: ...

@gsi.on_round_end
async def handler(player_id: str, old: RoundState | None, new: RoundState) -> None: ...
```

#### Bomb events

```python
@gsi.on_bomb_planted
async def handler(player_id: str, old: RoundState | None, new: RoundState) -> None: ...

@gsi.on_bomb_defused
async def handler(player_id: str, old: RoundState | None, new: RoundState) -> None: ...

@gsi.on_bomb_exploded
async def handler(player_id: str, old: RoundState | None, new: RoundState) -> None: ...
```

#### Map events

```python
@gsi.on_map_start
async def handler(player_id: str, old: MapState | None, new: MapState) -> None: ...

@gsi.on_map_end
async def handler(player_id: str, old: MapState | None, new: MapState) -> None: ...
```

#### Local player events

These events are scoped to the tracked players passed at initialization.

```python
@gsi.on_local_player_kill
async def handler(player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats) -> None: ...

@gsi.on_local_player_assist
async def handler(player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats) -> None: ...

@gsi.on_local_player_mvp
async def handler(player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats) -> None: ...

@gsi.on_local_player_death
async def handler(player_id: str, old: PlayerState | None, new: PlayerState) -> None: ...
```

#### Full state updates

Fires on every valid payload with the complete `GameState`.

```python
@gsi.on_state_update
async def handler(player_id: str, old: GameState | None, new: GameState) -> None: ...
```


### Data Types

#### `GameState`

| Field | Type | Description |
|---|---|---|
| `map` | `MapState \| None` | Current map and score information |
| `round` | `RoundState \| None` | Current round phase and bomb status |
| `player` | `Player \| None` | Local player data |

#### `RoundState`

| Field | Type | Description |
|---|---|---|
| `phase` | `"freezetime" \| "live" \| "over"` | Current round phase |
| `bomb` | `"planted" \| "defused" \| "exploded" \| None` | Bomb status |
| `winning_team` | `"CT" \| "T" \| None` | Winning team, set when phase is `over` |

#### `PlayerState`

| Field | Type | Description |
|---|---|---|
| `health` | `int` | Current health (0–100) |
| `armor` | `int` | Current armor (0–100) |
| `helmet` | `bool` | Has helmet |
| `money` | `int` | Current money |
| `round_kills` | `int` | Kills in current round |
| `flashed` | `int` | Flash intensity (0–255) |
| `equip_value` | `int` | Total value of equipped items |

#### `PlayerMatchStats`

| Field | Type | Description |
|---|---|---|
| `kills` | `int` | Total kills this match |
| `assists` | `int` | Total assists this match |
| `deaths` | `int` | Total deaths this match |
| `mvps` | `int` | MVP awards this match |
| `score` | `int` | Total score this match |

#### `MapState`

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Map name (e.g. `"de_dust2"`) |
| `mode` | `str` | Game mode (e.g. `"competitive"`) |
| `phase` | `"warmup" \| "live" \| "intermission" \| "gameover"` | Match phase |
| `round` | `int` | Current round number |
| `team_ct_score` | `int` | CT rounds won |
| `team_t_score` | `int` | T rounds won |
| `round_wins` | `dict[str, str]` | Round-by-round win history (e.g. `{"1": "ct_win_elimination"}`) |


## Scope and Limitations

pygsi is designed for **active players** (not spectators or observers). The following CS2 GSI components are only available to spectators and will return no data for players in an active match:

- `allplayers` — per-player data for all players in the match
- `bomb` — bomb position and carrier
- `allgrenades` — grenade positions
- `phase_countdowns` — phase countdown timers
- `player_position` — local player position

As a result, player-specific events (`on_local_player_kill`, `on_local_player_death`) are scoped to the **tracked players only**. Kill victim information is not available.


## License

MIT — see [LICENSE](LICENSE).
