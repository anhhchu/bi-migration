export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const LABELS: Record<string, string> = {
  GROUPING_REVIEW_REQUIRED: 'Needs approval',
  AWAITING_APPROVAL: 'Needs approval',
  MIGRATION_RUNNING: 'Migrating',
  IN_PROGRESS: 'In progress',
  RUNNING: 'Running',
  ACTION_REQUIRED: 'Action required',
  NEEDS_REVIEW: 'Needs review',
  READY_FOR_PREFLIGHT: 'Ready to migrate',
  PASS_SEMANTIC_ONLY: 'Passed (semantic only)',
  FAILED_SEMANTICS: 'Failed semantics',
  FAILED_VALUE: 'Query failed',
  BLOCKED_UNRESOLVED_MAPPING: 'Missing mapping',
  EXCLUDED_UNSUPPORTED: 'Excluded',
  NO_PROGRESS: 'No progress',
  BLOCKED_EVIDENCE: 'Blocked: evidence',
  UNRESOLVABLE_AUTOMATICALLY: 'Needs manual fix',
  REGRESSION_REJECTED: 'Regression rejected',
  EXHAUSTED: 'Attempts exhausted',
  SUPERSEDED: 'Superseded',
  READY_FOR_PARITY: 'Ready for parity',
  CHECKS_PENDING: 'Checks pending',
  BLOCKING: 'Blocking',
  MIGRATION_IN_PROGRESS: 'Migration in progress',
  NO_RESULT: 'No result',
};

const TONES: Array<[RegExp, StatusTone]> = [
  [/^(SUPERSEDED|EXCLUDED|UNKNOWN|NO_RESULT)/, 'neutral'],
  [/(FAIL|BLOCK|ERROR|REJECT|EXHAUST|UNRESOLV)/, 'danger'],
  [/^NO_PROGRESS$/, 'warning'],
  [/(RUNNING|PROGRESS|PENDING|SUBMITTED)$/, 'info'],
  [/(REVIEW|APPROVAL|ACTION|PARTIAL|NO_PROGRESS|WARN)/, 'warning'],
  [/^CHECKS_PENDING$/, 'info'],
  [/^(PASS|READY|COMPLETE|SUCCESS|APPROVED)/, 'success'],
];

export function statusLabel(status: string | null | undefined): string {
  if (!status) return 'Unknown';
  const key = status.toUpperCase();
  if (LABELS[key]) return LABELS[key];
  const words = key.toLowerCase().split('_').filter(Boolean).join(' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function statusTone(status: string | null | undefined): StatusTone {
  const key = (status ?? 'UNKNOWN').toUpperCase();
  return TONES.find(([pattern]) => pattern.test(key))?.[1] ?? 'neutral';
}
