"use client";

import ReactMarkdown from "react-markdown";

import { useI18n } from "@/lib/i18n";

const INSUFFICIENT = "[[INSUFFICIENT_EVIDENCE]]";
const CITATION = /\[(chunk_[0-9a-f]{10})\]/g;

/**
 * Renders the AI answer. Citation markers `[chunk_…]` become numbered chips pointing at the
 * source cards. Markers for ids that are not verified sources of this answer are dropped, so a
 * citation can never point at something the backend did not return.
 */
export function AnswerText({
  text,
  citationNumbers,
  onCite,
}: {
  text: string;
  citationNumbers: Map<string, number>;
  onCite: (sourceId: string) => void;
}) {
  const { num } = useI18n();
  let md = text.replace(INSUFFICIENT, "").trimStart();
  md = md.replace(/\[chunk_[0-9a-f]{0,10}$/, ""); // half-streamed marker
  md = md.replace(CITATION, (_, id: string) => {
    const n = citationNumbers.get(id);
    return n ? ` [${n}](#cite-${id})` : "";
  });

  return (
    <div className="bn-text prose-answer text-[15.5px] text-foreground [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-2 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-6">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) {
              const id = href.slice(6);
              const n = citationNumbers.get(id) ?? 0;
              return (
                <button
                  type="button"
                  onClick={() => onCite(id)}
                  className="mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-full bg-primary/10 px-1.5 align-middle text-[11px] font-semibold text-primary transition hover:bg-primary hover:text-primary-foreground"
                  aria-label={`source ${n}`}
                >
                  {num(n)}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">
                {children}
              </a>
            );
          },
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}
