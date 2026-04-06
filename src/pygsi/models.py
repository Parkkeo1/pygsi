from enum import StrEnum

from pydantic import BaseModel


class MapPhase(StrEnum):
    WARMUP = "warmup"
    LIVE = "live"
    INTERMISSION = "intermission"
    GAMEOVER = "gameover"


class RoundPhase(StrEnum):
    FREEZETIME = "freezetime"
    LIVE = "live"
    OVER = "over"


class BombStatus(StrEnum):
    PLANTED = "planted"
    DEFUSED = "defused"
    EXPLODED = "exploded"


class Team(StrEnum):
    T = "T"
    CT = "CT"


class Activity(StrEnum):
    PLAYING = "playing"
    MENU = "menu"
    TEXT_INPUT = "textinput"


class MapState(BaseModel):
    name: str
    mode: str
    phase: MapPhase
    round: int
    team_ct_score: int
    team_t_score: int
    round_wins: dict[str, str] = {}


class RoundState(BaseModel):
    phase: RoundPhase
    bomb: BombStatus | None = None
    winning_team: Team | None = None


class PlayerState(BaseModel):
    health: int
    armor: int
    helmet: bool
    flashed: int
    smoked: int
    burning: int
    money: int
    round_kills: int
    round_killhs: int
    equip_value: int


class PlayerMatchStats(BaseModel):
    kills: int
    assists: int
    deaths: int
    mvps: int
    score: int


class Player(BaseModel):
    steamid: str
    name: str
    team: Team
    activity: Activity | None = None
    state: PlayerState
    match_stats: PlayerMatchStats


class GameState(BaseModel):
    map: MapState | None = None
    round: RoundState | None = None
    player: Player | None = None
