// Names for the contract's unions and vocabularies, derived from the generated models. The codegen names only
// pydantic models, so each alias below is read off the field that carries it. A contract change still breaks
// the compile here or at the use site, never at runtime.
import type {
  Contract,
  EntryView,
  FailedState,
  ImportItemView,
  LyricsDoc,
  MoveCmd,
  PhoneCommandMsg,
  PreparingState,
  ReplyMsg,
  Rejected,
  SearchResponse,
  TvCommandMsg,
} from "./generated";

export type * from "./generated";

export type ClientMessage = Contract["client"];
export type ServerMessage = Contract["server"];
export type PhoneCommand = PhoneCommandMsg["command"];
export type TvCommand = TvCommandMsg["command"];
export type Outcome = ReplyMsg["outcome"];
export type MoveTarget = MoveCmd["to"];
export type Readiness = EntryView["readiness"];
export type OnlineResults = SearchResponse["online"];
export type VideoChoiceResponse = Contract["videoChoice"];

export type RejectReason = Rejected["reason"];
export type PrepStage = PreparingState["stage"];
export type FailReason = FailedState["reason"];
export type LyricsSource = LyricsDoc["source"];
export type ImportDecision = ImportItemView["decision"];
export type RestoreOfferResponse = Contract["restoreOffer"];
export type FavouriteRef = Contract["favouriteAdd"]["ref"];
