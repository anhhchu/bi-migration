import { describe, expect, it } from 'vitest';
import { statusLabel, statusTone } from './status';

describe('workflow status presentation', () => {
  it('uses plain-language labels for workflow statuses', () => {
    expect(statusLabel('GROUPING_REVIEW_REQUIRED')).toBe('Needs approval');
    expect(statusLabel('MIGRATION_RUNNING')).toBe('Migrating');
    expect(statusLabel('SOME_NEW_STATE')).toBe('Some new state');
    expect(statusLabel(null)).toBe('Unknown');
  });

  it('maps statuses to a tone', () => {
    expect(statusTone('BLOCKED')).toBe('danger');
    expect(statusTone('FAILED_VALUE')).toBe('danger');
    expect(statusTone('ACTION_REQUIRED')).toBe('warning');
    expect(statusTone('GROUPING_REVIEW_REQUIRED')).toBe('warning');
    expect(statusTone('NO_PROGRESS')).toBe('warning');
    expect(statusTone('MIGRATION_RUNNING')).toBe('info');
    expect(statusTone('PASS_SEMANTIC_ONLY')).toBe('success');
    expect(statusTone('READY_FOR_PREFLIGHT')).toBe('success');
    expect(statusTone('SUPERSEDED')).toBe('neutral');
    expect(statusTone('MIGRATION_IN_PROGRESS')).toBe('info');
    expect(statusLabel('MIGRATION_IN_PROGRESS')).toBe('Migration in progress');
    expect(statusTone('READY_FOR_PARITY')).toBe('success');
    expect(statusTone(undefined)).toBe('neutral');
  });
});
