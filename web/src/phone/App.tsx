// Phone remote (index.html). Screens are thin: they read the store and call store.run(controlId, command).
// Every interactive element carries a data-testid for the harness.
//
//   <NameGate>            first visit: ask name -> saveIdentity -> connect
//   <RestartPrompt>       modal while view.restartOffer: list of saved songs, Keep / Start new (first answer wins)
//   <NowPlaying>          title, artist, singer (or "Filler"), progress bar from store.progressS(),
//                         pause/resume  -> setPaused { playId, paused: !now.paused }
//                         skip          -> skip { playId }
//                         key - / +     -> setKey { playId, semitones: now.semitones -/+ 1 }   (absolute)
//                         vocal slider  -> setVocal { level }   (throttled to 10 Hz while dragging, final value on release)
//                         "Lyrics may be wrong" chip when now.lyricsFlagged
//   <Queue>               rows: title, artist, singer, readiness chip (stageText / failText / Ready)
//                         row menu: Play next -> move { at: "front" }, Remove -> remove; drag handle -> move { before }
//   <Search>              one box; debounced GET /api/search; library hits marked Ready -> queueLibrary;
//                         online hits -> pickReducer('choose') -> VideoPicker sheet when candidates come back;
//                         "Online search unavailable" note when online.kind === "unavailable"; artist names link to <Artist>
//   <Artist>              GET /api/artist/:id
//   <VideoPicker>         bottom sheet with candidate thumbnails; tap -> pickReducer('tap') -> queuePick
//   <Settings>            rename, AV offset (-/+ 0.05 s), shows "Preparing on GPU/CPU" from view.device

import { usePhone } from "./store";

export function App(): JSX.Element {
  void usePhone;
  throw new Error("not implemented");
}
