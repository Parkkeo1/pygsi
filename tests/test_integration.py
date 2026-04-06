"""Integration tests using real CS2 GSI payloads captured from a practice match.

Tests exercise the full stack: HTTP POST -> payload parsing -> state management
-> event handler dispatch, using FastAPI's in-process ASGI transport (no real
server or port needed).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from pygsi import (
    Activity,
    BombStatus,
    GameState,
    GSIServer,
    MapPhase,
    PlayerMatchStats,
    PlayerState,
    RoundPhase,
    RoundState,
    Team,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PLAYER_ID = "76561198000000000"
PLAYER_2_ID = "76561198000000001"


async def post(client: AsyncClient, payload: dict[str, Any]) -> None:
    resp = await client.post("/", json=payload)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# State parsing: verify that raw payloads are parsed into correct model values
# ---------------------------------------------------------------------------


class TestStateParsing:
    async def test_mid_round_state(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """A mid-round payload should fully populate map, round, and player."""
        await post(client, fixtures["mid_round"])

        state = gsi.state
        assert state is not None

        # Map
        assert state.map is not None
        assert state.map.name == "de_dust2"
        assert state.map.mode == "competitive"
        assert state.map.phase == MapPhase.LIVE
        assert state.map.round == 4
        assert state.map.team_ct_score == 2
        assert state.map.team_t_score == 2
        assert state.map.round_wins == {
            "1": "ct_win_elimination",
            "2": "ct_win_elimination",
            "3": "t_win_bomb",
            "4": "t_win_elimination",
        }

        # Round
        assert state.round is not None
        assert state.round.phase == RoundPhase.LIVE
        assert state.round.bomb is None
        assert state.round.winning_team is None

        # Player
        assert state.player is not None
        assert state.player.steamid == "76561198000000000"
        assert state.player.name == "TestPlayer"
        assert state.player.team == Team.T
        assert state.player.activity == Activity.PLAYING

        # Player state
        assert state.player.state.health == 100
        assert state.player.state.armor == 0
        assert state.player.state.helmet is False
        assert state.player.state.money == 5850
        assert state.player.state.equip_value == 2900

        # Match stats
        assert state.player.match_stats.kills == 10
        assert state.player.match_stats.assists == 1
        assert state.player.match_stats.deaths == 2
        assert state.player.match_stats.mvps == 2
        assert state.player.match_stats.score == 13

    async def test_freezetime_state(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Freezetime payload: round phase should be FREEZETIME."""
        await post(client, fixtures["freezetime_before_round_start"])

        state = gsi.state
        assert state is not None
        assert state.round is not None
        assert state.round.phase == RoundPhase.FREEZETIME

    async def test_round_over_with_bomb_exploded(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Round-over payload with bomb exploded and win_team mapped correctly."""
        # Need a prior state first so the server is in live phase
        await post(client, fixtures["before_round_end"])
        await post(client, fixtures["round_end_bomb_explode_death"])

        state = gsi.state
        assert state is not None
        assert state.round is not None
        assert state.round.phase == RoundPhase.OVER
        assert state.round.bomb == BombStatus.EXPLODED
        assert state.round.winning_team == Team.T

    async def test_bomb_planted_state(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """After bomb plant, round.bomb should be PLANTED."""
        await post(client, fixtures["bomb_planted"])

        state = gsi.state
        assert state is not None
        assert state.round is not None
        assert state.round.bomb == BombStatus.PLANTED


# ---------------------------------------------------------------------------
# Payload filtering: warmup, menu, and non-target player payloads
# ---------------------------------------------------------------------------


class TestPayloadFiltering:
    async def test_warmup_ignored(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Warmup payloads should not update state."""
        await post(client, fixtures["warmup"])
        assert gsi.state is None

    async def test_menu_ignored(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Menu payloads (no map) should not update state."""
        await post(client, fixtures["menu"])
        assert gsi.state is None

    async def test_spectating_teammate_nulls_player(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """When spectating a teammate, player should be set to None."""
        # First establish state with own player data
        await post(client, fixtures["mid_round"])
        assert gsi.state is not None
        assert gsi.state.player is not None

        # Now send a payload where we're spectating a bot (steamid=503)
        await post(client, fixtures["spectating_teammate"])
        assert gsi.state is not None
        assert gsi.state.player is None

    async def test_state_persists_after_filtered_payload(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Warmup/menu payloads should not wipe existing state."""
        await post(client, fixtures["mid_round"])
        assert gsi.state is not None

        await post(client, fixtures["warmup"])
        # State should still be the mid_round state, not wiped
        assert gsi.state is not None
        assert gsi.state.map is not None
        assert gsi.state.map.round == 4


# ---------------------------------------------------------------------------
# State transitions: verify state updates correctly across multiple payloads
# ---------------------------------------------------------------------------


class TestStateTransitions:
    async def test_state_updates_across_payloads(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """State should reflect the latest payload, not accumulate."""
        await post(client, fixtures["freezetime_before_round_start"])
        assert gsi.state is not None
        assert gsi.state.round is not None
        assert gsi.state.round.phase == RoundPhase.FREEZETIME
        assert gsi.state.map is not None
        assert gsi.state.map.round == 0

        await post(client, fixtures["round_start"])
        state2 = gsi.state
        assert state2 is not None
        assert state2.round is not None
        assert state2.round.phase == RoundPhase.LIVE

        await post(client, fixtures["mid_round"])
        state3 = gsi.state
        assert state3 is not None
        assert state3.map is not None
        assert state3.map.round == 4
        assert state3.player is not None
        assert state3.player.match_stats.kills == 10

    async def test_bomb_lifecycle(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Track bomb from no-bomb -> planted -> exploded."""
        await post(client, fixtures["before_bomb_plant"])
        assert gsi.state is not None
        assert gsi.state.round is not None
        assert gsi.state.round.bomb is None

        await post(client, fixtures["bomb_planted"])
        assert gsi.state.round is not None
        assert gsi.state.round.bomb == BombStatus.PLANTED

        await post(client, fixtures["round_end_bomb_explode_death"])
        assert gsi.state.round is not None
        assert gsi.state.round.bomb == BombStatus.EXPLODED


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


class TestRoundEvents:
    async def test_round_start_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_round_start
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["freezetime_before_round_start"])
        await post(client, fixtures["round_start"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert old.phase == RoundPhase.FREEZETIME
        assert new.phase == RoundPhase.LIVE

    async def test_round_start_not_fired_on_first_live_payload(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """First payload with round=live (no prior freezetime) should still fire
        round_start because prev_phase is None != LIVE."""
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_round_start
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["round_start"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is None
        assert new.phase == RoundPhase.LIVE

    async def test_round_end_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_round_end
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["before_round_end"])
        await post(client, fixtures["round_end_bomb_explode_death"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert old.phase == RoundPhase.LIVE
        assert new.phase == RoundPhase.OVER
        assert new.winning_team == Team.T

    async def test_round_end_not_fired_without_prior_live(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Round end requires prior phase to be LIVE."""
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_round_end
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        # Send round=over without prior round=live
        await post(client, fixtures["round_end_bomb_explode_death"])

        assert len(calls) == 0


class TestBombEvents:
    async def test_bomb_planted_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_bomb_planted
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["before_bomb_plant"])
        await post(client, fixtures["bomb_planted"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert old.bomb is None
        assert new.bomb == BombStatus.PLANTED

    async def test_bomb_exploded_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_bomb_exploded
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["before_round_end"])
        await post(client, fixtures["round_end_bomb_explode_death"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert old.bomb == BombStatus.PLANTED
        assert new.bomb == BombStatus.EXPLODED

    async def test_bomb_exploded_requires_prior_planted(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Bomb exploded should not fire if prior bomb was not PLANTED."""
        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_bomb_exploded
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        # Send exploded without prior planted
        await post(client, fixtures["round_end_bomb_explode_death"])
        assert len(calls) == 0


class TestPlayerEvents:
    async def test_kill_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, PlayerMatchStats | None, PlayerMatchStats]] = []

        @gsi.on_local_player_kill
        async def handler(
            player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["before_kill"])
        await post(client, fixtures["after_kill"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert new.kills == old.kills + 1

    async def test_kill_not_fired_on_first_payload(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Kill requires a prior state to compare against."""
        calls: list[tuple[str, PlayerMatchStats | None, PlayerMatchStats]] = []

        @gsi.on_local_player_kill
        async def handler(
            player_id: str, old: PlayerMatchStats | None, new: PlayerMatchStats
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["after_kill"])
        assert len(calls) == 0

    async def test_death_fires(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, PlayerState | None, PlayerState]] = []

        @gsi.on_local_player_death
        async def handler(
            player_id: str, old: PlayerState | None, new: PlayerState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["before_round_end"])
        await post(client, fixtures["round_end_bomb_explode_death"])

        assert len(calls) == 1
        pid, old, new = calls[0]
        assert pid == PLAYER_ID
        assert old is not None
        assert old.health > 0
        assert new.health == 0

    async def test_death_not_fired_when_already_dead(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Death requires prior health > 0."""
        calls: list[tuple[str, PlayerState | None, PlayerState]] = []

        @gsi.on_local_player_death
        async def handler(
            player_id: str, old: PlayerState | None, new: PlayerState
        ) -> None:
            calls.append((player_id, old, new))

        # Send death payload twice — second should not fire
        await post(client, fixtures["before_round_end"])
        await post(client, fixtures["round_end_bomb_explode_death"])
        assert len(calls) == 1

        await post(client, fixtures["round_end_bomb_explode_death"])
        assert len(calls) == 1  # still 1, not 2


class TestStateUpdateEvent:
    async def test_fires_on_every_valid_payload(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, GameState | None, GameState]] = []

        @gsi.on_state_update
        async def handler(
            player_id: str, old: GameState | None, new: GameState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["freezetime_before_round_start"])
        await post(client, fixtures["round_start"])
        await post(client, fixtures["mid_round"])

        assert len(calls) == 3

        # First call: old is None
        assert calls[0][1] is None
        assert calls[0][2].round is not None

        # Subsequent calls: old is the previous state
        assert calls[1][1] is not None
        assert calls[2][1] is not None

        # All calls have correct player_id
        assert all(c[0] == PLAYER_ID for c in calls)

    async def test_not_fired_for_warmup(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, GameState | None, GameState]] = []

        @gsi.on_state_update
        async def handler(
            player_id: str, old: GameState | None, new: GameState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["warmup"])
        assert len(calls) == 0

    async def test_not_fired_for_menu(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        calls: list[tuple[str, GameState | None, GameState]] = []

        @gsi.on_state_update
        async def handler(
            player_id: str, old: GameState | None, new: GameState
        ) -> None:
            calls.append((player_id, old, new))

        await post(client, fixtures["menu"])
        assert len(calls) == 0


class TestMultipleEvents:
    async def test_round_end_bomb_explode_death_fires_all_three(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """A single payload can trigger multiple events simultaneously."""
        round_end_calls: list[tuple[str, RoundState | None, RoundState]] = []
        bomb_exploded_calls: list[tuple[str, RoundState | None, RoundState]] = []
        death_calls: list[tuple[str, PlayerState | None, PlayerState]] = []
        state_update_calls: list[tuple[str, GameState | None, GameState]] = []

        @gsi.on_round_end
        async def on_round_end(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            round_end_calls.append((player_id, old, new))

        @gsi.on_bomb_exploded
        async def on_bomb_exploded(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            bomb_exploded_calls.append((player_id, old, new))

        @gsi.on_local_player_death
        async def on_death(
            player_id: str, old: PlayerState | None, new: PlayerState
        ) -> None:
            death_calls.append((player_id, old, new))

        @gsi.on_state_update
        async def on_state(
            player_id: str, old: GameState | None, new: GameState
        ) -> None:
            state_update_calls.append((player_id, old, new))

        # First set up prior state (live round, bomb planted, player alive)
        await post(client, fixtures["before_round_end"])
        # Then the triple-event payload
        await post(client, fixtures["round_end_bomb_explode_death"])

        assert len(round_end_calls) == 1
        assert len(bomb_exploded_calls) == 1
        assert len(death_calls) == 1
        assert len(state_update_calls) == 2  # both payloads fire state_update

    async def test_multiple_handlers_for_same_event(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Multiple handlers registered for the same event should all fire."""
        calls_a: list[RoundState] = []
        calls_b: list[RoundState] = []

        @gsi.on_round_start
        async def handler_a(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls_a.append(new)

        @gsi.on_round_start
        async def handler_b(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls_b.append(new)

        await post(client, fixtures["freezetime_before_round_start"])
        await post(client, fixtures["round_start"])

        assert len(calls_a) == 1
        assert len(calls_b) == 1


class TestHandlerErrorIsolation:
    async def test_failing_handler_does_not_block_others(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """An exception in one handler should not block other handlers."""
        calls: list[RoundState] = []

        @gsi.on_round_start
        async def bad_handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            raise RuntimeError("intentional test error")

        @gsi.on_round_start
        async def good_handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append(new)

        await post(client, fixtures["freezetime_before_round_start"])
        await post(client, fixtures["round_start"])

        assert len(calls) == 1

    async def test_server_returns_200_on_handler_error(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Server must always return 200, even when handlers throw."""

        @gsi.on_state_update
        async def bad_handler(
            player_id: str, old: GameState | None, new: GameState
        ) -> None:
            raise RuntimeError("intentional test error")

        resp = await client.post("/", json=fixtures["mid_round"])
        assert resp.status_code == 200


class TestHttpBehavior:
    async def test_always_returns_200(
        self, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Every POST should return 200, valid payload or not."""
        resp = await client.post("/", json=fixtures["mid_round"])
        assert resp.status_code == 200

    async def test_returns_200_on_invalid_json(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/", content=b"not json", headers={"content-type": "application/json"}
        )
        assert resp.status_code == 200

    async def test_returns_200_on_empty_body(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/", content=b"{}", headers={"content-type": "application/json"}
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Multi-player support
# ---------------------------------------------------------------------------


def _make_player2_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    """Clone a fixture and swap provider + player steamid to PLAYER_2_ID."""
    payload = copy.deepcopy(fixture)
    if "provider" in payload:
        payload["provider"]["steamid"] = PLAYER_2_ID
    if "player" in payload:
        payload["player"]["steamid"] = PLAYER_2_ID
        payload["player"]["name"] = "TestPlayer2"
        payload["player"]["team"] = "CT"
    return payload


class TestMultiPlayer:
    async def test_per_player_state_tracking(self, fixtures: dict[str, Any]) -> None:
        """Each player's state is tracked independently."""
        gsi = GSIServer(player_ids=[PLAYER_ID, PLAYER_2_ID], port=0)
        transport = ASGITransport(app=gsi._app)
        client = AsyncClient(transport=transport, base_url="http://test")

        # Player 1 sends mid_round payload
        await post(client, fixtures["mid_round"])
        # Player 2 sends freezetime payload
        p2_payload = _make_player2_payload(fixtures["freezetime_before_round_start"])
        await post(client, p2_payload)

        assert gsi.states[PLAYER_ID] is not None
        assert gsi.states[PLAYER_ID].map is not None
        assert gsi.states[PLAYER_ID].map.round == 4

        assert gsi.states[PLAYER_2_ID] is not None
        assert gsi.states[PLAYER_2_ID].round is not None
        assert gsi.states[PLAYER_2_ID].round.phase == RoundPhase.FREEZETIME

    async def test_state_property_raises_for_multi_player(
        self, fixtures: dict[str, Any]
    ) -> None:
        """gsi.state raises RuntimeError when multiple players are configured."""
        gsi = GSIServer(player_ids=[PLAYER_ID, PLAYER_2_ID], port=0)
        with pytest.raises(RuntimeError, match="multi-player"):
            _ = gsi.state

    async def test_unknown_player_ignored(
        self, gsi: GSIServer, client: AsyncClient, fixtures: dict[str, Any]
    ) -> None:
        """Payloads from players not in player_ids are ignored."""
        unknown_payload = _make_player2_payload(fixtures["mid_round"])
        await post(client, unknown_payload)
        assert gsi.state is None

    async def test_events_fire_with_correct_player_id(
        self, fixtures: dict[str, Any]
    ) -> None:
        """Events include the correct player_id for each player."""
        gsi = GSIServer(player_ids=[PLAYER_ID, PLAYER_2_ID], port=0)
        transport = ASGITransport(app=gsi._app)
        client = AsyncClient(transport=transport, base_url="http://test")

        calls: list[tuple[str, RoundState | None, RoundState]] = []

        @gsi.on_round_start
        async def handler(
            player_id: str, old: RoundState | None, new: RoundState
        ) -> None:
            calls.append((player_id, old, new))

        # Player 1: freezetime -> live
        await post(client, fixtures["freezetime_before_round_start"])
        await post(client, fixtures["round_start"])

        # Player 2: freezetime -> live
        p2_freeze = _make_player2_payload(fixtures["freezetime_before_round_start"])
        p2_start = _make_player2_payload(fixtures["round_start"])
        await post(client, p2_freeze)
        await post(client, p2_start)

        assert len(calls) == 2
        player_ids_fired = {c[0] for c in calls}
        assert player_ids_fired == {PLAYER_ID, PLAYER_2_ID}

    async def test_player_ids_accepts_single_string(self) -> None:
        """Passing a single string should work the same as a list with one element."""
        gsi = GSIServer(player_ids="76561198000000000", port=0)
        assert gsi.player_ids == frozenset({"76561198000000000"})
        # .state should work without raising
        assert gsi.state is None

    async def test_spectating_uses_provider_steamid(
        self, fixtures: dict[str, Any]
    ) -> None:
        """Spectating filter uses provider.steamid to route to correct player."""
        gsi = GSIServer(player_ids=[PLAYER_ID, PLAYER_2_ID], port=0)
        transport = ASGITransport(app=gsi._app)
        client = AsyncClient(transport=transport, base_url="http://test")

        # First give player 1 some state
        await post(client, fixtures["mid_round"])
        assert gsi.states[PLAYER_ID] is not None
        assert gsi.states[PLAYER_ID].player is not None

        # Player 1 spectating — provider is player 1, but player block is bot
        await post(client, fixtures["spectating_teammate"])
        # State routed to player 1 (via provider), player nulled out
        assert gsi.states[PLAYER_ID] is not None
        assert gsi.states[PLAYER_ID].player is None
        # Player 2 state unaffected
        assert gsi.states[PLAYER_2_ID] is None
