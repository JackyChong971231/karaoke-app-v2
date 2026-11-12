# Product spec

Status: Approved 2026-11-11. Amended the same day with the user's music video decisions, and again with the control page, start-up windows, TV full-screen button, filler rotation, and vocal switch.

## Goal

A home karaoke system for a party on the user's own Wi-Fi. Guests scan a QR code on the TV, queue songs from their phones, and sing along to the music video with word-by-word lyrics. The app prepares each song (music video, backing track, vocal track, and timed lyrics) and keeps it, so a repeat song starts at once.

## Setup

The laptop runs the app and is the only player.

```
Laptop --HDMI------------------> TV          (video and lyrics, no sound)
Laptop --USB audio interface---> Mixer <---- wireless microphones
                                 Mixer ----> Onkyo receiver ----> 5.1 speakers
```

- The microphones never pass through the laptop, so singers hear themselves with no delay.
- The TV shows the picture later than the audio reaches the speakers. The app has an AV offset setting that delays the audio to match. The user sets it once per TV.
- The app runs on any Windows laptop. It uses an NVIDIA GPU when one is present and falls back to the CPU. Preparation is slower without a GPU, and nothing else changes.

## Users and surfaces

- **Singer.** One phone is one singer. On first visit the phone asks for a name and remembers it. The singer can change the name later.
- **TV player.** A full-screen page on the laptop, shown on the TV. It plays the song, shows the lyrics, and shows the QR code.
- **Phone remote.** A web page opened by scanning the QR code. Anyone on the Wi-Fi who scans it can control the app. There is no PIN.
- **Control page.** A page on the laptop's own screen, used with the mouse. It has the same controls as the phone remote. The laptop drives the TV as an extended screen, so the control page shows only on the laptop and the TV page shows only on the TV. It shows now playing, the queue, and search side by side. Assumption: the control page asks for a name once, like a phone, and counts as one more singer.

### Start the app

- On start, the app opens the TV page full screen on the second screen and the control page on the main screen.
- Assumption: with only one screen, both pages open as ordinary windows, so the laptop is never trapped behind a full-screen TV page. The TV page's full-screen button enlarges it.

Every singer has the same powers. There is no host role.

## Phone remote

The remote must look and feel like a finished product, not a DIY tool.

### Control playback

- Pause and resume.
- Skip to the next song.
- Set the original vocal volume with a slider, from off to full.
- Turn the original vocal off or on with one switch beside the slider. Turning it on restores the level it had. Assumption: if it was never on, it turns on at full.
- Change the key up or down in semitones.

### See the queue

- Each entry shows the song title, the artist, the singer who queued it, and whether the song is ready.
- Any singer can reorder the queue, remove any song, or move a song to play next.

### Find and queue songs

- One search box finds songs in the local library and online.
- Each result shows the song title and the artist.
- Singers can browse and search by artist.
- Library songs are marked as ready to play.
- After a singer picks an online song, the app finds its official music video. If it finds none, the phone shows the top video results with thumbnails, and the singer taps one.

## TV player

### Show lyrics the karaoke way

- Two lyric lines are on screen. The first line sits at the left. The second line sits lower, at the right.
- While one line is sung, the other line already shows the next lyric. When a line finishes, it is replaced by the lyric after the next one.
- Each word lights up in blue as it is sung. For Chinese and Japanese, each character is one word.
- A line never overflows the lyrics area or overlaps the other line, however long it is.
- Chinese lyrics always show in Traditional script.

### Enlarge the picture

- A full-screen button sits at the bottom left, like YouTube. It shows when the mouse moves and hides when the mouse rests. Assumption: double-click and the F key also toggle full screen, and the button hides when the window already fills the screen.

### Show the vocal and key settings

- While a song plays, the TV always shows the guide vocal level and the key. Assumption: two chips at the top right, above the QR code, reading for example "Vocal 35%" or "Vocal Off", and "Key +1" or "Key Original". A chip pulses when its value changes, and a changed key is highlighted.

### Show the queue state

- The QR code stays visible so new guests can join.
- The next song and its singer are shown.

### Fill an empty queue

When the queue is empty, the TV plays random library songs with video, sound, and lyrics, so anyone can join in and sing at any time.

