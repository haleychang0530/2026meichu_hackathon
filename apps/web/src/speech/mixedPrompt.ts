import normalizationGolden from '../../../../data/language/normalization-golden.json';
import type { SpeechUtterance } from './gateway';

type SpeechSegment = SpeechUtterance['segments'][number];

type GoldenEntry = {
  readonly hanji: string;
  readonly tailo: string;
  readonly poj: string;
  readonly zh_gloss: string;
  readonly status: string;
};

type GoldenMatch = {
  readonly entry: GoldenEntry;
  readonly pattern: string;
  readonly isHanji: boolean;
};

const DEFAULT_PROMPT = '目前沒有可播放的提示。';

// Single Hanji characters are intentionally excluded from general matching:
// characters such as 「我」、「你」 and 「去」 are valid in both Mandarin and
// Taiwanese contexts.  They are only safe to route as Taiwanese when the
// entire prompt is that reviewed vocabulary item.
const VERIFIED_TAIWANESE_MATCHES = (normalizationGolden.entries as readonly GoldenEntry[])
  .filter((entry) => entry.status === 'verified')
  .flatMap<GoldenMatch>((entry) => [
    { entry, pattern: entry.hanji, isHanji: true },
    { entry, pattern: entry.tailo, isHanji: false },
    { entry, pattern: entry.poj, isHanji: false },
  ])
  .filter((match) => match.pattern.length > 0)
  .sort((left, right) => right.pattern.length - left.pattern.length);

function chineseSegment(text: string): SpeechSegment {
  return {
    lang: 'zh-TW',
    hanji: text,
    tailo_citation: null,
    poj_citation: null,
    zh_gloss: text,
    source: 'generated',
    pronunciation_status: 'verified',
  };
}

function appendChineseText(segments: SpeechSegment[], text: string): void {
  // A punctuation-only tail such as 「。」 must not become a standalone SAPI
  // request: Windows SAPI can emit a zero-frame WAV for it.  Punctuation that
  // is attached to actual Chinese text stays in that Chinese segment.
  if (!/[\p{L}\p{N}]/u.test(text)) return;
  appendSegment(segments, chineseSegment(text));
}

function taiwaneseSegment(entry: GoldenEntry): SpeechSegment {
  return {
    lang: 'nan-TW',
    hanji: entry.hanji,
    tailo_citation: entry.tailo,
    poj_citation: entry.poj,
    zh_gloss: entry.zh_gloss,
    source: 'dictionary',
    pronunciation_status: 'verified',
  };
}

function appendSegment(segments: SpeechSegment[], next: SpeechSegment): void {
  const previous = segments.at(-1);
  if (!previous || previous.lang !== next.lang) {
    segments.push(next);
    return;
  }

  if (next.lang === 'nan-TW') {
    segments[segments.length - 1] = {
      ...previous,
      hanji: `${previous.hanji}${next.hanji}`,
      tailo_citation: [previous.tailo_citation, next.tailo_citation]
        .filter((value): value is string => Boolean(value))
        .join(' '),
      poj_citation: [previous.poj_citation, next.poj_citation]
        .filter((value): value is string => Boolean(value))
        .join(' '),
      zh_gloss: [previous.zh_gloss, next.zh_gloss]
        .filter((value): value is string => Boolean(value))
        .join('；'),
    };
    return;
  }

  segments[segments.length - 1] = {
    ...previous,
    hanji: `${previous.hanji}${next.hanji}`,
    zh_gloss: `${previous.zh_gloss || ''}${next.zh_gloss || ''}` || null,
  };
}

function findMatch(text: string, offset: number): GoldenMatch | undefined {
  return VERIFIED_TAIWANESE_MATCHES.find((match) => {
    // A one-character Hanji item is ambiguous in a Chinese sentence.  It is
    // safe only when the complete prompt is that reviewed vocabulary item.
    if (match.isHanji && match.pattern.length === 1 && text.length !== 1) return false;
    // Romanization is allowed in demonstration prompts, but a one-letter
    // citation must not match the middle of an unrelated Latin word.
    if (!match.isHanji) {
      if (match.pattern.length === 1 && text.trim() !== match.pattern) return false;
      const before = text[offset - 1] || '';
      const after = text[offset + match.pattern.length] || '';
      if (/[A-Za-z]/.test(before) || /[A-Za-z]/.test(after)) return false;
    }
    return text.startsWith(match.pattern, offset);
  });
}

/**
 * Split a display prompt into safe, reviewed Mandarin/Taiwanese speech spans.
 *
 * This is deliberately conservative.  Only the repository's verified golden
 * entries are sent to nan-TW/MMS; unmatched text remains zh-TW so an unknown
 * or ambiguous Hanji reading cannot be guessed by the Taiwanese model.
 */
export function splitMixedPrompt(prompt: string): SpeechSegment[] {
  const text = prompt.trim() || DEFAULT_PROMPT;
  const segments: SpeechSegment[] = [];
  let plainStart = 0;
  let offset = 0;

  while (offset < text.length) {
    const match = findMatch(text, offset);
    if (!match) {
      offset += 1;
      continue;
    }

    if (plainStart < offset) {
      appendChineseText(segments, text.slice(plainStart, offset));
    }
    appendSegment(segments, taiwaneseSegment(match.entry));
    offset += match.pattern.length;
    plainStart = offset;
  }

  if (plainStart < text.length) {
    appendChineseText(segments, text.slice(plainStart));
  }

  return segments.length ? segments : [chineseSegment(DEFAULT_PROMPT)];
}

export function promptToUtterance(prompt: string): SpeechUtterance {
  const segments = splitMixedPrompt(prompt);
  return {
    schema_version: '0.1.0',
    id: 'utt_student_prompt',
    segments,
    tts_provider: segments.some((segment) => segment.lang === 'nan-TW')
      ? 'mms-tts-nan'
      : 'windows',
    audio_url: null,
    audio_cache_key: null,
  };
}
