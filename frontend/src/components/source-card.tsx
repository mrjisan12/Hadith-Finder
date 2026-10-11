"use client";

import { BookOpen, Check, Copy, FileImage, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n";
import type { PagePart, Source } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ViewerTarget {
  pageId: number;
  lineBoxes: number[][] | null;
}

const isRtl = (lang: string) => lang === "ar" || lang === "ur";

/** "263" or, for a printed page the scanner split over two PDF pages, "189–190". */
export function pdfPageLabel(num: (n: number) => string, start: number, other?: number | null) {
  if (!other || other === start) return num(start);
  const [a, b] = start < other ? [start, other] : [other, start];
  return `${num(a)}–${num(b)}`;
}

export function PrintedPage({ label, source }: { label: string | null; source: Source["printed_page_source"] }) {
  const { t, num } = useI18n();
  const value = label ? num(label) : t.pageUnknown;
  const note = source === "inferred" ? t.pageInferred : source === "manual" ? t.pageManual : source === "unknown" ? t.pageUnknown : null;
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-muted-foreground">{t.printedPage}:</span>
      <span className="font-semibold text-foreground">{value}</span>
      {note && source !== "unknown" && <span className="text-[11px] text-muted-foreground">({note})</span>}
    </span>
  );
}

function PartBlock({ part, label, onView }: { part: PagePart; label: string; onView: (t: ViewerTarget) => void }) {
  const { t, num } = useI18n();
  return (
    <div className="rounded-md border border-dashed border-paper-border bg-paper/60 px-3 py-2">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {label} · {t.printedPage} {part.printed_page_label ? num(part.printed_page_label) : t.pageUnknown} · {t.pdfPage}{" "}
          {pdfPageLabel(num, part.pdf_page, part.pdf_page_end)}
        </span>
        <Button variant="ghost" size="xs" onClick={() => onView({ pageId: part.page_id, lineBoxes: null })}>
          <FileImage /> {t.viewOriginal}
        </Button>
      </div>
      <p lang="bn" className="source-text text-[15px] text-foreground/90">
        {part.text}
      </p>
    </div>
  );
}

export function SourceCard({
  source,
  number,
  onView,
  highlighted,
}: {
  source: Source;
  number: number;
  onView: (t: ViewerTarget) => void;
  highlighted?: boolean;
}) {
  const { t, num } = useI18n();
  const [copied, setCopied] = useState(false);
  const text = source.original_text;
  const partial = source.match_start > 0 || source.match_end < text.length;
  const path = [source.section, source.chapter].filter(Boolean).join(" › ");

  const copy = async () => {
    const ref = `${source.book_native ?? source.book} — ${t.printedPage} ${source.printed_page_label ?? "?"}, ${t.pdfPage} ${pdfPageLabel(String, source.pdf_page, source.pdf_page_end)}`;
    await navigator.clipboard.writeText(`${text}\n\n(${ref})`);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <article
      id={`source-${source.source_id}`}
      className={cn(
        "scroll-mt-24 rounded-xl border bg-card shadow-sm transition-shadow",
        highlighted && "ring-2 ring-primary/50",
      )}
    >
      <header className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b px-4 py-3">
        <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {num(number)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 font-medium">
            <BookOpen className="size-4 text-primary" />
            <span>{source.book_native ?? source.book}</span>
            {source.book_native && <span className="text-sm font-normal text-muted-foreground">({source.book})</span>}
          </div>
          {path && <div className="mt-0.5 text-sm text-muted-foreground">{path}</div>}
          {source.heading && source.heading !== source.chapter && (
            <div className="text-sm text-muted-foreground">› {source.heading}</div>
          )}
        </div>
        <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 text-sm sm:w-auto sm:flex-col sm:items-end">
          <PrintedPage label={source.printed_page_label} source={source.printed_page_source} />
          <span>
            <span className="text-muted-foreground">{t.pdfPage}:</span> <span className="font-semibold">{pdfPageLabel(num, source.pdf_page, source.pdf_page_end)}</span>
          </span>
        </div>
      </header>

      <div className="space-y-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t.originalPassage}</span>
          {source.hadith_number && (
            <Badge variant="outline">
              {t.hadith} {num(source.hadith_number)}
            </Badge>
          )}
          <Tooltip>
            <TooltipTrigger render={<span />} className="inline-flex cursor-help items-center gap-1 text-xs text-primary">
              <ShieldCheck className="size-3.5" /> {t.verified}
            </TooltipTrigger>
            <TooltipContent className="max-w-sm">{t.verifiedHelp}</TooltipContent>
          </Tooltip>
        </div>

        {source.previous_part && <PartBlock part={source.previous_part} label={`← ${t.continuedFrom}`} onView={onView} />}

        <blockquote
          lang={source.lang}
          dir={isRtl(source.lang) ? "rtl" : "ltr"}
          className="source-text rounded-lg border border-paper-border bg-paper px-4 py-3 text-[16px] text-foreground"
        >
          {partial ? (
            <>
              {text.slice(0, source.match_start)}
              <mark className="rounded-sm bg-highlight px-0.5 text-foreground">{text.slice(source.match_start, source.match_end)}</mark>
              {text.slice(source.match_end)}
            </>
          ) : (
            text
          )}
        </blockquote>

        {source.continuation && <PartBlock part={source.continuation} label={`${t.continuesOn} →`} onView={onView} />}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button size="sm" onClick={() => onView({ pageId: source.page_id, lineBoxes: source.line_boxes })}>
            <FileImage /> {t.viewOriginal}
          </Button>
          <Button size="sm" variant="outline" onClick={copy}>
            {copied ? <Check /> : <Copy />} {copied ? t.copied : t.copy}
          </Button>
        </div>
      </div>
    </article>
  );
}
