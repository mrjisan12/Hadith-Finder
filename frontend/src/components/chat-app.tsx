"use client";

import { ArrowUp, BookOpenText, Languages, RotateCcw, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AssistantMessage, type AssistantTurn } from "@/components/assistant-message";
import { PageViewer } from "@/components/page-viewer";
import type { ViewerTarget } from "@/components/source-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ChatHttpError, SHOW_DEBUG, streamChat } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ChatEvent, HistoryTurn } from "@/lib/types";

interface UserTurn {
  id: string;
  role: "user";
  content: string;
}
type Turn = UserTurn | AssistantTurn;

const uid = () => Math.random().toString(36).slice(2);
const stripCitations = (s: string) => s.replace(/\[(chunk_[0-9a-f]{10})\]/g, "").replace("[[INSUFFICIENT_EVIDENCE]]", "").trim();

export function ChatApp() {
  const { t, lang, setLang } = useI18n();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [viewerKey, setViewerKey] = useState(0);
  const openViewer = useCallback((target: ViewerTarget) => {
    setViewer(target);
    setViewerKey((k) => k + 1);
  }, []);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const updateAssistant = useCallback((id: string, fn: (a: AssistantTurn) => AssistantTurn) => {
    setTurns((prev) => prev.map((m) => (m.id === id && m.role === "assistant" ? fn(m) : m)));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  const send = async (query: string) => {
    const q = query.trim();
    if (!q || busy) return;
    const history: HistoryTurn[] = turns.slice(-8).map((m) =>
      m.role === "user" ? { role: "user", content: m.content } : { role: "assistant", content: stripCitations(m.answer).slice(0, 2000) },
    );
    const assistantId = uid();
    setTurns((prev) => [
      ...prev,
      { id: uid(), role: "user", content: q },
      { id: assistantId, role: "assistant", stage: "understanding", answer: "", sources: [], done: false, insufficient: false, error: null },
    ]);
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const onEvent = (e: ChatEvent) => {
      switch (e.type) {
        case "status":
          updateAssistant(assistantId, (a) => ({ ...a, stage: e.stage }));
          break;
        case "sources":
          updateAssistant(assistantId, (a) => ({ ...a, sources: e.sources }));
          break;
        case "delta":
          updateAssistant(assistantId, (a) => ({ ...a, answer: a.answer + e.text }));
          break;
        case "final":
          updateAssistant(assistantId, (a) => ({
            ...a,
            answer: e.answer,
            sources: e.sources,
            insufficient: e.insufficient_evidence,
            done: true,
            stage: null,
            error: e.error ? t.error : null,
            debug: e.debug,
          }));
          break;
        case "error":
          updateAssistant(assistantId, (a) => ({ ...a, done: true, error: t.error }));
          break;
      }
    };

    try {
      await streamChat({ query: q, history, debug: SHOW_DEBUG }, onEvent, controller.signal);
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      const message = err instanceof ChatHttpError && err.status === 429 ? t.rateLimited : t.error;
      updateAssistant(assistantId, (a) => ({ ...a, done: true, stage: null, error: aborted ? null : message }));
    } finally {
      updateAssistant(assistantId, (a) => (a.done ? a : { ...a, done: true, stage: null }));
      setBusy(false);
      abortRef.current = null;
      inputRef.current?.focus();
    }
  };

  const reset = () => {
    abortRef.current?.abort();
    setTurns([]);
    setInput("");
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpenText className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="font-semibold leading-tight">{t.appName}</h1>
            <p className="truncate text-xs text-muted-foreground">ফাযায়েলে আমল · Fazail-e-Amal</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setLang(lang === "bn" ? "en" : "bn")} aria-label="language">
            <Languages /> {lang === "bn" ? "English" : "বাংলা"}
          </Button>
          {turns.length > 0 && (
            <Button variant="outline" size="sm" onClick={reset}>
              <RotateCcw /> <span className="hidden sm:inline">{t.newChat}</span>
            </Button>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-40">
        {turns.length === 0 ? (
          <div className="flex flex-col items-center pt-16 text-center sm:pt-24">
            <div className="mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <BookOpenText className="size-7" />
            </div>
            <h2 className="text-2xl font-semibold">{t.appName}</h2>
            <p className="bn-text mt-2 max-w-xl text-muted-foreground">{t.tagline}</p>
            <div className="mt-8 w-full max-w-xl text-left">
              <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t.examplesTitle}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {t.examples.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => send(ex)}
                    className="bn-text rounded-lg border bg-card px-3 py-2.5 text-left text-sm shadow-xs transition hover:border-primary/40 hover:bg-primary/5"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-8 pt-6">
            {turns.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="bn-text max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground">{m.content}</div>
                </div>
              ) : (
                <AssistantMessage key={m.id} turn={m} onView={openViewer} />
              ),
            )}
          </div>
        )}
        <div ref={endRef} />
      </main>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/90 backdrop-blur">
        <form
          className="mx-auto flex max-w-3xl items-end gap-2 px-4 pt-3 pb-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter = newline; never send mid-IME composition (Bangla keyboards).
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder={t.placeholder}
            maxLength={1000}
            rows={1}
            className="bn-text max-h-40 min-h-11 resize-none bg-card text-[15px]"
            aria-label={t.placeholder}
          />
          {busy ? (
            <Button type="button" size="icon-lg" variant="outline" onClick={() => abortRef.current?.abort()} aria-label={t.stop}>
              <Square />
            </Button>
          ) : (
            <Button type="submit" size="icon-lg" disabled={!input.trim()} aria-label={t.send}>
              <ArrowUp />
            </Button>
          )}
        </form>
        <p className="mx-auto max-w-3xl px-4 pb-2 text-center text-[11px] text-muted-foreground">{t.disclaimer}</p>
      </div>

      <PageViewer key={viewerKey} target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
