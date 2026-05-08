import { describe, expect, it, vi } from 'vitest';

import { computeUnlocks } from '../../src/systems/progression.js';
import {
  SAVE_KEY,
  createFreshSave,
  createPersistence
} from '../../src/systems/persistence.js';

function createMemoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));

  return {
    getItem: vi.fn((key) => (data.has(key) ? data.get(key) : null)),
    setItem: vi.fn((key, value) => {
      data.set(key, value);
    }),
    removeItem: vi.fn((key) => {
      data.delete(key);
    }),
    peek(key) {
      return data.get(key);
    }
  };
}

describe('persistence schema loading', () => {
  it('loads a fresh versioned save when storage is empty', () => {
    const warn = vi.fn();
    const persistence = createPersistence({
      storage: createMemoryStorage(),
      warn
    });

    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(warn).not.toHaveBeenCalled();
  });

  it('loads valid save JSON from angry-bird-save-v1', () => {
    const storedSave = {
      schemaVersion: 1,
      cleared: ['1-01'],
      bestScore: { '1-01': 33000 },
      bestStars: { '1-01': 3 },
      mute: true
    };
    const storage = createMemoryStorage({
      [SAVE_KEY]: JSON.stringify(storedSave)
    });

    const persistence = createPersistence({ storage, warn: vi.fn() });

    expect(persistence.loadSave()).toEqual(storedSave);
    expect(storage.getItem).toHaveBeenCalledWith(SAVE_KEY);
  });

  it('falls back to a fresh save and warns once for malformed JSON', () => {
    const warn = vi.fn();
    const persistence = createPersistence({
      storage: createMemoryStorage({ [SAVE_KEY]: '{not-json' }),
      warn
    });

    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('falls back to a fresh save and warns once for future schema versions', () => {
    const warn = vi.fn();
    const persistence = createPersistence({
      storage: createMemoryStorage({
        [SAVE_KEY]: JSON.stringify({
          schemaVersion: 2,
          cleared: ['1-01'],
          bestScore: { '1-01': 33000 },
          bestStars: { '1-01': 3 },
          mute: true
        })
      }),
      warn
    });

    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(warn).toHaveBeenCalledTimes(1);
  });
});

describe('persistence writes and fallback behavior', () => {
  it('persists mute changes as a full save blob', () => {
    const storage = createMemoryStorage();
    const persistence = createPersistence({ storage, warn: vi.fn() });

    expect(persistence.setMute(true)).toMatchObject({ mute: true });
    expect(JSON.parse(storage.peek(SAVE_KEY))).toEqual({
      schemaVersion: 1,
      cleared: [],
      bestScore: {},
      bestStars: {},
      mute: true
    });
  });

  it('keeps an in-memory save and warns once when writes throw', () => {
    const warn = vi.fn();
    const storage = createMemoryStorage();
    storage.setItem.mockImplementation(() => {
      throw new Error('quota');
    });
    const persistence = createPersistence({ storage, warn });

    const cleared = persistence.recordLevelClear({
      levelId: '1-01',
      score: 33000,
      stars: 3
    });
    const muted = persistence.setMute(true);

    expect(cleared.bestScore['1-01']).toBe(33000);
    expect(muted).toMatchObject({
      cleared: ['1-01'],
      bestScore: { '1-01': 33000 },
      bestStars: { '1-01': 3 },
      mute: true
    });
    expect(persistence.loadSave()).toEqual(muted);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('keeps gameplay state in memory when localStorage reads throw', () => {
    const warn = vi.fn();
    const storage = createMemoryStorage();
    storage.getItem.mockImplementation(() => {
      throw new Error('private browsing');
    });
    const persistence = createPersistence({ storage, warn });

    expect(persistence.loadSave()).toEqual(createFreshSave());
    expect(persistence.recordLevelClear({
      levelId: '1-01',
      score: 25000,
      stars: 1
    }).cleared).toEqual(['1-01']);
    expect(warn).toHaveBeenCalledTimes(1);
  });
});

describe('progression unlocks from persisted cleared set', () => {
  it('computes level unlock state from cleared ids after a save round trip', () => {
    const storage = createMemoryStorage();
    const persistence = createPersistence({ storage, warn: vi.fn() });
    const save = persistence.recordLevelClear({
      levelId: '1-01',
      score: 33000,
      stars: 3
    });

    const reloaded = createPersistence({ storage, warn: vi.fn() }).loadSave();

    expect(reloaded).toEqual(save);
    expect(computeUnlocks(reloaded, { env: {} }).levels['1-02']).toBe(true);
    expect(computeUnlocks(reloaded, { env: {} }).levels['1-03']).toBe(false);
  });

  it('unlocks everything when ANGRY_BIRD_DEV is enabled without mutating cleared', () => {
    const save = createFreshSave();
    const unlocks = computeUnlocks(save, {
      env: { ANGRY_BIRD_DEV: '1' }
    });

    expect(Object.values(unlocks.episodes).every(Boolean)).toBe(true);
    expect(Object.values(unlocks.levels).every(Boolean)).toBe(true);
    expect(save.cleared).toEqual([]);
  });
});
