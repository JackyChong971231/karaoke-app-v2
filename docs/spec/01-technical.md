# Technical spec

Status: Approved 2026-11-11. The section "Changes for 2026-11-12" was approved by the user on 2026-11-12. Built from prototype measurements. The user passed key change and word-by-word highlighting by ear and by eye on 2026-11-11.

## Stack

- **Server.** Python 3.12, managed with `uv`. Python is required because vocal separation and lyric alignment run on PyTorch.
- **Web pages.** TypeScript, served by the same server. One page is the TV player and one page is the phone remote. Assumption: React with Vite, for a polished phone UI.
- **Live updates.** One WebSocket per page. The server is the only owner of queue and playback state and pushes every change to every page.
- **Download tool.** `yt-dlp` in its own `uv tool` environment, plus the Deno JavaScript runtime that `yt-dlp` needs for YouTube.

## Architecture

The server runs these modules. Each module owns one job and talks to the others through typed calls, never through shared files.

| Module | Owns |
| --- | --- |
| `session` | The queue, the fairness order, singers, and the playback state. Saves itself on every change so a restart can offer to keep the queue. |
| `catalog` | Search across the library and YouTube, and the canonical title and artist for each song. |
| `prepare` | One job per queued song. It runs download, separation, and lyrics, in that order, and reports progress. |
| `download` | Calls `yt-dlp`. Updates `yt-dlp` at startup and retries once after an update when a download fails. |
| `separate` | Splits the audio into a backing track and a vocal track with Demucs `htdemucs`. |
| `lyrics` | Finds the lyric text, converts Chinese to Traditional, and times every word against the vocal track. |
| `library` | The song folders on disk and the search index. |
| `importer` | Copies v1 songs into the library. |

The TV player page owns audio playback. It reports its playback position to the server, and the server forwards it to the phones.

## Data model

```
Song        id (YouTube video ID), title, artist_id, duration, language, lyrics_source
Artist      id, names (every spelling, for example 陳奕迅 and Eason Chan)
Singer      id (random ID stored on the phone), name, joined_at
QueueEntry  id, song_id, singer_id, round, added_at
Session     started_at, queue (ordered QueueEntry list), sung_count per singer, now_playing
Prepared    song_id, state (queued, downloading, separating, aligning, ready, failed), progress, error
Lyrics      lines, each with words, each with text, start, end, gap_before
```

`round` is computed once, when the entry is added: the singer's songs sung this session, plus their songs already queued, plus one. A new entry goes right after the last entry whose `(round, singer join order)` is smaller.

## Song folder

```
library/
  index.sqlite
  <video id>/
    song.json          title, artist, duration, language, source URL, lyrics source
    video.mp4          at most 1080p, no audio track
    instrumental.opus
    vocals.opus
    lyrics.json        word-timed lines
```

The folder name is the YouTube video ID, so it never collides, never needs cutting, and is safe in any file system. A song is in the library only when every file exists. A preparation writes into a temporary folder and renames it into place at the end, so a crash never leaves a half-finished song.

Assumption: Opus audio at 160 kbit/s. It is about 5 MB per track instead of about 44 MB as WAV. Browsers decode Opus natively.

## Play a song on the TV

- The page loads the backing track and the vocal track into one four-channel audio buffer, so the two tracks can never drift apart.
- The buffer plays through Signalsmith Stretch (`signalsmith-stretch` 1.3.2, MIT licence) for real-time key change. A key change from a phone takes effect at once, with no reprocessing.
- The vocal slider sets the gain of the vocal channels after the key change.
- The audio is the clock. The video and the lyrics follow the audible position, which is `inputTime - (stretch latency + baseLatency + outputLatency)`. The raw `inputTime` runs ahead of the speakers. The prototype measured a 0.115 s stretch lead and 0.05 s of browser output latency, and the user had to set the lyrics 0.2 s later until the clock subtracted both.
- After a seek, the page keeps the target position itself until the stretch node reports a new time. `inputTime` updates by message, so reading it right after a seek returns the old position.
- The AV offset setting moves the video and the lyrics earlier by the TV's display lag, so picture and sound reach the room together.

Two library traps found in the prototype:

- Create the stretch node with `numberOfInputs: 1`, even though nothing connects to the input. With `numberOfInputs: 0`, the node crashes the first time it processes while paused.
- Call `setUpdateInterval` to receive playback position updates.

## Show lyrics

- Two slots. Line `i` always uses slot `i % 2`. While line `i` is sung, the other slot already shows line `i + 1`.
- Each word fills with blue from left to right over its own start and end time.
- A line too wide for one row is split at preparation time, at the word gap nearest its middle, and each half keeps its word times. As a last guard, the player shrinks the font of a line that still does not fit. A line never wraps.

## Prepare lyrics

