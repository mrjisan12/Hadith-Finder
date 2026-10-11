# Hadith Finder — frontend

Next.js 16 (App Router) · TypeScript · Tailwind CSS v4 · shadcn/ui (Base UI) · TanStack Query.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
npm run build && npm run lint
```

* `src/components/chat-app.tsx` — chat, SSE streaming (`src/lib/api.ts`)
* `src/components/answer-text.tsx` — answer with citation chips (only verified source ids render)
* `src/components/source-card.tsx` — original paragraph, printed/PDF page, page-break parts
* `src/components/page-viewer.tsx` — original scanned page, zoom, prev/next, paragraph highlight
* `src/lib/i18n.tsx` — Bangla / English UI strings

No secrets belong here; the backend holds every API key. See the root README for the full setup.
