"""The party core: one pure reducer and its projections.

Public surface. Everything else in this package is private: import-linter forbids importing
karaoke.party.fairness, .reduce, or .projections from outside the package.

    initial_state(saved) -> PartyState
    reduce(state, input) -> Step(state, outcome)
    durable(state)            -> DurableSnapshot        # shell persists it
    preparation_demand(state) -> tuple[SongMeta, ...]   # shell hands it to the Preparer
    filler_request(state)     -> FillerRequest | None   # shell answers with FillerPicked
"""

from karaoke.party.inputs import (
    Before, End, FillerPicked, Front, Hello, Input, MoveEntry, PhoneCommand, Position, QueueSong,
    RemoveEntry, Rename, ResolveRestart, SetAvOffset, SetKey, SetPaused, SetVocal, Skip, SongReady,
    TrackEnded, TrackFailed, TvPresence,
)
from karaoke.party.model import (
    Accepted, AwaitingRestartChoice, DurableSnapshot, EntryId, Filler, FromQueue, Idle, Outcome,
    PartyState, PlayId, Playing, QueueEntry, Rejected, Running, SavedEntry, Settings, Step,
)
from karaoke.party.projections import FillerRequest, durable, filler_request, preparation_demand
from karaoke.party.reduce import initial_state, reduce