1. Look up the lyric text on LRCLIB by title and artist. Prefer a result in the song's own script, for example Hangul over romanized Korean.
2. Convert Chinese to Traditional with OpenCC `s2hk`.
3. Split Chinese and Japanese text into single characters, keeping the original spaces as `gap_before`.
4. Time every word against the vocal track with `stable-ts` and the Whisper `small` model. Use language `zh` for Cantonese.
5. Widen each line's first word. The aligner places the first word's start too late, so its median length was 0.15 s to 0.22 s against about 0.4 s for other words, and some first words had zero length. On screen the first two words then lit up at once. When a first word is shorter than half the line's median word length, move its start earlier so it gets the median length, but never before the previous line ends. This changed 18 to 26 lines per song.
6. If LRCLIB has no lyrics, transcribe the vocal track instead and mark the song's lyrics as possibly wrong.

## Measured results

All numbers come from the prototype on the target laptop (Core Ultra 7 155H, RTX 4060 Laptop GPU with 8 GB, 15.5 GB RAM).

### Lyric timing

Line start error against LRCLIB line times, after removing one constant offset per song. LRCLIB times are made for the album audio, so they are a reference, not ground truth.

| Song | Language | Whisper `large-v3` within 0.3 s | Whisper `small` within 0.3 s | `small` median error |
| --- | --- | --- | --- | --- |
| 說謊者 | Cantonese | 61% | 89% | 0.06 s |
| 陀飛輪 | Cantonese | 50% | 89% | 0.14 s |
| 小幸運 | Mandarin | 27% | 84% | 0.06 s |
| アイドル | Japanese | 84% | 86% | 0.10 s |
| 눈,코,입 | Korean | 57% | 90% | 0.08 s |
| Complicated | English | 54% | 51% | 0.27 s |

- `small` beats `large-v3` on five songs and ties on English. Running `large-v3` with language `zh` did not close the gap, so the model, not the language code, explains it.
- The music video often has an intro that the album lacks. Offsets of +4 s to +24 s were measured. Alignment against the video's own audio removes the problem.
- English stays at about 50% against LRCLIB, but the user found its highlighting correct when watching. The LRCLIB reference is the likely weak point for that song.

### Preparation time per song

| Step | With the RTX 4060 | Processor only |
| --- | --- | --- |
| Download audio | 9 s | 9 s |
| Download video, at most 1080p | 9 s, in parallel with the audio | 9 s, in parallel with the audio |
| Separate vocals, 4 min 13 s song | 12 s, 3 runs, spread under 0.5 s | 85 s and 168 s, 2 runs |
| Align lyrics | 1.4 s to 3.4 s | 16 s to 19 s |
| **Total** | **about 25 s** | **about 2 to 3.5 minutes** |

The processor-only separation time varied by 2x between runs. The limiter is not yet identified. Power and thermal limits are the first suspects.

## Find songs and videos

The `catalog` module uses `ytmusicapi` (1.12.3 tested) against YouTube Music, region `HK`.

- **Song identity comes from song results.** A song result (`MUSIC_VIDEO_TYPE_ATV`) has a clean title and an artist with a stable channel ID. The top song result was the right song for all 7 direct searches, including searches by artist name only.
- **Artists group by channel ID.** The same ID comes back in every language, for example `UC2rCynaFhWz7MeRoqJLvcow` for both 陳奕迅 and Eason Chan. The library stores every name it sees for that ID, so either name finds the artist.
- **Fetch each result in two languages.** `zh_TW` gives native Chinese names and clean Chinese titles, but it also translates Western songs, for example "Complicated" to 超複雜 and Avril Lavigne to 艾薇兒. `en` keeps Western titles. Show the `en` title when it has no CJK characters and the `zh_TW` title does. Otherwise show the `zh_TW` title. Store both for search.
- **Filtered search breaks in `zh_TW`.** `search(filter="songs")` returns nothing with `language="zh_TW"`. Search unfiltered and filter by `resultType` instead.
- **The song-to-video link is not available.** The `counterpart` field was empty for all 10 tested songs without sign-in, so the app finds the music video by search.

### Pick the music video

Search videos for `artist + title`. Accept a result only when all three hold:

1. `videoType` is `MUSIC_VIDEO_TYPE_OMV`, the official music video.
2. The video title contains the song title before any edition tag, such as "(Live)" or "AIR (Day Version)".
3. The video's artist ID is the song's artist ID.

On the 20 songs v1 played most, this strict rule picked 9 official videos and no wrong ones. Loosening rule 3 to accept a label upload that names the singer raised that to 13, but 2 of the 13 were wrong: a parody medley and a piano cover. The strict rule stays. When it finds nothing, the phone shows the top video results with thumbnails and the singer picks one.

The importer applies the same rule to each v1 song. A found official music video replaces the v1 video, and the song is prepared again from it, which takes about 25 s per song on the RTX 4060.

Matching a messy v1 video title to a song was wrong 2 times in 20. For example, 小幸運 matched another artist's "A Little Happiness". So the importer never trusts its own match. It shows each match for the user to confirm.

## External integrations

| Integration | What breaks | How the app notices | What the user sees |
| --- | --- | --- | --- |
| YouTube through `yt-dlp` | YouTube changes its player | A download fails | The app updates `yt-dlp` and retries once. If that fails, the song shows "Can't download" on the phone. |
| LRCLIB | No lyrics for a song, or the site is down | Empty result or a network error | The song plays with transcribed lyrics, marked as possibly wrong. |
| YouTube Music search through `ytmusicapi` | YouTube Music changes its page format | A search raises an error or returns no song results for a common query | Search on the phone shows library results only, with a note that online search is unavailable. |

