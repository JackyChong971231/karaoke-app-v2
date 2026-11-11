"""Spec examples as tests on the pure reducer. No server, no browser, no mocks: inputs in, state out.

Sketch: the helpers raise until implemented. The cases ARE the spec (00-product.md "Queue fairness",
"Restart the app", "Fill an empty queue", "Song preparation").
"""

from __future__ import annotations

from karaoke.party import PartyState


def party() -> PartyState:
    """initial_state(None) with singers A, B, C, D said Hello, TV connected."""
    raise NotImplementedError


def queue_as(state: PartyState, *singers_in_order: str) -> PartyState:
    """Each letter queues a fresh not-yet-ready song (so nothing starts playing and the queue is observable)."""
    raise NotImplementedError


def order(state: PartyState) -> str:
    """Queue as singer letters, e.g. 'ABCABBB'."""
    raise NotImplementedError


def test_fairness_example_from_user() -> None:
    s = queue_as(party(), *"ABBBBAC")
    assert order(s) == "ABCABBB"
    s = queue_as(s, "C")
    assert order(s) == "ABCABCBB"


def test_fairness_history_example() -> None:
    """A has sung 3 tonight; D joins. D's round 1 goes before A's round 4."""
    raise NotImplementedError


def test_manual_move_is_kept_and_new_songs_are_still_placed_fairly() -> None:
    raise NotImplementedError


def test_unready_song_keeps_front_place_while_next_ready_song_plays() -> None:
    raise NotImplementedError


def test_double_skip_with_same_play_id_skips_one_song() -> None:
    raise NotImplementedError


def test_filler_plays_when_idle_and_is_not_interrupted_by_a_ready_song() -> None:
    raise NotImplementedError


def test_stale_filler_pick_is_dropped() -> None:
    raise NotImplementedError


def test_restart_keep_keeps_order_and_resets_fairness() -> None:
    """Saved A B B; keep -> same order, rounds renumbered 1,1,2; a new C song goes after B1 (round 1, joined 3rd)."""
    raise NotImplementedError


def test_restart_first_answer_wins() -> None:
    raise NotImplementedError


def test_durable_snapshot_has_no_fairness() -> None:
    raise NotImplementedError


def test_any_input_sequence_keeps_invariants() -> None:
    """Hypothesis: random sequences of all Input kinds. After each step:
    entry ids unique; now-playing entry not in queue; every queued singer in join_order;
    reduce(state, same Skip twice) changes state at most once; rejected inputs leave state identical."""
    raise NotImplementedError
