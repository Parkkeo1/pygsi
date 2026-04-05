from typing import Literal

from pydantic import BaseModel


class MapState(BaseModel):
    name: str
    mode: str
    phase: Literal["warmup", "live", "intermission", "gameover"]
    round: int
    team_ct_score: int
    team_t_score: int
    round_wins: dict[str, str] = {}


class RoundState(BaseModel):
    phase: Literal["freezetime", "live", "over"]
    bomb: Literal["planted", "defused", "exploded"] | None = None
    winning_team: Literal["CT", "T"] | None = None


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
    team: Literal["T", "CT"]
    activity: str | None = None
    state: PlayerState
    match_stats: PlayerMatchStats


class GameState(BaseModel):
    map: MapState | None = None
    round: RoundState | None = None
    player: Player | None = None