## Changes for 2026-11-12

These implement the product spec's sections marked "added 2026-11-12".

### Identity: phone address for fairness, browser ID for favourites

- The hub reads the phone's address from the WebSocket connection. The party's `SingerId` becomes `net:<address>`, and the laptop's own address (`127.0.0.1` or `::1`) becomes `net:laptop`. The turn rotation keys on it, so a private tab or a cleared browser on the same phone is the same singer.
- The random ID the browser stores is renamed `browserId`. It keys favourites only.
- `QueueEntry` gains `singer_name`, the name sent with the queue command. The queue shows it, so a rename does not change songs already queued. Now playing shows the playing entry's name.
- Assumption: the home router keeps a phone's address for the whole night. Phones that randomise their Wi-Fi address do so per network, not per hour, so this holds.

### Settings sync

- The server stays the only owner of the vocal level, the vocal switch, and the key.
- The key buttons send a step, "up one" or "down one", not a target key. A phone that has not yet received another phone's change then cannot move the key back. Reset still sends 0. Two phones pressing up at the same moment raise the key by two, and every screen shows the result.
- The level the switch restores moves from the phone to the server: `Settings` gains `vocal_restore`, the last level above zero. Every phone then restores the same level.
- The phone slider sends only while the singer drags, and once at the end of the drag if the value changed. It ends a drag on `pointerup`, `pointercancel`, and `lostpointercapture`, so a touch that turns into a scroll cannot leave a stale local value. While not dragging, it shows the server's value only.
- A phone sends nothing on reconnect except its hello.
- A browser test opens two phones and the TV, changes the vocal and key from each, and checks all three show the same values after every change.

### Choose the video

- `Catalog.candidates(song)` returns up to 6 video results for `artist + title`. A result passing the official-video rule is first and flagged `official`. The rule itself is unchanged.
- The phone always shows the list. "Queue" takes the first result.
- A song in the library with another video ID is a separate library song. Both copies stay.

### Browse

- **What YouTube Music offers, probed 2026-11-12 in region `HK`.**
  - Genres (`get_mood_categories`) have 日本流行音樂, K-Pop, and Pop, but 粵語 and 國語 share one genre, 華語與粵語流行樂. `get_mood_playlists` crashed on one entry. Genres are not used.
  - `get_charts("HK")` returns three video charts (Trending 20, Daily Top, Top 100 Music Videos) and the top 40 artists, mixed across regions.
  - Playlist search works with language `en` and returns nothing with `zh_TW`, like song search. Each region search returns label and chart playlists, for example warnermusichk's 最新熱門廣東歌, Sony Music Taiwan's 華語中文流行熱門歌曲合輯, and Sony Music Japan's J-pop list, mixed with fan-made lists.
- Per-country charts, probed the same day: `get_charts` returns a Top 100 Music Videos chart and the top 40 artists for `HK`, `TW`, `JP`, `KR`, and `US`. For `CN` it returns only the global chart, because YouTube is blocked in mainland China. The `TW` artists include G.E.M. and JJ Lin, so a chart says where a singer is popular, not where they are from.
- **Places.** Each place box is a page of shelves:

  Every box shows 熱門 songs only: currently popular, not classics. The user decided this on 2026-11-12.

  | Box | First shelf | Other 熱門 shelves, from playlist search |
  | --- | --- | --- |
  | 香港 | HK Top 100 Music Videos | "最新熱門廣東歌" |
  | 台灣 | TW Top 100 Music Videos | "KKBOX 華語 新歌" |
  | 中國 | none: no chart exists | "中國大陸 流行歌曲 2026", "抖音 熱歌" |
  | 日本 | JP Top 100 Music Videos | "J-Pop 2026" |
  | 韓國 | KR Top 100 Music Videos | "K-Pop 2026" |
  | 歐美 | US Top 100 Music Videos | "Pop hits 2026" |

  The year in a search is the current year, not a fixed 2026.

  Playlists by record labels and chart owners, such as KKBOX or Sony Music, are preferred over fan-made lists. Songs on a shelf go through the same song identity rules as search results, so titles and artists stay clean. Every chart and HK, TW, and mainland list mixes in singers from elsewhere. So a shelf keeps only songs whose singer belongs to that box. Assumption: a song on a shelf whose singer has no known place stays on the shelf it came from.
