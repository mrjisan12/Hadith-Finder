// Mirrors backend/app/schemas. Every text field of a Source comes from the database.

export interface PagePart {
  text: string;
  page_id: number;
  pdf_page: number;
  pdf_page_end: number | null;
  printed_page: number | null;
  printed_page_label: string | null;
  page_image_url: string;
}

export type PrintedPageSource = "manual" | "ocr" | "inferred" | "unknown";

export interface Source {
  source_id: string;
  paragraph_id: string;
  book_id: number;
  book: string;
  book_native: string | null;
  section: string | null;
  chapter: string | null;
  heading: string | null;
  page_id: number;
  pdf_page: number;
  pdf_page_end: number | null; // one printed page split over two PDF pages
  printed_page: number | null;
  printed_page_label: string | null;
  printed_page_source: PrintedPageSource;
  original_text: string;
  matched_text: string;
  match_start: number;
  match_end: number;
  lang: string;
  hadith_number: string | null;
  ocr_confidence: number | null;
  bbox: number[] | null;
  line_boxes: number[][] | null;
  continuation: PagePart | null;
  previous_part: PagePart | null;
  page_image_url: string;
  relevance_score: number | null;
  cited: boolean;
  rank: number;
}

export interface DebugCandidate {
  source_id: string | null;
  pdf_page: number | null;
  printed_page: string | null;
  section: string | null;
  fused_score: number;
  rerank_score: number | null;
  ranks: Record<string, number>;
  raw_scores: Record<string, number>;
  selected: boolean;
  snippet: string | null;
}

export interface DebugInfo {
  query_plan?: Record<string, unknown>;
  latencies_ms?: Record<string, number>;
  reranker?: string;
  threshold?: number;
  list_sizes?: Record<string, number>;
  errors?: string[];
  candidates?: DebugCandidate[];
}

export type ChatStage = "understanding" | "retrieving" | "generating";

export type ChatEvent =
  | { type: "status"; stage: ChatStage }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | {
      type: "final";
      answer: string;
      insufficient_evidence: boolean;
      sources: Source[];
      query_id: number | null;
      error?: string;
      debug?: DebugInfo;
    }
  | { type: "error"; message: string };

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export interface PageParagraphBox {
  paragraph_id: string;
  paragraph_index: number;
  kind: string;
  lang: string;
  bbox: number[] | null;
  line_boxes: number[][] | null;
}

export interface PageInfo {
  id: number;
  book_id: number;
  book: string;
  book_native: string | null;
  pdf_page: number;
  merged_with_pdf_page: number | null;
  printed_page: number | null;
  printed_page_label: string | null;
  printed_page_source: PrintedPageSource;
  section: string | null;
  running_header: string | null;
  image_url: string;
  width: number | null;
  height: number | null;
  needs_review: boolean;
  prev_page_id: number | null;
  next_page_id: number | null;
  paragraphs: PageParagraphBox[];
}

export interface BookInfo {
  id: number;
  slug: string;
  title: string;
  title_native: string | null;
  author: string | null;
  language: string;
  total_pages: number | null;
  indexed_pages: number;
  indexed_chunks: number;
}
