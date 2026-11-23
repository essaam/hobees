const STORAGE_PREFIX = 'hobees.web-ui';

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    // Storage can throw in private-mode / sandboxed contexts.
    return null;
  }
}

export function readStored<T>(key: string, fallback: T): T {
  const storage = getStorage();
  if (!storage) return fallback;
  const raw = storage.getItem(`${STORAGE_PREFIX}:${key}`);
  if (raw == null) return fallback;
  try {
    const parsed = JSON.parse(raw) as T;
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeStored(key: string, value: unknown): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(`${STORAGE_PREFIX}:${key}`, JSON.stringify(value));
  } catch {
    // Ignore quota / private-mode failures; selection stays in memory.
  }
}
