# pygsi example

Logs every GSI event to the console while you play CS2.

## Prerequisites

- CS2 installed via Steam
- Python 3.14+
- Your **SteamID64** (find it at [steamid.io](https://steamid.io) or by typing `status` in the CS2 console)

## Setup

### 1. Install the GSI config file

Copy `gamestate_integration_pygsi.cfg` into your CS2 cfg directory:

**macOS:**
```
~/Library/Application Support/Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/
```

**Windows:**
```
C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\cfg\
```

**Linux:**
```
~/.steam/steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/
```

> If CS2 is installed to a custom Steam library folder, look under that
> folder's `steamapps/common/` instead.

The filename **must** start with `gamestate_integration_` and end with `.cfg` — CS2 scans for this prefix on launch.

### 2. Edit `example.py`

Open `example.py` and replace the placeholder SteamID:

```python
STEAM_ID = "76561198XXXXXXXXX"  # ← your SteamID64 here
```

### 3. Run the example

From the repo root:

```bash
uv run python example/example.py
```

You should see:

```
12:00:00  Listening for CS2 GSI on http://127.0.0.1:4213
12:00:00  Player filter: 76561198XXXXXXXXX
12:00:00  Waiting for CS2 payloads...
```

### 4. Launch CS2

Start CS2 and join any match (competitive, casual, deathmatch, etc.).
CS2 reads the cfg file on launch, so if CS2 was already running when you
copied the config, **restart CS2**.

Once in a match you will see events printed in real time:

```
12:01:23  >>> ROUND 1 START on de_dust2
12:02:05  +++ KILL  (total K/D/A: 1/0/0)
12:02:18  --- DEATH
12:02:45  *** BOMB PLANTED
12:02:55  *** BOMB DEFUSED
12:03:10  <<< ROUND END — winner: CT
```

## How it works

The cfg file tells CS2 to POST JSON payloads to `http://127.0.0.1:4213`
whenever game state changes. `pygsi` runs a local HTTP server on that
port, parses the payloads into typed Python models, and fires the
registered event handlers.

The cfg subscribes to these GSI components:

| Component | What it provides |
|---|---|
| `provider` | Game name, app ID, client SteamID |
| `player_id` | Current player's name, SteamID, team |
| `player_state` | Health, armor, money, round kills, etc. |
| `player_match_stats` | Total kills, deaths, assists, MVPs, score |
| `player_weapons` | All weapons and their ammo state |
| `map` | Map name, mode, phase, team scores |
| `map_round_wins` | Per-round win conditions |
| `round` | Round phase, bomb status, winning team |

Components like `allplayers_*`, `bomb` (position), `allgrenades`, and
`phase_countdowns` are intentionally excluded — they only return data for
spectators/observers, not active players.

## Troubleshooting

**No output after joining a match?**
- Make sure CS2 was (re)started *after* copying the cfg file.
- Verify the cfg is in the `game/csgo/cfg/` directory (not the old `csgo/cfg/`).
- Check that your SteamID in `example.py` matches `status` output in console.

**"Address already in use" error?**
- Another process is using port 4213. Kill it or change `PORT` in `example.py`
  (and update the `uri` in the cfg to match).

**Events are delayed?**
- The cfg uses `"buffer" "1.0"` and `"throttle" "1.0"` (1 second each).
  Decrease these values for lower latency, increase if you see performance issues.
