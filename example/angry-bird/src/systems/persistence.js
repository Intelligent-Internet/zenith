import { recordLevelClear as recordScoringLevelClear } from './scoring.js';

export const SAVE_KEY = 'angry-bird-save-v1';
export const SAVE_SCHEMA_VERSION = 1;

const SAVE_WARNING = 'Angry Birds save unavailable; using in-memory save.';

function warnOnceFactory(warn) {
  let warned = false;

  return (error) => {
    if (warned || typeof warn !== 'function') {
      return;
    }

    warned = true;
    warn(SAVE_WARNING, error);
  };
}

export function createFreshSave(mute = false) {
  return {
    schemaVersion: SAVE_SCHEMA_VERSION,
    cleared: [],
    bestScore: {},
    bestStars: {},
    mute: Boolean(mute)
  };
}

function normalizeRecord(record, normalizeValue) {
  return Object.entries(record ?? {}).reduce((normalized, [levelId, value]) => {
    if (typeof levelId !== 'string' || levelId.length === 0) {
      return normalized;
    }

    normalized[levelId] = normalizeValue(value);
    return normalized;
  }, {});
}

function normalizeScore(score) {
  return Math.max(0, Math.floor(Number(score) || 0));
}

function normalizeStars(stars) {
  return Math.max(0, Math.min(3, Math.floor(Number(stars) || 0)));
}

function normalizeCleared(cleared) {
  if (!Array.isArray(cleared)) {
    return [];
  }

  return [...new Set(cleared.filter((levelId) => (
    typeof levelId === 'string' && levelId.length > 0
  )))];
}

export function normalizeSave(save = {}) {
  return {
    schemaVersion: SAVE_SCHEMA_VERSION,
    cleared: normalizeCleared(save.cleared),
    bestScore: normalizeRecord(save.bestScore, normalizeScore),
    bestStars: normalizeRecord(save.bestStars, normalizeStars),
    mute: Boolean(save.mute)
  };
}

export function cloneSave(save) {
  return normalizeSave(save);
}

function resolveStorage(providedStorage, warnOnce) {
  if (providedStorage !== undefined) {
    return providedStorage;
  }

  try {
    return globalThis.localStorage ?? null;
  } catch (error) {
    warnOnce(error);
    return null;
  }
}

function parseStoredSave(raw, warnOnce) {
  if (raw == null) {
    return createFreshSave();
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    warnOnce(error);
    return createFreshSave();
  }

  if (!parsed || parsed.schemaVersion !== SAVE_SCHEMA_VERSION) {
    warnOnce(new Error('Unsupported save schema version'));
    return createFreshSave();
  }

  return normalizeSave(parsed);
}

export function createPersistence({
  storage,
  warn = console.warn
} = {}) {
  const warnOnce = warnOnceFactory(warn);
  const storageTarget = resolveStorage(storage, warnOnce);
  let storageAvailable = Boolean(storageTarget);
  let loaded = false;
  let memoryRaw = null;
  let currentSave = createFreshSave();

  function readRaw() {
    if (!storageAvailable || !storageTarget) {
      return memoryRaw;
    }

    try {
      return storageTarget.getItem(SAVE_KEY);
    } catch (error) {
      storageAvailable = false;
      warnOnce(error);
      return memoryRaw;
    }
  }

  function writeRaw(raw) {
    memoryRaw = raw;
    if (!storageAvailable || !storageTarget) {
      return;
    }

    try {
      storageTarget.setItem(SAVE_KEY, raw);
    } catch (error) {
      storageAvailable = false;
      warnOnce(error);
    }
  }

  function loadSave() {
    currentSave = parseStoredSave(readRaw(), warnOnce);
    loaded = true;
    return cloneSave(currentSave);
  }

  function ensureLoaded() {
    if (!loaded) {
      loadSave();
    }
  }

  function replaceSave(nextSave) {
    currentSave = normalizeSave(nextSave);
    loaded = true;
    writeRaw(JSON.stringify(currentSave));
    return cloneSave(currentSave);
  }

  function updateSave(updater) {
    ensureLoaded();
    return replaceSave(updater(cloneSave(currentSave)));
  }

  return {
    loadSave,
    getSave() {
      ensureLoaded();
      return cloneSave(currentSave);
    },
    replaceSave,
    updateSave,
    recordLevelClear(clearData) {
      return updateSave((save) => recordScoringLevelClear(save, clearData));
    },
    setMute(muted) {
      return updateSave((save) => ({
        ...save,
        mute: Boolean(muted)
      }));
    }
  };
}

let defaultPersistence;

export function getPersistence() {
  if (!defaultPersistence) {
    defaultPersistence = createPersistence();
  }

  return defaultPersistence;
}

export function resetPersistenceForTests() {
  defaultPersistence = null;
}
