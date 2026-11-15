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
- Songs picked on the laptop that runs the app show the singer as "System" on every screen, not the name typed there (added 2026-11-12, clarified the same day). The user's words: only the song picked from the laptop running the app will be System. When other users join with a laptop, they name themselves and the app shows that name. A guest's laptop counts as one singer, like a phone. Assumption: this covers the phone queue, now playing, the TV, and the restart offer. The control page still marks them as its own, so there they read "System (you)".
- Assumption: each queued song shows the name the singer had when they queued it. A later rename does not change songs already in the queue.
- **TV player.** A full-screen page on the laptop, shown on the TV. It plays the song, shows the lyrics, and shows the QR code.
- **Phone remote.** A web page opened by scanning the QR code. Anyone on the Wi-Fi who scans it can control the app. There is no PIN.
- **Control page.** A page on the laptop's own screen, used with the mouse. It has the same controls as the phone remote. The laptop drives the TV as an extended screen, so the control page shows only on the laptop and the TV page shows only on the TV. It shows now playing, the queue, and search side by side. It counts as one more singer, shown as "System". It never asks for a name, and its settings have no name field (changed 2026-11-12: the user asked why the app still asked for their name when started with the .cmd). Any page opened on the laptop running the app behaves the same way. A guest's own laptop is asked for a name, like a phone.

### Start the app

- On start, the app opens the TV page full screen on the second screen and the control page on the main screen.
- Assumption: with only one screen, both pages open as ordinary windows, so the laptop is never trapped behind a full-screen TV page. The TV page's full-screen button enlarges it.
- Closing the app's terminal window closes the TV page and the control page too (added 2026-11-12). The user's words: when I close the terminal, also close the karaoke control UI and the TV page. Assumption: this applies however the app stops, including Ctrl+C or a crash. Song preparation still running in the background stops with it. Pages opened by hand in another browser, and phones, stay open and show that the app is offline.

Every singer has the same powers. There is no host role.

## Phone remote

The remote must look and feel like a finished product, not a DIY tool.

### Control playback

- Pause and resume.
- Skip to the next song.
- Set the original vocal volume with a slider, from off to full.
- Turn the original vocal off or on with one switch beside the slider. Turning it on restores the level it had. Assumption: if it was never on, it turns on at full.
- Change the key up or down in semitones.

### Move around in the song (added 2026-11-15)

- Sing the song again from the start, in the middle of the song. The user's words: add a button to allow resing in the middle of the song, this should not affect the queue. The song keeps its place as the song playing now: the queue, the singer's count for tonight, and the key stay as they are.
- Jump 5 s forward with one tap. Each tap jumps 5 s more.
- Drag the progress bar to any point in the song, like a normal video player. The video, the audio, and the lyrics all jump there.
- Assumption: these work on filler songs too, and every phone and the control page sees the new position.
- Assumption: a paused song stays paused after a jump or a restart, and plays from the new place when resumed.
- Assumption: jumping forward past the end of the song stops 1 s before the end, so the song still ends normally.
- Assumption: the restart button and the 5 s button sit in the row with the pause button, so now playing still fits on one screen. Restart sits left of pause and the 5 s button right of it.

### Now playing fits on one screen (added 2026-11-12)

The user's words: make it easier to see and navigate, and fit everything on the now playing page into one screen. The singer should not need to scroll down to see the key change or the up next list.

- On a phone, the now playing page shows the song, progress, pause and skip, guide vocal, key, and up next without scrolling.
- Up next is collapsed by default. Collapsed, it still shows the next song and how many more are waiting. Assumption: the collapsed row shows the first song in the queue.
- Opening up next shows the next few songs, and a "Load more" button shows more with each tap. Assumption: it opens to 3 songs, and each tap adds 5.
- The song title takes one line. The user's words: when the song name is too long, it scrolls horizontally back and forth and only occupies one line, instead of multiple lines, to save space. Assumption: it pauses at each end, and it stays still for people who turned on reduced motion on their phone, showing "…" instead.
- Assumption: "one screen" means a common phone size (about 375 by 667 points, iPhone SE, and larger) with the browser's toolbars showing. Opening up next or loading more may make the page scroll.
- The playing song's picture is big. The user's words: I still prefer a bigger image for the song that is playing. Assumption: it is a wide picture across the page, as tall as the phone allows while everything above still fits one screen. On a phone too short for that (iPhone SE size), it stays a small square beside the title.

### Song pictures (added 2026-11-12)

- A song that is already downloaded shows the picture of its video, not the first letter of its title. The user's words: for songs that are already downloaded, show the thumbnail of the video instead of the first-letter logo.
- Assumption: the laptop keeps each downloaded song's picture beside its files and phones load it from the laptop, so pictures show without YouTube at party time. The laptop takes YouTube's best-quality picture for the video, once. If YouTube cannot be reached, it uses a frame from the downloaded video.
- A song that is not downloaded yet shows YouTube's picture. The first letter shows only when no picture can be found.

