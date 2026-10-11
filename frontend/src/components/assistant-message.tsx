"use client";

import { CircleAlert, Loader2, SearchX } from "lucide-react";
import { useMemo, useState } from "react";

import { AnswerText } from "@/components/answer-text";
import { DebugPanel } from "@/components/debug-panel";
import { SourceCard, type ViewerTarget } from "@/components/source-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n";
import type { ChatStage, DebugInfo, Source } from "@/lib/types";

export interface AssistantTurn {
  id: string;
  role: "assistant";
  stage: ChatStage | null;
  answer: string;
  sources: Source[];
  done: boolean;
  insufficient: boolean;
  error: string | null;
  debug?: DebugInfo;
}

export function AssistantMessage({ turn, onView }: { turn: AssistantTurn; onView: (t: ViewerTarget) => void }) {
  const { t } = useI18n();
  const [flash, setFlash] = useState<string | null>(null);

  // Cited sources first (numbered in citation order), then related-but-uncited ones.
  const { cited, related, numbers } = useMemo(() => {
    const citedList = turn.done ? turn.sources.filter((s) => s.cited) : turn.sources;
    const relatedList = turn.done ? turn.sources.filter((s) => !s.cited) : [];
    const map = new Map<string, number>();
    citedList.forEach((s, i) => map.set(s.source_id, i + 1));
    relatedList.forEach((s, i) => map.set(s.source_id, citedList.length + i + 1));
    return { cited: citedList, related: relatedList, numbers: map };
  }, [turn.sources, turn.done]);

  const scrollTo = (id: string) => {
    document.getElementById(`source-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setFlash(id);
    setTimeout(() => setFlash(null), 1600);
  };

  const waiting = !turn.done && !turn.answer;

  return (
    <div className="space-y-4">
      <section className="rounded-xl border bg-card px-4 py-3 shadow-sm">
        <div className="mb-1 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {t.answer}
          {turn.insufficient && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium normal-case tracking-normal text-amber-800">
              <SearchX className="size-3" /> {t.insufficient}
            </span>
          )}
        </div>
        {waiting ? (
          <div className="space-y-2 py-1">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> {turn.stage ? t.stage[turn.stage] : t.stage.understanding}
            </div>
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-8/12" />
          </div>
        ) : (
          <AnswerText text={turn.answer} citationNumbers={numbers} onCite={scrollTo} />
        )}
        {!turn.done && turn.answer && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary/60 align-middle" />}
        {turn.error && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-destructive">
            <CircleAlert className="size-4" /> {turn.error}
          </p>
        )}
      </section>

      {cited.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-muted-foreground">{t.sources}</h3>
          {cited.map((s) => (
            <SourceCard key={s.source_id} source={s} number={numbers.get(s.source_id) ?? 0} onView={onView} highlighted={flash === s.source_id} />
          ))}
        </section>
      )}

      {related.length > 0 && (
        <details className="group space-y-3">
          <summary className="cursor-pointer text-sm font-semibold text-muted-foreground hover:text-foreground">
            {t.relatedSources} ({related.length})
          </summary>
          <div className="mt-3 space-y-3">
            {related.map((s) => (
              <SourceCard key={s.source_id} source={s} number={numbers.get(s.source_id) ?? 0} onView={onView} highlighted={flash === s.source_id} />
            ))}
          </div>
        </details>
      )}

      {turn.debug && <DebugPanel debug={turn.debug} />}
    </div>
  );
}
