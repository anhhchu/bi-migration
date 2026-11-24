import { describe, expect, it } from 'vitest';
import { isOneOf, isString, readPersistedValue, writePersistedValue } from './persistent-state';

function memoryStorage() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}

describe('persistent state', () => {
  it('round-trips a saved Volume path', () => {
    const storage = memoryStorage();
    writePersistedValue('datasource-path', '/Volumes/c/s/v/project/datasources', storage);
    expect(readPersistedValue('datasource-path', '', isString, storage)).toBe('/Volumes/c/s/v/project/datasources');
  });

  it('clears the key when the value is emptied', () => {
    const storage = memoryStorage();
    writePersistedValue('mapping-path', '/Volumes/c/s/v/m', storage);
    writePersistedValue('mapping-path', '', storage);
    expect(storage.items.size).toBe(0);
  });

  it('falls back when stored data is invalid or corrupt', () => {
    const storage = memoryStorage();
    const isMode = isOneOf(['semantic_model', 'dashboard'] as const);
    storage.setItem('bi-migration-review:migration-mode', JSON.stringify('unknown'));
    expect(readPersistedValue('migration-mode', 'semantic_model', isMode, storage)).toBe('semantic_model');
    storage.setItem('bi-migration-review:migration-mode', '{not json');
    expect(readPersistedValue('migration-mode', 'semantic_model', isMode, storage)).toBe('semantic_model');
  });

  it('falls back when storage is unavailable', () => {
    expect(readPersistedValue('datasource-path', 'fallback', isString, null)).toBe('fallback');
  });
});
