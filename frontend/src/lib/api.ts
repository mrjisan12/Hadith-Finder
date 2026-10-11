import type { BookInfo, ChatEvent, HistoryTurn, PageInfo } from "./types";

// Public backend URL. No secrets live in the frontend - all API keys stay on the backend.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const SHOW_DEBUG = process.env.NEXT_PUBLIC_SHOW_DEBUG === "true";

export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path));
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const fetchPage = (pageId: number) => getJson<PageInfo>(`/api/v1/pages/${pageId}`);
export const fetchBooks = () => getJson<BookInfo[]>("/api/v1/books");

export class ChatHttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** POST /api/v1/chat/stream and dispatch each Server-Sent Event. */
export async function streamChat(
  body: { query: string; history: HistoryTurn[]; book_id?: number | null; debug?: boolean },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(apiUrl("/api/v1/chat/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep statusText */
    }
    throw new ChatHttpError(res.status, detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of raw.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as ChatEvent);
        } catch {
          /* ignore malformed event */
        }
      }
    }
  }
}
