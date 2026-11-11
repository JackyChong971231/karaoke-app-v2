# Karaoke App V2 #
Purpose: This is a application that it searches the music vidoes from data source (maybe YouTube, if this is still the best source), remove vocals, and generating lyrics and syncing the lyrics with the video, and output the video along with the sound (allowing users to select with vocal or without). 

# My old repo #
- a python gui that allows user to connect to it through private wifi connection. After the user copy and paste the youtube url, the gui will then download the video, remove vocals and generate the lyrics. When all these are ready, the gui will then show the video along with the sound (with or without vocal). The laptop will then output the sound to an audio mixer, and the audio mixer mix the sound receive from wireless microphone and transmit to the onkyo audio receiver, and at last output to my 5.1 sound system, while the TV is showing the video plus the lyric.

# Requirement #

## System ##
- I am not sure if the above approach is the best approach for a diy home karaoke app. If it does, you can stick with that approach, if not, recommend a better approach.

## Limitation ##
- The TV audio cannot be output to the audio mixer yet. So tell me which approach is better first before writing the code. Then I will confirm with the system design

## UI ##
- Allow users to access the control of this app on their mobile phone by scanning a QR Code showing on the TV
- The basic control should allow the following control
    - Pause songs, skip songs
    - enable or disable vocal from the audio
    - seeing what songs are in the queue as well as who place the song (coming from which mobile devices)
    - selecting songs (local songs or online)
        - the song should show the song title, singer
    - song selection can be searched using artists
    - overall, I want a more user friendly song selection control page, 
- The lyrics should have an indicator on which exact word it is being sung in the line. Simulating the actual karaoke app where the lyrics will follow word by word by highliting them in blue
- the lyrics part should simulate the actual karaoke app where there are 2 lines shown, when the current lyrics is sung, the next line should ready on the other line. And when current  line is finished, is should prepare for the next line again. Let me know if you need more clarification on how the karaoke app works. 

## backend ##
- when song is selected, the back should have the music video ready, remove the vocal from the audio from the music video, then by analyzing the vocal audio, transcribe them into lyrics.
- To avoid songs being dominated by how fast the mobile device selected songs by the user, everytime when the song is selected on the mobile device, the order of the songs should follow how many people are in the queue. For example, when song selection order is as following : By A -> By B -> By B -> By B -> By B -> By A -> By C, the song ordering at last should be like: By A -> By B -> By C -> By A -> By B -> By B -> By B. So that each person do not have to wait for a long time, preventing 咪霸. And when a song by C is added, the order will be By A -> By B -> By C -> By A -> By B -> By C -> By B -> By B.
- song should be saved in the local laptop so that when the same song is selected the next time, there is no processing time.

# Improvements I want to make comparing with the old repo #
- Downloading videos from youtube takes too much time that sometimes the screen of the tv will have to wait until the next song is loaded
- when users skip too many songs in a row, the next song might not be ready. So the prepartion of the song should start whenever the song is added
- When interacting with youtube, it depends on whether the library is up to date. so the app should automatically fix those version compatability issue
- the lyrics transcribed is always not correct, leading to a problem that the users have to select lyrics video instead of music video. so basically the lyrics generation is not reliable
- even though lyrics are generated, it only sync with the video on which line is the current line. But I want the accuracy to also following which exact word is sung so the sung words will be highlighted in blue
- The UI is not that user friendly, it seems so diy and not professional enough.

# Places where I dont know how to make the decision now #
- not sure whats the right approach to handle video download in a proper way
- not sure how to really get the artist name correctly so that songs will be grouped into singer perfectly
- not sure how the system should be setup or my previous repo is already the best approach