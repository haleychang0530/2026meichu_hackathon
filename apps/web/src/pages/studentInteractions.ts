import type { TeachingPhase } from '../types/viewModels';

export type StudentInteractionGroup = 'teaching' | 'practice' | 'hint' | 'complete';

/**
 * Keep the student controls aligned with the teaching phase instead of
 * exposing every Core control at every point in the lesson.
 */
export function getStudentInteractionGroup(phase: TeachingPhase): StudentInteractionGroup {
  if (phase === 'complete') return 'complete';
  if (phase === 'hint') return 'hint';
  if (phase === 'read_aloud' || phase === 'comprehension' || phase === 'review') return 'practice';
  return 'teaching';
}

export function canAnswerInStudentInteractionGroup(group: StudentInteractionGroup | null): boolean {
  return group === 'practice' || group === 'hint';
}

export function showsNextInStudentInteractionGroup(group: StudentInteractionGroup | null): boolean {
  return group === 'teaching' || group === 'practice';
}
