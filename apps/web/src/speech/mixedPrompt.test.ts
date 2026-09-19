import { describe, expect, it } from 'vitest';
import { promptToUtterance, splitMixedPrompt } from './mixedPrompt';

describe('mixed student prompts', () => {
  it('keeps Chinese scaffolding and routes a reviewed Taiwanese sentence to nan-TW', () => {
    const segments = splitMixedPrompt('請跟讀這句：阿媽欲去市場買菜。');

    expect(segments.map(({ lang, hanji }) => ({ lang, hanji }))).toEqual([
      { lang: 'zh-TW', hanji: '請跟讀這句：' },
      { lang: 'nan-TW', hanji: '阿媽欲去市場買菜' },
    ]);
    expect(segments[1]).toMatchObject({
      tailo_citation: 'A-má beh khì tshī-tiûnn bé tshài.',
      poj_citation: 'a-má beh khì chhī-tiûnn bé chhài',
      pronunciation_status: 'verified',
    });
  });

  it('splits a short mixed prompt into Chinese and Taiwanese spans', () => {
    const utterance = promptToUtterance('請跟我說：食飯');

    expect(utterance.tts_provider).toBe('mms-tts-nan');
    expect(utterance.segments.map(({ lang, hanji }) => ({ lang, hanji }))).toEqual([
      { lang: 'zh-TW', hanji: '請跟我說：' },
      { lang: 'nan-TW', hanji: '食飯' },
    ]);
  });

  it('recognizes the canonical romanization used by demonstration prompts', () => {
    const utterance = promptToUtterance('先聽示範：「A-má」，意思是「祖母」。請準備跟讀。');

    expect(utterance.segments.map(({ lang, hanji }) => ({ lang, hanji }))).toEqual([
      { lang: 'zh-TW', hanji: '先聽示範：「' },
      { lang: 'nan-TW', hanji: '阿媽' },
      { lang: 'zh-TW', hanji: '」，意思是「祖母」。請準備跟讀。' },
    ]);
  });

  it('leaves an unknown or ambiguous phrase in Chinese', () => {
    const utterance = promptToUtterance('請說：行');

    expect(utterance.tts_provider).toBe('windows');
    expect(utterance.segments).toHaveLength(1);
    expect(utterance.segments[0]).toMatchObject({ lang: 'zh-TW', hanji: '請說：行' });
  });

  it('routes a single verified one-character vocabulary item only when explicit', () => {
    const utterance = promptToUtterance('我');

    expect(utterance.segments).toHaveLength(1);
    expect(utterance.segments[0]).toMatchObject({ lang: 'nan-TW', hanji: '我' });
  });
});
