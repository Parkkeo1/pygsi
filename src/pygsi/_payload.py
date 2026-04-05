"""
Internal module for parsing raw CS2 GSI JSON payloads into public GameState types.

CS2 sends some field names that differ from our public API (e.g. win_team vs
winning_team). All models here use extra='ignore' so unknown or future fields
don't break parsing.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .models import (
    GameState,
    MapState,
    Player,
    PlayerMatchStats,
    PlayerState,
    RoundState,
    Weapon,
)


class _MapPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    mode: str
    phase: Literal["warmup", "live", "intermission", "gameover"]
    round: int
    team_ct: dict[str, int]
    team_t: dict[str, int]

    def to_public(self) -> MapState:
        return MapState(
            name=self.name,
            mode=self.mode,
            phase=self.phase,
            round=self.round,
            team_ct_score=self.team_ct["score"],
            team_t_score=self.team_t["score"],
        )


class _RoundPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phase: Literal["freezetime", "live", "over"]
    bomb: Literal["planted", "defused", "exploded"] | None = None
    # CS2 sends "win_team", not "winning_team"
    win_team: Literal["CT", "T"] | None = None

    def to_public(self) -> RoundState:
        return RoundState(
            phase=self.phase,
            bomb=self.bomb,
            winning_team=self.win_team,
        )


class _PlayerStatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    health: int
    armor: int
    helmet: bool
    flashed: int
    smoked: int
    burning: int
    money: int
    round_kills: int
    round_killhs: int
    round_totaldmg: int
    equip_value: int
    defusekit: bool | None = None

    def to_public(self) -> PlayerState:
        return PlayerState(**self.model_dump())


class _PlayerMatchStatsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kills: int
    assists: int
    deaths: int
    mvps: int
    score: int

    def to_public(self) -> PlayerMatchStats:
        return PlayerMatchStats(**self.model_dump())


class _WeaponPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    paintkit: str
    type: str
    ammo_clip: int | None = None
    ammo_clip_max: int | None = None
    ammo_reserve: int | None = None
    state: str

    def to_public(self) -> Weapon:
        return Weapon(**self.model_dump())


class _PlayerPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    steamid: str
    name: str
    team: Literal["T", "CT"]
    activity: str | None = None
    state: _PlayerStatePayload
    weapons: dict[str, _WeaponPayload] = {}
    match_stats: _PlayerMatchStatsPayload

    def to_public(self) -> Player:
        return Player(
            steamid=self.steamid,
            name=self.name,
            team=self.team,
            activity=self.activity,
            state=self.state.to_public(),
            weapons={slot: w.to_public() for slot, w in self.weapons.items()},
            match_stats=self.match_stats.to_public(),
        )


class GSIPayload(BaseModel):
    """Top-level CS2 GSI payload.

    Extra fields (previously, added, auth, etc.) are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    map: _MapPayload | None = None
    round: _RoundPayload | None = None
    player: _PlayerPayload | None = None

    def to_game_state(self) -> GameState:
        return GameState(
            map=self.map.to_public() if self.map else None,
            round=self.round.to_public() if self.round else None,
            player=self.player.to_public() if self.player else None,
        )
