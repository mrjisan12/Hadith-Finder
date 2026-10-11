"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, Highlighter, Maximize, TriangleAlert, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { PrintedPage, pdfPageLabel, type ViewerTarget } from "@/components/source-card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { apiUrl, fetchPage } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ZOOMS = [1, 1.35, 1.75, 2.25, 3];

const NO_BOXES: number[][] = [];

/**
 * Shows the ORIGINAL scanned page image (never a reconstruction), with the cited paragraph's
 * OCR line boxes highlighted on top of it. Mount with a fresh `key` per opening so its state
 * (page, zoom) starts clean.
 */
export function PageViewer({ target, onClose }: { target: ViewerTarget | null; onClose: () => void }) {
  const { t, num } = useI18n();
  const [pageId, setPageId] = useState<number | null>(target?.pageId ?? null);
  const [zoomIdx, setZoomIdx] = useState(0);
  const [showHighlight, setShowHighlight] = useState(true);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: page, isError } = useQuery({
    queryKey: ["page", pageId],
    queryFn: () => fetchPage(pageId!),
    enabled: pageId !== null,
  });

  const src = page ? apiUrl(page.image_url) : null;
  const loaded = src !== null && loadedSrc === src;
  const boxes = useMemo(
    () => (pageId === target?.pageId ? (target?.lineBoxes ?? NO_BOXES) : NO_BOXES),
    [pageId, target],
  );
  const zoom = ZOOMS[zoomIdx];

  // Bring the highlighted passage into view once the image has loaded / zoom changed.
  useEffect(() => {
    if (!loaded || !boxes.length || !scrollRef.current) return;
    const el = scrollRef.current;
    const top = Math.min(...boxes.map((b) => b[1]));
    el.scrollTo({ top: Math.max(0, top * el.scrollHeight - el.clientHeight * 0.25), behavior: "smooth" });
  }, [loaded, zoomIdx, boxes]);

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex h-[94vh] w-[97vw] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3 pr-12">
          <div className="min-w-0">
            <DialogTitle className="text-base">
              {page ? (page.book_native ?? page.book) : <Skeleton className="h-5 w-40" />}
              {page?.section && <span className="font-normal text-muted-foreground"> · {page.section}</span>}
            </DialogTitle>
            <DialogDescription className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {page && (
                <>
                  <PrintedPage label={page.printed_page_label} source={page.printed_page_source} />
                  <span>
                    <span className="text-muted-foreground">{t.pdfPage}:</span> <span className="font-semibold text-foreground">{pdfPageLabel(num, page.pdf_page, page.merged_with_pdf_page)}</span>
                  </span>
                  <span className="text-muted-foreground">{t.scanNote}</span>
                </>
              )}
            </DialogDescription>
            {page?.needs_review && (
              <p className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                <TriangleAlert className="size-3.5" /> {t.needsReview}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1 border-b bg-muted/40 px-3 py-1.5">
          <Button variant="ghost" size="sm" disabled={!page?.prev_page_id} onClick={() => page?.prev_page_id && setPageId(page.prev_page_id)}>
            <ChevronLeft /> {t.prevPage}
          </Button>
          <Button variant="ghost" size="sm" disabled={!page?.next_page_id} onClick={() => page?.next_page_id && setPageId(page.next_page_id)}>
            {t.nextPage} <ChevronRight />
          </Button>
          <span className="mx-1 h-5 w-px bg-border" />
          <Button variant="ghost" size="icon-sm" aria-label={t.zoomOut} disabled={zoomIdx === 0} onClick={() => setZoomIdx((z) => Math.max(0, z - 1))}>
            <ZoomOut />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
          <Button variant="ghost" size="icon-sm" aria-label={t.zoomIn} disabled={zoomIdx === ZOOMS.length - 1} onClick={() => setZoomIdx((z) => Math.min(ZOOMS.length - 1, z + 1))}>
            <ZoomIn />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setZoomIdx(0)}>
            <Maximize /> {t.fit}
          </Button>
          {boxes.length > 0 && (
            <Button variant={showHighlight ? "secondary" : "ghost"} size="sm" onClick={() => setShowHighlight((v) => !v)}>
              <Highlighter /> {t.highlight}
            </Button>
          )}
          {page && (
            <a
              href={apiUrl(page.image_url)}
              target="_blank"
              rel="noreferrer noopener"
              className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <ExternalLink className="size-3.5" /> {t.openImage}
            </a>
          )}
        </div>

        <div ref={scrollRef} className="relative flex-1 overflow-auto bg-neutral-200/70">
          {isError && <p className="p-6 text-center text-sm text-destructive">{t.error}</p>}
          {page && (
            <div className="mx-auto my-4 px-4" style={{ width: `${Math.round(zoom * 100)}%`, maxWidth: zoom === 1 ? 900 : undefined }}>
              <div className="relative bg-white shadow-md">
                {!loaded && <Skeleton className="absolute inset-0" />}
                {/* eslint-disable-next-line @next/next/no-img-element -- original scan served by the API; must not be re-encoded */}
                <img
                  key={page.id}
                  src={src!}
                  alt={`${page.book} — PDF ${page.pdf_page}`}
                  className={cn("block h-auto w-full select-none", !loaded && "opacity-0")}
                  onLoad={() => setLoadedSrc(src)}
                  draggable={false}
                />
                {loaded &&
                  showHighlight &&
                  boxes.map((b, i) => (
                    <div
                      key={i}
                      className="pointer-events-none absolute rounded-sm bg-yellow-300/35 ring-1 ring-yellow-500/60 mix-blend-multiply"
                      style={{
                        left: `${(b[0] - 0.006) * 100}%`,
                        top: `${(b[1] - 0.003) * 100}%`,
                        width: `${(b[2] - b[0] + 0.012) * 100}%`,
                        height: `${(b[3] - b[1] + 0.006) * 100}%`,
                      }}
                    />
                  ))}
              </div>
            </div>
          )}
          {!page && !isError && (
            <div className="mx-auto my-4 max-w-225 px-4">
              <Skeleton className="aspect-[3/4.7] w-full" />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