### Keep settings in sync (added 2026-11-12)

The user saw the vocal setting differ between phones, and the app sometimes followed one phone at random.

- Every phone, the control page, and the TV always show the same vocal level, vocal switch, and key.
- The latest change wins, from whichever phone made it. Every other screen updates to it within a second.
- A phone never sends a setting the singer did not just change. Ending a slider drag, a cancelled touch, or a reconnect must not resend an old value.
- Two phones changing the key at the same moment end on one agreed key, shown everywhere.

### Search button goes home (added 2026-11-15)

- Pressing Search in the bottom navigation always opens the search home page: an empty search box with the browse boxes. It clears any typed search and leaves any singer, region, or "Ready to sing" page.
- Assumption: this happens whether Search was already the open tab or another tab was.

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

### Show full song titles (added 2026-11-12)

- The TV never clips a song title. Letters that hang below the line, like g, p, and y, show in full.

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
- On the phone and the control page, the singer can tap the "Lyrics may be wrong" mark to learn why (added 2026-11-12). Assumption: a short panel explains that no published lyrics were found for the song, so the app wrote down the words it heard in the recording, and that it can mishear words, like automatic captions. The timing still follows the singing.

## Read the lyrics from a lyrics site (added 2026-11-14)

The user's words: allow users to show lyrics from a website directly on their devices if the lyrics are wrong or if the ordering is wrong. Allow multiple lyrics sites. For Chinese songs, get lyrics from KKBOX.

- When the TV shows wrong words, or lines in the wrong order, a singer can read the song's lyrics from a lyrics website on their own phone.
- The singer can switch between several lyrics sites.
- For a Chinese song, the lyrics come from KKBOX. Assumption: KKBOX is the first site shown for a Chinese song, and the singer can still switch to the others.
- Assumption: a "Lyrics" button on now playing opens the lyrics for the song now playing, on the phone and on the control page. It does not change the now playing layout's fit on one screen.
- Assumption: the app shows the site's lyric text inside the app, as plain text the singer scrolls, with the site's name and a link to the original page. It does not open the site itself, because lyrics sites are full of ads and many refuse to show inside another page.
- Assumption: Chinese lyrics show in Traditional script, as on the TV.
- Assumption: the text does not follow the music. The singer scrolls by hand.
- The sites are KKBOX, LRCLIB, Uta-Net, and Genius (decided 2026-11-14). Assumption: the app offers each site for every song, and the song's language only sets which site is shown first: KKBOX for Chinese, Uta-Net for Japanese, Genius for English, LRCLIB otherwise.
- KKBOX shows an "Open lyrics on KKBOX" button instead of the text (decided 2026-11-14). KKBOX's bot protection stops the app from reading its song pages, but the phone's own browser opens them. The button opens the song's KKBOX page in the phone's browser. Assumption: when the app cannot find the song on KKBOX, the button opens KKBOX's search results for the song's title and singer instead.
- 魔鏡歌詞網 (Mojim) is left out (decided 2026-11-14). On that day the site could not be reached: its name pointed at a private network address. It can be added if the site comes back.
- If a site has no lyrics for the song, or is down, the app says so for that site and the other sites still work.
- This feature is view only, on the singer's own device (decided 2026-11-14). The user's words: keep LRCLIB for the TV; this add-on should only be view-only lyrics on users' devices. The site's lyrics never change the TV's lyrics or the song's saved lyrics, and the TV's lyrics still come from LRCLIB.

## Advanced lyrics matching (added 2026-11-14)

The user's words: some song videos have a long intro before the song starts, sometimes with someone speaking or background sound. The video plays, the song only starts at 20 s, but the lyrics start to roll from 0 s. Sometimes the video is a live performance, or has a bridging drama scene in the middle of the song. Don't overwrite the current lyrics generation approach. Mark the new approach as "advanced lyrics matching" that we can enable, so we can switch back and forth, or dump it completely if we don't want it.

### What the user sees today

The lyrics start lighting up during the intro, stop on one word, and catch up when the real singing starts. Today's timing has to place every lyric word somewhere in the video, in LRCLIB's order. It has no way to say "nobody is singing this song here", so it puts early words on intro speech or noise.

### What advanced lyrics matching does

