import { useEffect, useState } from 'react';

const STORAGE_PREFIX = 'bi-migration-review:';

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function browserStorage(): StorageLike | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readPersistedValue<T>(
  key: string,
  fallback: T,
  isValid: (value: unknown) => value is T,
  storage: StorageLike | null = browserStorage()
): T {
  try {
    const raw = storage?.getItem(STORAGE_PREFIX + key);
    if (raw === null || raw === undefined) return fallback;
    const parsed: unknown = JSON.parse(raw);
    return isValid(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function writePersistedValue<T>(key: string, value: T, storage: StorageLike | null = browserStorage()): void {
  try {
    if (value === '' || value === null || value === undefined) {
      storage?.removeItem(STORAGE_PREFIX + key);
    } else {
      storage?.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
    }
  } catch {
    // Storage can be unavailable (private mode, quota); persistence is best effort.
  }
}

export const isString = (value: unknown): value is string => typeof value === 'string';

export function isOneOf<T extends string>(options: readonly T[]) {
  return (value: unknown): value is T => typeof value === 'string' && (options as readonly string[]).includes(value);
}

/** useState that survives reloads by mirroring the value into localStorage. */
export function usePersistentState<T>(key: string, fallback: T, isValid: (value: unknown) => value is T) {
  const [value, setValue] = useState<T>(() => readPersistedValue(key, fallback, isValid));
  useEffect(() => {
    writePersistedValue(key, value);
  }, [key, value]);
  return [value, setValue] as const;
}
