import { describe, expect, it } from 'vitest';
import {
  canAnswerInStudentInteractionGroup,
  getStudentInteractionGroup,
  showsNextInStudentInteractionGroup,
} from './studentInteractions';

describe('student interaction groups', () => {
  it('keeps introduction and demonstration in the teaching group', () => {
    expect(getStudentInteractionGroup('introduction')).toBe('teaching');
    expect(getStudentInteractionGroup('demonstration')).toBe('teaching');
    expect(canAnswerInStudentInteractionGroup(getStudentInteractionGroup('introduction'))).toBe(false);
    expect(showsNextInStudentInteractionGroup('teaching')).toBe(true);
  });

  it('makes practice and review answerable', () => {
    expect(getStudentInteractionGroup('read_aloud')).toBe('practice');
    expect(getStudentInteractionGroup('comprehension')).toBe('practice');
    expect(getStudentInteractionGroup('review')).toBe('practice');
    expect(canAnswerInStudentInteractionGroup('practice')).toBe(true);
    expect(showsNextInStudentInteractionGroup('practice')).toBe(true);
  });

  it('keeps hint as a continuation into the answer flow', () => {
    expect(getStudentInteractionGroup('hint')).toBe('hint');
    expect(canAnswerInStudentInteractionGroup('hint')).toBe(true);
    expect(showsNextInStudentInteractionGroup('hint')).toBe(false);
  });

  it('does not expose answer controls after completion', () => {
    expect(getStudentInteractionGroup('complete')).toBe('complete');
    expect(canAnswerInStudentInteractionGroup('complete')).toBe(false);
    expect(canAnswerInStudentInteractionGroup(null)).toBe(false);
    expect(showsNextInStudentInteractionGroup('complete')).toBe(false);
    expect(showsNextInStudentInteractionGroup(null)).toBe(false);
  });
});
