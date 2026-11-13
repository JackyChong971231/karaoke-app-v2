"""Closed vocabularies. Each list exists exactly once, here.

Leaf module (stdlib only). The party core, the song side, and the wire contract all import from it.
The wire schema exports each as a JSON Schema enum, so TypeScript gets the same union, and any
`Record<Vocab, ...>` table on a page fails to compile when a member is added here.
"""

from typing import Literal

RejectReason = Literal[
    "awaiting_restart_choice",
    "already_resolved",
    "stale_play",
    "unknown_entry",
    "nothing_playing",
    "invalid_value",
    "unknown_singer",
    "pick_expired",
]
"""Why the party (or the boundary) refused a command. 'pick_expired' comes from shell.parse, the rest from reduce."""

PrepStage = Literal["waiting", "downloading", "separating", "aligning", "ready", "failed"]

FailReason = Literal["cant_download", "video_unavailable", "processing_crashed", "disk_full"]

LyricsSource = Literal["lrclib", "transcribed"]
"""'transcribed' means possibly wrong; the TV and the phone show a badge."""

ImportDecision = Literal["proposed", "confirmed", "corrected", "skipped"]
"""The user's decision per v1 song. 'Imported' and 'failed' are NOT decisions: they are derived from the
library and the preparation board when the review page is rendered."""

MediaFile = Literal["video.mp4", "instrumental.opus", "vocals.opus", "lyrics.json"]

PlaceId = Literal["hk", "tw", "cn", "jp", "kr", "west"]
"""The browse boxes, by where a singer is from (spec "Browse for songs"): 香港 台灣 中國 日本 韓國 歐美."""