- Lyrics light up only while the song is actually sung. Intros, outros, spoken parts, drama scenes, and an artist talking to the crowd show no lit words.
- The lyrics follow the video, not the album. In a live performance, a chorus sung three times shows three times, and a skipped verse is left out. Assumption: within a line, the words keep LRCLIB's order. Only whole lines can repeat, be skipped, or move.
- During a break of 8 seconds or more, the TV clears the lyrics and shows "♪ intro" or "♪ break" with a countdown to the next line. Assumption: the 8-second length, and the next line appears 3 seconds before it is sung.
- Where the app is unsure, for example a chorus the crowd sings while the artist is silent, the TV shows its best guess and lights the words as usual (decided 2026-11-14). Assumption: the TV does not mark these lines as guessed.
- The words still come from LRCLIB. Songs with no LRCLIB lyrics keep today's transcribed lyrics and their "Lyrics may be wrong" mark. Assumption: they get no advanced version.

### Fix only the long intro (decided 2026-11-14, after the full library run)

The user's words: the original approach is already very good, about 95% of the songs' lyrics are a match. Whisper's accuracy is not that high for songs, so don't trust its result that much. Use it only as a reference to anchor some parts of the lyrics. Mark the original approach as the default, and only adjust the lyrics if Whisper is confidently saying the line is off. Build the cautious version: I don't want to ruin the 9 in 10 songs, I want it to fix just that 1 song, and strictly not affect the other 9. That one song is always due to a long wait at the intro.

The user left the design to the agent. The agent decided:

- Advanced lyrics fix only the opening of a song, where the current lyrics start before the singing does.
- From the first place where Whisper confidently agrees with the current lyrics, to the end of the song, the advanced lyrics are an exact copy of the current lyrics.
- The opening is re-timed only when Whisper confidently heard at least 2 opening lines, each sung more than 2 s later than the current lyrics show them, and none sung earlier.
- A song that does not need this fix gets no advanced lyrics at all, so the switch changes nothing on it. That is the guarantee for the other 9 songs.
- When Whisper heard too little of the song to be trusted, the song gets no advanced lyrics either.
- Advanced lyrics have the same lines as the current lyrics, in the same order. They never add, repeat, or leave out a line.
- On a fixed song, the TV shows "♪ Intro" with a countdown until the first line. There is no countdown for breaks later in the song, because the rest of the song is the current lyrics.
- This replaces the broader behaviour above: live performances, drama scenes, and breaks mid-song keep the current lyrics. The earlier bullets under "What advanced lyrics matching does" describe the first version and no longer apply beyond the intro.

### Switch it on and off

- Preparation always makes both versions of the lyrics, the current one and the advanced one, whether the switch is on or off (decided 2026-11-14). The user's words: have 2 lyrics matching processed during the preparation so that it can be enabled or disabled while they are singing, and it can take effect immediately.
- The switch can be flipped at any time, including in the middle of a song. It takes effect immediately: the TV changes to the other lyrics at the same place in the song, and the song keeps playing without a pause.
- Advanced lyrics matching is on by default for all songs (changed 2026-11-15; it was off by default before). Songs with no advanced lyrics show their current lyrics, so the default changes nothing for them. Assumption: a singer can still turn it off, and the app remembers that choice across restarts like the vocal setting. Assumption: the switch applies to the whole app. It is on the control page and on the phone's now playing, and every screen shows its current state like the vocal and key settings. On the phone it sits beside the play button, so now playing still fits on one screen. For a song marked "Lyrics may be wrong", that mark shows there instead: the song has no advanced lyrics, so the switch would do nothing for it.
- The current approach is never replaced. Every song keeps its current lyrics, and the advanced lyrics are saved beside them.
- When the switch is on and a song has no advanced lyrics, the TV uses the current lyrics. This happens when advanced matching failed for that song, or the song has no LRCLIB lyrics.
- Assumption: songs already in the library get advanced lyrics in the background, once, after any queued song that is still preparing. Until a song has them, the switch has no effect on that song.
- Dumping the approach means deleting its own code and its saved files. Nothing else in the app changes.

### What good looks like

The user picks test videos: some with long intros, some with speaking in the intro, some live performances, and some with a drama scene mid-song. Someone marks by hand when lines are really sung. On those videos, advanced matching must meet all of these:

- The first line after every intro or break starts within 0.5 s of when it is really sung.
- Every line starts within 1 s of when it is really sung.
- No word is lit for more than 1 s while nobody is singing the song.

The same videos are also measured with the current approach, so the two can be compared.

## Open questions

- **Advanced lyrics matching (2026-11-14):** which songs make up the test set? The agent can suggest candidates from the library, but the user knows which videos showed the problem.
- **Advanced lyrics matching (2026-11-14):** how much longer may preparing a song take? Measured: a median of 13 s more per song with the graphics card (technical spec, "Measured results (2026-11-14)"). The user will judge it in use.

Decided 2026-11-12: favourites follow the browser, with the restore offer above. Region boxes use YouTube Music's charts and playlists. Two friends sharing one phone count as one singer. Decided 2026-11-14: the lyrics sites, and that site lyrics are view only on the singer's device while the TV keeps LRCLIB.
