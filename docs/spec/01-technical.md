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

- The hub reads the phone's address from the WebSocket connection. The party's `SingerId` becomes `net:<address>`, and the laptop's own address (`127.0.0.1` or `::1`) becomes `net:laptop`. Fairness, join order, and "sung tonight" all key on it, so a private tab or a cleared browser on the same phone is the same singer.
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

## Verification

- Unit tests cover the fairness order, including both examples in the product spec and the user's 2026-11-12 example.
- Unit tests show that a rename or a second browser ID from the same phone address stays one singer.
- A project verification skill, made with `/pstack:create-verification-skill`, drives the TV page and a phone page in a real browser with Playwright. The prototype proved this works on the laptop with Microsoft Edge.

## Open questions

None.
