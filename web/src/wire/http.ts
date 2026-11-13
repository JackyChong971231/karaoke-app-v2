// HTTP queries. Every body is a contract model serialized by the server from the same contract.py the types
// are generated from, so the boundary check is the HTTP status; the shape is the contract's.

import type {
  ArtistPlaceRequest,
  ArtistResponse,
  BrowseResponse,
  PlaceId,
  PlaceResponse,
  ReadyResponse,
  FavouriteAddRequest,
  FavouriteRemoveRequest,
  FavouritesResponse,
  RestoreClaimRequest,
  RestoreOfferResponse,
  ImportDecideRequest,
  ImportPlanView,
  LyricsDoc,
  SearchResponse,
  VideoChoiceResponse,
  WhoAmIResponse,
} from "./types";

export class HttpError extends Error {
  constructor(readonly status: number, url: string) {
    super(`${String(status)} from ${url}`);
  }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new HttpError(res.status, url);
  const text = await res.text();
  return (text === "" ? null : JSON.parse(text)) as T;
}

const q = encodeURIComponent;

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  search: (query: string, signal: AbortSignal) => request<SearchResponse>(`/api/search?q=${q(query)}`, { signal }),
  artist: (artistId: string, signal: AbortSignal) => request<ArtistResponse>(`/api/artist/${q(artistId)}`, { signal }),
  browse: (_key: string, signal: AbortSignal) => request<BrowseResponse>("/api/browse", { signal }),
  place: (placeId: string, signal: AbortSignal) => request<PlaceResponse>(`/api/place/${q(placeId)}`, { signal }),
  /** Whether this browser is on the laptop running the app, which never asks for a name. */
  whoami: () => request<WhoAmIResponse>("/api/whoami"),
  ready: (_key: string, signal: AbortSignal) => request<ReadyResponse>("/api/ready", { signal }),
  /** Control page: where a singer is from. Null returns them to the app's guess. */
  setArtistPlace: (artistId: string, name: string, placeId: PlaceId | null) =>
    post<unknown>("/api/artist-place", { artistId, name, placeId } satisfies ArtistPlaceRequest),
  videoChoice: (onlineKey: string, signal: AbortSignal) =>
    request<VideoChoiceResponse>(`/api/video-choice?key=${q(onlineKey)}`, { signal }),
  /** Phones: always a list, the official video first and flagged. `key` may be `lib:<song id>`. */
  videoOptions: (onlineKey: string, signal: AbortSignal) =>
    request<VideoChoiceResponse>(`/api/video-options?key=${q(onlineKey)}`, { signal }),
  favourites: (browserId: string) => request<FavouritesResponse>(`/api/favourites?browser=${q(browserId)}`),
  favouriteAdd: (body: FavouriteAddRequest) => post<FavouritesResponse>("/api/favourites/add", body),
  favouriteRemove: (body: FavouriteRemoveRequest) => post<FavouritesResponse>("/api/favourites/remove", body),
  /** A saved list this phone may take back: by its Wi-Fi address, or by the typed name. */
  restoreOffer: (name: string | null) =>
    request<RestoreOfferResponse>(name === null ? "/api/favourites/offer" : `/api/favourites/offer?name=${q(name)}`),
  restoreClaim: (body: RestoreClaimRequest) => post<FavouritesResponse>("/api/favourites/claim", body),
  lyrics: (songId: string, signal: AbortSignal) => request<LyricsDoc>(`/media/${q(songId)}/lyrics.json`, { signal }),
  importPlan: (signal?: AbortSignal) => request<ImportPlanView>("/api/import", signal ? { signal } : {}),
  importMatch: (limit: number | null) =>
    request<unknown>(limit === null ? "/api/import/plan" : `/api/import/plan?limit=${String(limit)}`, { method: "POST" }),
  importDecide: (body: ImportDecideRequest) =>
    request<unknown>("/api/import/decide", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  importRun: () => request<unknown>("/api/import/run", { method: "POST" }),
};

export function mediaUrl(songId: string, file: "video.mp4" | "instrumental.opus" | "vocals.opus"): string {
  return `/media/${q(songId)}/${file}`;
}

/** YouTube's still for a video ID. Song IDs are YouTube video IDs; callers fall back when it fails to load. */
export function thumbnailFor(songId: string): string {
  return `https://i.ytimg.com/vi/${q(songId)}/mqdefault.jpg`;
}