- A place's shelves are cached for 6 hours in memory, so opening a box is quick.
- **A singer's place.** Wikidata was tried and dropped on 2026-11-12. It lists 鄧紫棋 (G.E.M.) only as a citizen of the PRC, born in Shanghai, so she would land under 中國, the exact case the user named. Most Hong Kong singers also carry a PRC citizenship there. It also refused requests after five lookups. Instead, a short built-in list of well-known singers who appear on more than one Chinese box (for example G.E.M., 陳奕迅, 周杰倫, 薛之謙) gives their place by name. Otherwise a singer's place is the box whose shelves they appear on most, with Cantonese playlists counting double for 香港, since only Hong Kong singers sing on them. A song whose singer has a certain place (the built-in list or the user's choice) is left out of the other Chinese boxes. Playlists naming the current year are preferred, so a box shows this year's 熱門, not an old list. A singer on no shelf has no place: they still appear in search and on artist pages. The control page lets the user set any singer's place, and the user's choice always wins. Places and choices are saved in `artist-places.json` in the app data folder. Library songs take their singer's place.
- **Chart tracks.** Chart and playlist tracks are music videos with the artist's channel ID, the same ID search returns. A track is shown like a search result: its title is cleaned of the artist name and tags such as "Official Music Video", and the 《》 brackets are taken when present. Queueing it opens the same video choice, so the official video comes first.
- **Foreign songs on a chart.** Every chart mixes in other places, for example K-pop on the Hong Kong chart. The 香港, 台灣, and 中國 boxes keep only songs with Chinese characters in the title or artist. 日本 drops songs in Hangul, 韓國 drops songs in kana, and 歐美 drops songs with any Chinese, Japanese, or Korean script.
- **Singers.** Each place page ends with a grid of that place's singers, with the photo from `get_artist`. Photos are cached on disk in the app data folder.
- **Ready to sing.** Every library song, newest first.

### Favourites

- New module `favourites`, owning `favourites.json` in the app data folder beside `party.json`. It is written the same crash-safe way: write a temporary file, then rename.
- Each list stores the browser ID, the last name, the last phone address, and each song's video ID, title, and artist. Storing the full song means a favourite that is not in the library can be queued and prepared without searching again.
- New phone commands: add a favourite, remove a favourite, and queue a favourite. Queue a favourite is checked against the stored list, so a phone cannot queue an arbitrary video ID.
- Restore after a laptop address change: a phone without a stored identity asks the server for a restore offer, first by its address, then by the typed name. The server answers with the list's name and song count, never its songs. On yes, the server moves the list to the new browser ID.

## Changes for 2026-11-14: lyrics sites

These implement the product spec's "Read the lyrics from a lyrics site".

- New module `songs/lyric_sites.py`. It owns the site list (`vocab.LyricsSite`: `kkbox`, `lrclib`, `utanet`, `genius`), the order per song language, and one reader per site behind a `LyricsSites` port, so the fake world swaps in canned answers and never touches the internet.
- `GET /api/site-lyrics?song=<id>` returns the song's sites in order. `GET /api/site-lyrics?song=<id>&site=<site>` returns one site's answer: the text and the page link, a link only (KKBOX), "no lyrics", or "site down". The song must be in the library, so a phone can only ask about a song the party knows. The search uses the library's title and singer.
- Answers are kept in memory for 6 hours per song and site, so many phones opening the same song make one request. A "site down" answer is not kept.
- How each site is read, probed 2026-11-14:

  | Site | Find the song | Read the lyrics |
  | --- | --- | --- |
  | LRCLIB | `/api/search` by title and singer, the same matching as preparation | Plain lyrics, or synced lyrics with the times removed. LRCLIB has no song page, so no link. |
  | Genius | `genius.com/api/search/multi`, first song hit whose title matches | The song page's `data-lyrics-container` blocks, skipping the blocks marked `data-exclude-from-selection` (headers and ads) |
  | Uta-Net | `/search/?Keyword=<title>&Aselect=2&Bselect=3`, the row whose singer matches, else the first row whose title matches | The song page's `#kashi_area` |
  | KKBOX | `/tw/tc/search?q=<title>`. Only the top result is in the page; the rest load by script. It is used when its title and singer match. | Not read: KKBOX answers song pages with a bot check (AWS WAF challenge). The app returns the page link only. Otherwise the link is the search page for title and singer. |

- Chinese text is converted to Traditional with OpenCC `s2hk`. Credit lines such as 作詞 and 作曲 are kept, since the singer only reads the text.
- Each request has a 10 s timeout. Any network error or unexpected page shape counts as "site down" for that site.
- External integrations: a site changing its page shape shows that one site as down on the phone. The TV and preparation never depend on these sites.

## Changes for 2026-11-14: advanced lyrics matching

These implement the product spec's "Advanced lyrics matching". The current "Prepare lyrics" steps stay exactly as they are.

### Kept apart so it can be removed

- New module `songs/prepare/_advanced_lyrics.py`. It is the only code that knows about anchors, breaks, and line matching. It reads the song's LRCLIB text and vocal track, and writes `lyrics.advanced.json`.
- `lyrics.json` is still written by the current steps for every song. The advanced file sits beside it in the song folder and is optional. A song is complete without it.
- `Settings` gains `advanced_lyrics: bool`, default `false` (changed to `true` on 2026-11-15). The server owns it and syncs it like the vocal and key settings.
- The TV loads both files when a song starts. It draws from `lyrics.advanced.json` when the setting is on and the file exists, and from `lyrics.json` otherwise.
- A change to the setting mid-song swaps which file the renderer draws from on the next frame. Both files use the audio position as their clock, so playback is not touched. Assumption: the swap clears both lyric slots and redraws them for the current position, with no fade.
- The phone's now playing and the control page show the switch. It sends the new value like the vocal switch, and the server broadcasts it to every screen.
- To dump the approach: delete the module, the setting, the TV's file choice, and the break display, then delete every `lyrics.advanced.json`.

### Lyrics file

- `lyrics.advanced.json` uses the same `LyricsDoc` shape, so the TV draws it with the same renderer, plus two optional fields:
  - `breaks`: stretches of 8 s or more where nobody sings the song, each with `start`, `end`, and `kind` (`intro`, `break`, or `outro`).
  - per line, `estimated: true` when the line's time was guessed rather than matched. The TV ignores it (product decision: no mark). It is kept for measuring and debugging.
- Assumption: `LyricsDoc.version` becomes 2 for files with these fields. The TV reads version 1 and version 2.

### Steps

Run after the current steps for every song, whatever the setting, as part of the "aligning" stage. `lyrics.json` is written last, so a crash re-runs both. A song is ready when `lyrics.json` exists. If advanced matching fails or crashes, the song is still ready, without `lyrics.advanced.json`.

The current lyrics are evidence, not a competitor. Advanced matching keeps their timing wherever the audio agrees with it, and changes a line only where the evidence says it is wrong, which is mostly intros and breaks.

1. **Keep LRCLIB's line times.** The current lookup throws them away. Advanced matching keeps each synced line's start time.
2. **Listen.** Transcribe the vocal track with `stable-ts` and Whisper `small`, in the lyrics' language, with word times. Measure the vocal track's loudness every 0.1 s.
3. **Find anchors.** Compare the transcript with every LRCLIB line, after the normalising `restore_alignment` uses (NFKC, case folded, letters and digits only).
   - Chinese, Japanese, and Korean compare per character, but an English word inside them stays one unit. Letter by letter, a repeated English hook such as "anytime, anywhere" matched everywhere.
   - Chinese compares as Simplified, because Whisper writes either script and the Hong Kong forms the TV shows (説) differ from LRCLIB's Taiwan forms (說).
   - An anchor needs a run of at least 3 words, or 4 characters, in a row, and must cover at least 60% of the line. A shared opening such as 如果你能 is not enough.
   - The matched pieces must be heard within 2 s of each other. Whisper's text runs on across pauses, so without this one match was stitched from words 10 s apart.
   - Intro speech, dialogue, and crowd noise do not match lyrics, so they create no anchors. A line shorter than an anchor never anchors; it is placed by step 6.
4. **Choose which lines are sung, and where.** Pick the chain of matches, in time order, with the best total of matched units.
   - Following LRCLIB's order costs nothing. A forward skip costs 0.5 units. A repeat or a jump back costs 3 units.
   - With LRCLIB times, a change of offset (time heard minus LRCLIB's time) between neighbouring matches costs 0.5 units per second, at most 7.5. This picks the right copy of a repeated chorus, which is a minute away from the wrong one. It drops a line Whisper invented by repeating itself in an instrumental, because that jumps away and back. An inserted drama scene shifts the offset once and pays once.
5. **Keep heard lines the current lyrics already time right.** When the current lyrics start a heard line within 1.5 s of where Whisper heard it, and between its neighbours, their word times are kept. Otherwise the line gets a clip: from its first heard word to its last, widened by the song's typical singing rate for missed words, plus 1 s each side, never past its neighbouring anchors.
6. **Place the lines Whisper did not hear.** Whisper `small` skips whole soft passages, such as both verses of 如果的事. For each unheard line, in order of trust:
   1. The current lyrics' time, when it sits on voice between the neighbouring anchors and is within 3 s of LRCLIB's time shifted by the neighbours' offsets. Trusting it without LRCLIB's agreement broke 突然好想你, whose current lyrics drift mid-song too.
   2. LRCLIB's shifted time, when at least 30% of that stretch has voice. The line gets a clip there.
   3. For plain lyrics (no LRCLIB times): the current lyrics' time between two anchors, else voice right next to the anchor, through gaps of up to 4 s.

   Otherwise the line is left out: it was not sung, as for a verse a live show skipped. These lines are marked `estimated: true`.
7. **Time the words.** Clips that touch are merged. Each clip is aligned with `stable-ts` against only its own audio, and its start time is added back. A line can then never spill into an intro or a break. A clip the aligner cannot place shares its clip evenly, marked `estimated`.
8. **Check each line.** A line squeezed faster than 2.5 times the song's typical singing rate was misplaced by the aligner: it is spread at the typical rate and marked `estimated`. No word starts before the previous line ends.
9. **Find breaks.** A stretch of 8 s or more with no lyrics: `intro` before the first line, `break` between lines, `outro` after the last.
10. **Apply the current finishing steps:** widen first words and fit lines to the screen width.
11. **Fall back when matching fails.** No advanced file is written, and the song uses `lyrics.json`, when:
    - fewer than 30% of LRCLIB's lines get an anchor; or
    - more than 15% of the lines (and more than 2) are left out with no mid-song break to explain it.

    The log records the reason.

A file `lyrics.advanced.tried` in the song folder holds the matching version that last finished, whether it wrote lyrics or not. A crash writes no marker. The version is 3; raising it re-matches every library song.

### Revision: fix only the long intro (2026-11-14)

This implements the product spec's "Fix only the long intro". Steps 1 to 4 and 7 to 10 above still run, but only for the opening. The version becomes 5. When this version leaves a song alone, it deletes any `lyrics.advanced.json` an earlier version wrote, so the switch never shows the earlier version's lyrics.

1. **Strong anchors only.** A match counts as a strong anchor when it is in the chain from step 4, covers at least 80% of its line's units, and its offset from LRCLIB's time is within 2 s of the median offset of its two nearest chain neighbours on each side. Songs without LRCLIB line times get no strong anchors. Assumption: 80% and 2 s.
2. **Fall back.** No advanced file is written when fewer than 20% of the lines have a strong anchor: Whisper barely heard the song. The intro rule in steps 4 and 5 carries the confidence. 40% was tried first: it blocked the clear intro of 一場誤會, where Whisper hears Cantonese poorly elsewhere in the song. Assumption: 20%.
3. **Compare each strong anchor with the current lyrics.** It *agrees* when the current start of its line is within 2 s of where Whisper heard it, is *early* when the current start is more than 2 s before, and *late* when more than 2 s after.
4. **Find the agreement point:** the first strong anchor that agrees and whose next strong anchor also agrees. Without one, no advanced file is written.
5. **Fix only an intro.** Every strong anchor before the agreement point must be early, and there must be at least 2 of them. Otherwise no advanced file is written.
6. **Re-time the opening.** The lines before the agreement point are aligned again with `stable-ts`, as the current approach does, but against only one clip of the vocal track: from where the singing starts to the agreement point's current start. The singing starts 1 s before where Whisper heard the first early line begin, or earlier when LRCLIB's time for the first line, shifted by the early lines' offset, says so. So no line can be left out, and none can land in the intro. Steps 7 and 8 apply. The first try re-timed the opening line by line, as in step 6 above, and gave up on About Damn Time and Out of Time because Whisper had not heard every opening line.
7. **Copy the rest.** From the agreement point on, the lines are copied exactly from `lyrics.json`.
8. **Breaks:** only the intro. The re-timed opening gets the finishing steps (step 10).

Check before committing: run every library song with LRCLIB lyrics. Every advanced file has the same lyric text as its current lyrics, in the same order, and every line from the agreement point on is identical to the current lyrics. Report which songs got a fix, and check each one's first line against LRCLIB's time. The long-intro songs found by the first version (About Damn Time, Not Like Us, 突然好想你, Out of Time, Can You Feel The Love Tonight, 一場誤會) should be among them.

Measured on all 72 library songs with LRCLIB lyrics (2026-11-15). 67 songs get no advanced lyrics. 5 are fixed, all with the same lyric text as the current lyrics and every line after the opening unchanged:

| Song | First line: current, fixed, LRCLIB | Within 1 s: current, fixed |
| --- | --- | --- |
| 突然好想你 | 2.0 s, 35.4 s, 35.4 s | 67%, 80% |
| About Damn Time | 13.2 s, 57.3 s, 46.8 s | 79%, 95% |
| Can You Feel The Love Tonight | 7.0 s, 17.0 s, 17.2 s | 40%, 47% |
| Out of Time | 5.2 s, 18.4 s, 18.3 s | 63%, 83% |
| 一場誤會 | 13.6 s, 21.1 s, 21.3 s | 82%, 97% |

Not fixed on purpose: Not Like Us and Sexy, because Whisper confidently heard none of their opening lines, and 好心好報, where it confidently heard too little of the song (18%). About Damn Time's fixed first line is 10 s after LRCLIB's time; the user checks it by ear. Advanced matching took a median of 13 s per song when it had the graphics card to itself.

### Measured results (2026-11-14)

On 10 library songs chosen for being hard: the 6 the first version broke, the 3 it fixed, and the live recording. "Within 1 s" is the share of lines within 1 s of LRCLIB's times after one constant offset. That is a reference, not ground truth. "Silent" is seconds of lit words over a silent vocal track.

| Song | Current: within 1 s, silent | Advanced: within 1 s, silent | Notes |
| --- | --- | --- | --- |
| 如果的事 | 98%, 1.6 s | 98%, 1.6 s | All 40 lines. Finds the 20 s instrumental break. |
| Sugar Talking | 95%, 5.2 s | 92%, 2.8 s | Leaves out the ad-lib "(Want me)". |
| Choosin' Texas | 100%, 9.5 s | 97%, 3.8 s | |
| 潮共 | 100%, 0 s | 100%, 0 s | |
| Anytime Anywhere | 92%, 6.9 s | 98%, 6.9 s | Leaves out five backing ad-libs "(anytime, anywhere)" in the outro. |
| BANG BANG BANG | 80%, 9.2 s | 91%, 1.2 s | |
| 踊り子 | 8%, 17.8 s | 73%, 8.0 s | |
| 突然好想你 | 67%, 13.7 s, first line at 2 s | 90%, 1.5 s, first line at 35 s | The intro case. |
| 一場誤會 | 82%, 7.6 s, first line at 14 s | 97%, 0.1 s, first line at 21 s | The intro case. |
| 普渡眾生 (live) | 100%, 20.1 s | 100%, 12.7 s | Finds an 8 s break. |

No first line got worse. Advanced matching took a median of 13 s per song with the RTX 4060 (8 to 61 s), on top of today's preparation.

Over all 75 library songs, the first version fixed the first line of 5 songs and broke 5, and left out 3 or more lines on 15. That run found the causes fixed above: soft passages Whisper does not hear, choosing the wrong copy of a chorus, stitched and partial matches, invented repeats, and English hooks inside Japanese lyrics.

### Songs already in the library

- On start, a background job runs advanced matching for every library song with LRCLIB lyrics whose `lyrics.advanced.tried` is missing or older than the current matching version. It runs whatever the setting.
- It looks the lyrics up on LRCLIB again for the line times, then holds the accelerator one song at a time, at a lower priority than any queued or imported song.
- The vocal WAV is deleted when a song is installed, so the job decodes `vocals.opus` to a temporary WAV and deletes it afterwards.
- The media route serves lyrics files with `Cache-Control: no-cache`, since the job adds them after install. Audio and video stay cached for a year.

### TV: breaks

- During a break, both lyric slots are empty and the lyrics area shows "♪ intro" or "♪ break" with the seconds left until the next line.
- The next line's slot fills 3 s before it starts, then playback continues as in "Show lyrics".
- Outros show nothing.

### Measuring

- `server/tests/lyrics_eval/run_eval.py` runs both approaches on library songs, writing nothing into the library. Per song, it prints the share of lines within 1 s of LRCLIB's times after one constant offset, when the first line lights up, and the seconds of lit words over a silent vocal track.
- Hand-marked times for the user's own problem videos can be added once the user names them (open question in the product spec).
- Unit tests feed made-up transcripts to steps 3 to 11: intro speech, an unheard first line after a talking intro, a repeated chorus with a skipped verse, mid-song dialogue, a crowd-sung line, unsung lines with no voice, too few anchors, Chinese in mixed scripts, and each failure found on 如果的事 (an unheard opening verse, the wrong chorus copy, an invented repeat, a shared opening, a stitched match, too many lines left out).
- A browser test switches the setting mid-song on the fake world and checks that the TV swaps lyrics at the same position and counts down the intro.

## Changes for 2026-11-15: move around in the song

- One phone command, `seek {playId, toS}`, does all three: restart sends 0, the 5 s button sends the shown position plus 5, and the progress bar sends where the finger lifts. It is a target, not a step, so a TV that sees only the latest of several quick seeks still lands in the right place.
- The party keeps the latest seek on `Playing` as `(seq, to_s)`. `seq` increases with every seek, so seeking twice to the same place still jumps twice. A seek never changes the queue, fairness, or `play_id`. The reducer clamps `to_s` to between 0 and 1 s before the song's end.
- The TV applies a seek whose `seq` it has not applied yet for this play. It moves the stretch node's input time, holds the target in its clock (see "Play a song on the TV"), and the video and lyrics follow the audio as usual. A TV that loads or reloads mid-song counts the seek it finds as already applied and starts from `resume_at_s`.
- The phone shows the target position at once, before the TV's next clock report, so the bar does not jump back and a second quick tap on the 5 s button adds 5 s to the first. The target is dropped when a clock report lands near it, or after 2 s.
- The progress bar is a range input. While the finger is on it, the bar follows the finger and shows the time under it. Lifting sends one seek.
- Search: pressing the Search tab remounts the search panel, which clears the query and the page stack.
- `Settings.advanced_lyrics` now defaults to `true`. A saved `party.json` keeps its saved value.

## Changes for 2026-11-17: Windows installer

A small installer carries the tools and the app. `uv` builds the Python environment on the friend's laptop on first start. This keeps the installer far under GitHub's 2 GB limit per release file, and `uv.lock` still pins every version.

### What the installer contains

About 150 MB, built with Inno Setup into `Karaoke-Setup-<version>.exe`, and installed per user in `%LOCALAPPDATA%\Programs\Karaoke`, so it needs no administrator rights.

| Part | Why |
| --- | --- |
| `uv.exe` | Installs the locked packages, and keeps `yt-dlp` updated as today. |
| `python\` (CPython 3.12.16) | The app's Python. Bundled since 2.0.1: `uv python install` makes a folder link that some laptops refuse ("untrusted mount point", os error 448), so the launcher sets `UV_PYTHON` to this copy and `UV_PYTHON_DOWNLOADS=never`. |
| `ffmpeg.exe`, `ffprobe.exe` | Called by preparation and thumbnails. They are on the user's laptop today but not on a friend's. |
| `deno.exe` | Needed by `yt-dlp` for YouTube. |
| `server/` source with `pyproject.toml` and `uv.lock` | The app. |
| `web/dist` | The built pages, so the friend needs no Node. |
| `Karaoke.cmd` | The launcher. |

### First start

1. The launcher puts the installed tools first on `PATH`, points uv at the bundled Python, and sets `UV_PROJECT_ENVIRONMENT` under `%LOCALAPPDATA%\Karaoke\runtime`, so nothing lands in the install folder or a cloud-synced folder.
2. It checks for an NVIDIA card with `nvidia-smi -L`. If one is found, it runs `uv sync --frozen --no-default-groups --group cu128`, otherwise `--group cpu`. `pyproject.toml` has two conflicting dependency groups that take `torch` and `torchaudio` 2.11.0 from the CUDA 12.8 index or the CPU index. `cu128` is a default group, so the developer's `uv run` on the user's laptop is unchanged. Setting `KARAOKE_TORCH=cpu` forces the CPU build, for testing.
3. It runs `uv tool install "yt-dlp[default]"` if `yt-dlp` is missing, with the tool folders under `runtime` too.
4. It starts `karaoke serve --installed` from the environment directly, so no tool in the install folder is running while the app runs. The Whisper and Demucs models download on first use, as they do today.

Later starts skip steps 2 and 3 when the environment matches the lock, which `uv sync` checks in about a second.

Assumption: the friend's laptop has Microsoft Edge, which every Windows 10 and 11 laptop has. Without Edge the app already prints the two addresses to open by hand.

### Release

- A GitHub Actions workflow on `windows-latest`, started by pushing a tag such as `v2.1.0`: build `web/dist`, download pinned versions of `uv`, `ffmpeg`, and `deno`, run Inno Setup, and attach the installer to a GitHub Release for that tag.
- `Start Karaoke.cmd` stays for the user's own development copy.
- The version lives in one place, `version` in `server/pyproject.toml`. The workflow fails when the tag does not match it, so a release can never report the wrong version.
- To release: bump `version`, commit, `git tag v2.1.0`, `git push --follow-tags`.

### Upgrade

- A new `updates` module in `shell` owns the check. The installed launcher passes `--installed`, and only then is the module on. It reads `GET https://api.github.com/repos/<owner>/karaoke-app-v2/releases/latest` with no login, once at start. That is far under GitHub's limit of 60 requests an hour without a login. The request carries only a generic `User-Agent`. Drafts and pre-releases are skipped, because `releases/latest` never returns them.
- It compares the release tag with the running version as version numbers, not as text. A newer release with an asset named `Karaoke-Setup-<version>.exe` is offered by `GET /api/update` (`contract.UpdateResponse`). Only the control page asks for it and shows the bar.
- `POST /api/update/upgrade` answers only the laptop running the app. The server downloads the asset to `%LOCALAPPDATA%\Karaoke\updates`, checks its size against the release's asset size, writes the installer's path and version to `pending.txt`, and exits with code 75. Exiting closes the TV and control windows as today. The party is already saved on every change.
- The app cannot start the install itself: everything it starts is killed with it (see `shell/lifetime.py`). `Karaoke.cmd` is outside that, so on exit code 75 it starts `upgrade.ps1` from a copy in `%TEMP%` and closes. That step waits for the old app to let go of the install folder, runs the installer with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL`, then runs `Karaoke.cmd` again.
- The installer is per user, so the silent install needs no administrator prompt. Inno Setup replaces the install folder and keeps `%LOCALAPPDATA%\Karaoke`. On the next start, `uv sync --frozen` installs only the packages whose locked versions changed. Uninstalling removes `runtime` and `updates` but keeps songs, settings, and favourites.
- When the installer exits with an error, the PowerShell step still starts `Karaoke.cmd`, with `--upgrade-failed <version>` so the control page can say so.
- Assumption: the installer is not signed, so the app trusts it by downloading only from the repository's own release over HTTPS. Signing is a separate decision if friends outside the user's circle install it.

### Proof of the upgrade

- Publish `v2.0.1` and `v2.0.2` as test releases. Install `v2.0.1` in Windows Sandbox, see the bar, press Upgrade, and see the app come back as `2.0.2` with the library and settings kept.
- A unit test covers the version comparison, including `2.10.0` being newer than `2.9.0`.

### Proof

- A clean Windows VM or Windows Sandbox with no Python, uv, Node, or ffmpeg installs from the release file, starts the app, and prepares one song on the CPU path.
- The user's laptop installs the same file and prepares one song on the CUDA path.

## Verification

- Unit tests cover the fairness order, including every example in the product spec, and a random-input test that no singer is ever queued back to back while another waits.
- A server test runs a 5-phone party over WebSockets (simultaneous adds, ready and preparing songs, a late joiner, a rename, a second browser, a remove, a move, songs ending) and checks the queue after every step.
- Unit tests show that a rename or a second browser ID from the same phone address stays one singer.
- A project verification skill, made with `/pstack:create-verification-skill`, drives the TV page and a phone page in a real browser with Playwright. The prototype proved this works on the laptop with Microsoft Edge.

## Open questions

- **Advanced lyrics matching (2026-11-14):** the thresholds were tuned on 10 library songs ("Measured results (2026-11-14)"), not on the user's own problem videos. Whisper `small` is kept: it took a median of 13 s per song, and the passages it misses are now placed from LRCLIB's times and the current lyrics instead. Backing ad-libs in parentheses that Whisper does not hear can be left out; whether that is acceptable is for the user to judge in use.
- **Fix only the long intro (2026-11-14):** A Whole New World's current lyrics stop at 2:15, and the first advanced version covered the rest of the song. The intro-only fix gives that up, along with live shows' repeated choruses and mid-song drama scenes. If those matter later, they are a separate decision.
