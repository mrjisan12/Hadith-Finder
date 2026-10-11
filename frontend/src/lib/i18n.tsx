"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";

export type Lang = "bn" | "en";

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
export const toBanglaDigits = (v: string | number) => String(v).replace(/[0-9]/g, (d) => BN_DIGITS[Number(d)]);

const strings = {
  bn: {
    appName: "হাদীস ফাইন্ডার",
    tagline: "ফাযায়েলে আমল থেকে উৎসসহ উত্তর — প্রতিটি উত্তরের মূল অনুচ্ছেদ ও পৃষ্ঠা যাচাই করুন",
    placeholder: "কিতাবের কোনো বিষয়ে প্রশ্ন করুন…",
    send: "পাঠান",
    stop: "থামান",
    examplesTitle: "উদাহরণ প্রশ্ন",
    examples: [
      "সদকার ফজিলত সম্পর্কে কী বলা হয়েছে?",
      "কুরআন তেলাওয়াতের ফজিলত কী?",
      "জামাতে নামাজ পড়ার গুরুত্ব কী?",
      "কিয়ামতের দিন কোন তিন ব্যক্তি ভয় পাবে না?",
    ],
    stage: {
      understanding: "প্রশ্ন বোঝা হচ্ছে…",
      retrieving: "কিতাবে খোঁজা হচ্ছে…",
      generating: "উত্তর লেখা হচ্ছে…",
    },
    answer: "উত্তর",
    sources: "মূল উৎস",
    relatedSources: "সম্পর্কিত অন্যান্য অংশ (উত্তরে উদ্ধৃত নয়)",
    insufficient: "পর্যাপ্ত প্রমাণ নেই",
    printedPage: "মুদ্রিত পৃষ্ঠা",
    pdfPage: "PDF পৃষ্ঠা",
    viewOriginal: "মূল পৃষ্ঠা দেখুন",
    originalPassage: "মূল অনুচ্ছেদ",
    continuesOn: "পরের পৃষ্ঠায় চলমান",
    continuedFrom: "আগের পৃষ্ঠা থেকে",
    verified: "ডাটাবেস থেকে হুবহু মূল পাঠ",
    verifiedHelp:
      "এই লেখা স্ক্যান করা কিতাবের OCR থেকে সংরক্ষিত মূল পাঠ — AI এটি লেখেনি। নিশ্চিত হতে মূল পৃষ্ঠার ছবি দেখুন।",
    copy: "কপি",
    copied: "কপি হয়েছে",
    pageUnknown: "অজানা",
    pageInferred: "পাশের পৃষ্ঠা থেকে নির্ণীত",
    pageManual: "হাতে সংশোধিত",
    hadith: "হাদীস",
    error: "দুঃখিত, একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।",
    rateLimited: "অনেক বেশি অনুরোধ। একটু পরে আবার চেষ্টা করুন।",
    zoomIn: "বড় করুন",
    zoomOut: "ছোট করুন",
    fit: "মানানসই",
    highlight: "অনুচ্ছেদ চিহ্নিত",
    prevPage: "আগের পৃষ্ঠা",
    nextPage: "পরের পৃষ্ঠা",
    openImage: "ছবি নতুন ট্যাবে",
    scanNote: "মূল স্ক্যান করা পৃষ্ঠা — উৎসের চূড়ান্ত প্রমাণ",
    needsReview: "এই পৃষ্ঠার নম্বর যাচাই প্রয়োজন",
    newChat: "নতুন আলোচনা",
    debug: "রিট্রিভাল ডিবাগ",
    disclaimer:
      "AI উত্তর সংক্ষিপ্ত সারাংশ মাত্র; মূল অনুচ্ছেদ ও স্ক্যান করা পৃষ্ঠাই চূড়ান্ত উৎস। শরয়ী মাসআলার জন্য আলেমের পরামর্শ নিন।",
  },
  en: {
    appName: "Hadith Finder",
    tagline: "Source-grounded answers from Fazail-e-Amal — verify the original paragraph and page of every answer",
    placeholder: "Ask about a topic in the book…",
    send: "Send",
    stop: "Stop",
    examplesTitle: "Example questions",
    examples: [
      "সদকার ফজিলত সম্পর্কে কী বলা হয়েছে?",
      "What is the virtue of reciting the Qur'an?",
      "Why is praying in congregation important?",
      "Which three people will not fear on the Day of Judgement?",
    ],
    stage: {
      understanding: "Understanding the question…",
      retrieving: "Searching the book…",
      generating: "Writing the answer…",
    },
    answer: "Answer",
    sources: "Original sources",
    relatedSources: "Other related passages (not cited in the answer)",
    insufficient: "Not enough evidence",
    printedPage: "Printed page",
    pdfPage: "PDF page",
    viewOriginal: "View original page",
    originalPassage: "Original passage",
    continuesOn: "continues on the next page",
    continuedFrom: "from the previous page",
    verified: "Exact original text from the database",
    verifiedHelp:
      "This text is the stored OCR of the scanned book - it was not written by the AI. Open the original page image to verify it.",
    copy: "Copy",
    copied: "Copied",
    pageUnknown: "unknown",
    pageInferred: "inferred from neighbouring pages",
    pageManual: "manually corrected",
    hadith: "Hadith",
    error: "Sorry, something went wrong. Please try again.",
    rateLimited: "Too many requests. Please wait a moment and try again.",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    fit: "Fit",
    highlight: "Highlight passage",
    prevPage: "Previous page",
    nextPage: "Next page",
    openImage: "Open image",
    scanNote: "Original scanned page — the authoritative source",
    needsReview: "The page number of this page needs review",
    newChat: "New chat",
    debug: "Retrieval debug",
    disclaimer:
      "The AI answer is only a short summary; the original passage and scanned page are the authoritative source. Consult a scholar for religious rulings.",
  },
};

export type Strings = (typeof strings)["bn"];

const I18nContext = createContext<{ lang: Lang; t: Strings; setLang: (l: Lang) => void; num: (n: string | number) => string }>({
  lang: "bn",
  t: strings.bn,
  setLang: () => {},
  num: (n) => toBanglaDigits(n),
});

// The chosen UI language is a per-viewer convenience kept in localStorage (read via an
// external store so server render = "bn" and the client switches without a hydration mismatch).
const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};
let memoryLang: Lang | null = null; // fallback when storage is blocked
const readLang = (): Lang => {
  if (memoryLang) return memoryLang;
  try {
    return window.localStorage.getItem("hf-lang") === "en" ? "en" : "bn";
  } catch {
    return "bn";
  }
};

export function I18nProvider({ children }: { children: ReactNode }) {
  const lang = useSyncExternalStore(subscribe, readLang, () => "bn" as Lang);
  const setLang = (l: Lang) => {
    memoryLang = l;
    try {
      window.localStorage.setItem("hf-lang", l);
    } catch {
      /* storage unavailable: language resets on reload */
    }
    listeners.forEach((cb) => cb());
  };
  const num = (n: string | number) => (lang === "bn" ? toBanglaDigits(n) : String(n));
  return <I18nContext.Provider value={{ lang, t: strings[lang], setLang, num }}>{children}</I18nContext.Provider>;
}

export const useI18n = () => useContext(I18nContext);
