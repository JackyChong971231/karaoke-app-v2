# Product spec

Status: Approved 2026-11-11. Amended the same day with the user's music video decisions, and again with the control page, start-up windows, TV full-screen button, filler rotation, and vocal switch. Amended 2026-11-12 with video choice, settings sync, browse, fairness by phone, and favourites, approved by the user the same day.

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

### One phone is one singer, whatever the name (added 2026-11-12)

The user's words: a 咪霸 might keep changing their name when adding songs, so their songs queue back to back. Order the queue by the machine, not the typed name. The screens still show the typed names.

- Fairness counts songs per phone. Changing the name does not make a new singer.
- Assumption: a phone is recognised by its address on the home Wi-Fi, not only by the ID the browser stores. Clearing the browser, opening a private tab, or switching to another browser on the same phone is still the same singer. A browser cannot read a true hardware ID, so the network address is the closest the app can get.
- Assumption: the laptop control page counts as one singer, like one phone.
- Assumption: each queued song shows the name the singer had when they queued it. A later rename does not change songs already in the queue.
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

### Keep settings in sync (added 2026-11-12)

The user saw the vocal setting differ between phones, and the app sometimes followed one phone at random.

- Every phone, the control page, and the TV always show the same vocal level, vocal switch, and key.
- The latest change wins, from whichever phone made it. Every other screen updates to it within a second.
- A phone never sends a setting the singer did not just change. Ending a slider drag, a cancelled touch, or a reconnect must not resend an old value.
- Two phones changing the key at the same moment end on one agreed key, shown everywhere.

### See the queue

- Each entry shows the song title, the artist, the singer who queued it, and whether the song is ready.
- Any singer can reorder the queue, remove any song, or move a song to play next.

### Find and queue songs

- One search box finds songs in the local library and online.
- Each result shows the song title and the artist.
- Singers can browse and search by artist.
- Library songs are marked as ready to play.
- After a singer picks an online song, the app finds its official music video. If it finds none, the phone shows the top video results with thumbnails, and the singer taps one.

### Choose the video (added 2026-11-12)

The user's words: sometimes the video is not the official music video, so let singers choose which YouTube video they want.

- After a singer picks an online song, the phone always shows a short list of videos with thumbnails, title, channel, and length. The app's best guess is first and marked, for example "Official MV".
- One tap on "Queue" takes the best guess, so the common case stays fast. Tapping another video queues that one instead.
- Assumption: the list shows up to 6 videos.
- Assumption: a library song that already has a video can also be queued with a different video. The other video is prepared as its own copy and the first copy stays.

### Browse for songs (added 2026-11-12)

The user's words: more ways to find songs than the search box, like a karaoke app, with boxes such as 歐美, 粵語, and 日語.

The search screen opens on a browse page with these ways in:

- **Search box.** As today.
- **By region.** One box per place: 香港, 台灣, 中國, 日本, 韓國, 歐美. The user asked for 香港, 中國, and 台灣 to be listed separately. Every box shows the 熱門 (currently popular) songs of that place, then the library songs whose singer is from that place, marked ready.
- A singer's place is where the singer is from, not the language of the song. For example, 鄧紫棋 (G.E.M.) is under 香港 even when she sings in Mandarin.
- Assumption: the app guesses each singer's place, and the laptop control page lets the user correct a wrong one. The correction is kept.
- **By singer.** A grid of singers with photos, grouped by region. Tapping a singer shows their songs.
- **My favourites.** See below.
- Assumption: also a **Ready to sing** box listing every library song, newest first, since those start at once.

### Favourite songs (added 2026-11-12)

- Any singer can mark a song as a favourite from search results, the queue, or now playing, with one tap on a heart.
- Each phone has its own favourites list. Queueing a song from the list takes one tap.
- The lists are saved on the laptop, not on the phone, so they survive a cleared browser and are easy to back up.
- A favourite song that is not yet in the library is prepared when it is queued, like any online song.
- The list belongs to the phone's browser. The user's words: the list must not be lost if the laptop's IP address changes.
- A browser keeps its saved data per web address. When the laptop's IP address changes, the QR code points at a new address and the phone's browser starts empty, as if it were a new phone. The app then offers the singer their old list:
  - If the phone's Wi-Fi address matches the one a saved list was last used from, the phone asks "Welcome back, Amy. Keep your 12 favourites?" before asking for a name.
  - Otherwise, after the singer types a name that matches a saved list, the phone asks the same question.
  - Nothing is restored unless the singer taps yes. A restored list is then this browser's list.

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

Example from the user, 2026-11-12, to be proven by a test. A has 2 songs queued: A, A. B queues a song, and it goes after A's first song: A, B, A. A queues another, and it goes to the back: A, B, A, A. C queues a song, and it goes after B: A, B, C, A, A.

- Added 2026-11-12: the user reported that 防咪霸 does not always work. The fairness rule above is unchanged. The fix is to prove it with the user's example and to count by phone, not by name (see "One phone is one singer").

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

None. Decided 2026-11-12: favourites follow the browser, with the restore offer above. Region boxes use YouTube Music's charts and playlists. Two friends sharing one phone count as one singer.
