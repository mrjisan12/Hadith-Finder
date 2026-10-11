"use client";

import { Bug, ChevronDown } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useI18n } from "@/lib/i18n";
import type { DebugInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Development aid: why was each passage selected (per-retriever ranks, fused and rerank scores). */
export function DebugPanel({ debug }: { debug: DebugInfo }) {
  const { t } = useI18n();
  return (
    <Collapsible className="rounded-lg border border-dashed text-xs">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-muted-foreground hover:text-foreground">
        <Bug className="size-3.5" /> {t.debug}
        <span className="ml-2">
          reranker={debug.reranker} · threshold={debug.threshold} · {Object.entries(debug.latencies_ms ?? {})
            .filter(([k]) => !k.includes("."))
            .map(([k, v]) => `${k} ${Math.round(v)}ms`)
            .join(" · ")}
        </span>
        <ChevronDown className="ml-auto size-3.5" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 border-t px-3 py-2">
        {debug.errors && debug.errors.length > 0 && <pre className="whitespace-pre-wrap text-destructive">{debug.errors.join("\n")}</pre>}
        <details>
          <summary className="cursor-pointer">query plan</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{JSON.stringify(debug.query_plan, null, 2)}</pre>
        </details>
        <div className="text-muted-foreground">lists: {JSON.stringify(debug.list_sizes)}</div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead className="text-muted-foreground">
              <tr>
                <th className="p-1">#</th>
                <th className="p-1">rerank</th>
                <th className="p-1">fused</th>
                <th className="p-1">pdf/printed</th>
                <th className="p-1">ranks</th>
                <th className="p-1">snippet</th>
              </tr>
            </thead>
            <tbody>
              {debug.candidates?.map((c, i) => (
                <tr key={c.source_id ?? i} className={cn("border-t align-top", c.selected && "bg-primary/5 font-medium")}>
                  <td className="p-1">{i + 1}</td>
                  <td className="p-1 tabular-nums">{c.rerank_score ?? "–"}</td>
                  <td className="p-1 tabular-nums">{c.fused_score.toFixed(4)}</td>
                  <td className="p-1 whitespace-nowrap">
                    {c.pdf_page}/{c.printed_page ?? "?"}
                  </td>
                  <td className="p-1 whitespace-nowrap">
                    {Object.entries(c.ranks)
                      .map(([k, v]) => `${k.replace("vec_", "v:")}#${v}`)
                      .join(" ")}
                  </td>
                  <td className="p-1 font-[family-name:var(--font-source)]">{c.snippet}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