- Filler songs are picked at random from the entire library. A song does not come back until 20 other fillers have played, or until every library song has played since it did. The same song never plays twice in a row while the library has two or more songs.
- If a filler song fails to play, the TV shows that for 3 seconds before moving on, so a broken song cannot flash past in a loop.
- A filler song plays like a queued song. Singers can pause it, skip it, set the vocal volume, and change the key.
- A filler song is not in the queue, has no singer, and does not count toward fairness.
- Assumption: when someone queues a song during a filler song, the filler song plays to its end and the queued song follows. Any singer can skip the filler song to start the queued song at once.

## Song preparation

- Preparation starts the moment a song is queued, not when its turn comes.
- Preparation gets the music video, separates the backing track from the vocals, and produces lyrics with a time for every word.
- A prepared song is saved on the laptop. Next time it is queued, it is ready at once.
- If a song is not ready when its turn comes, the next ready song plays. The unready song keeps its place at the front.
- When the online song source changes and downloads break, the app updates its download tool and retries without the user doing anything.
- Every library song has a proper title and artist, not the video title or channel name. The same artist is grouped as one, whatever language the name is written in.

## Queue fairness

The queue takes turns between singers, so no singer can hold the microphone by queueing fast.

- "Tonight" means since the app last started. A restart resets every singer's count and the join order.
- Each song gets a round number. A singer's first song tonight is round 1, their second is round 2, and so on. Songs already sung tonight count.
- Within a round, singers go in the order they first joined tonight.
- A new song is inserted at its fair position. Songs already in the queue keep their order.
- A manual reorder by any singer stays in place. Fairness applies only to where new songs go in.

Example from the user. Songs are queued in the order A, B, B, B, B, A, C. The queue becomes A, B, C, A, B, B, B. When C queues a second song, the queue becomes A, B, C, A, B, C, B, B.

Example with history. A has sung 3 songs tonight and D joins. D's first song is round 1 and A's next song is round 4, so D sings first.

### Restart the app

- On start, if the last session left songs in the queue, the app asks whether to keep that queue or start a new one.
- Assumption: the question shows on the TV and on every connected phone. The first answer wins.
- A kept queue keeps its order. Counts and join order still reset, so new songs are placed as if the night had just started.

## Song library

- The library lives on a local disk folder that the user chooses, not in a cloud-synced folder.

### Import the v1 library

- An import tool copies prepared songs from v1 as files only. It redoes the title, the artist, and the lyrics.
- If the app finds an official music video for the song, the import replaces the v1 video with it, for example a lyric video with its own subtitles, and prepares the song again from the new video. Otherwise it reuses the v1 video and separated audio.
- Before importing, the tool shows each v1 song with its matched title, artist, and video. The user confirms or corrects each match.
- The first import takes 20 songs. Assumption: the 20 songs v1 queued most often, read from the play counts in v1's saved state.
- The user tries v2 and then asks for the rest, about 468 songs, in a second run.
- Running the import again skips songs already in the library, so a run that stops halfway can be restarted safely.
- After the full import, the user deletes the v1 library so songs are not stored twice. The import tool never deletes v1 files.

## Lessons from v1

v2 designs out these failures:

- **Slow downloads.** The TV waited for the next song. v2 prepares on queue and downloads at a size fit for a TV.
- **Unready songs after skips.** v2 prepares every queued song, not only the next one.
- **Broken YouTube downloads.** v2 updates and retries the download tool on its own.
- **Wrong lyrics.** Speech recognition guessed the words, so singers chose lyric videos over music videos. v2 looks up the real lyrics and times them against the vocals.
- **Line-level sync only.** v2 times every word.
- **Wrong artist names.** v1 stored the YouTube channel name as the artist.
- **Amateur interface.** v2 aims for the polish of a commercial karaoke app.
- **Tangled code.** v1 mixed the UI, playback, downloads, and processing, so fixes caused new bugs.

## Out of scope

- Microphone input, scoring, and recording. The mixer handles the microphones.
- Access from outside the home Wi-Fi.

## Unreliable lyrics

- If no lyrics text exists for a song, the app transcribes the vocals and plays the song with those lyrics.
- The TV and the phone mark those lyrics as possibly wrong.

## Open questions

None.
