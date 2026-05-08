import { describe, expect, it, vi } from 'vitest';

import Slingshot from '../../src/entities/Slingshot.js';
import {
  resolveBootRoute,
  stripTransientLevelParamFromUrl
} from '../../src/systems/bootRoute.js';
import { PHYSICS_CONFIG } from '../../src/systems/physics.js';

vi.mock('phaser', () => ({
  default: {
    Scenes: {
      Events: {
        SHUTDOWN: 'shutdown'
      }
    },
    Math: {
      Clamp: (value, min, max) => Math.min(Math.max(value, min), max)
    }
  }
}));

describe('cross-flow mid-level cleanup regressions', () => {
  it('treats direct level boot URLs as transient so hard reloads leave gameplay', () => {
    expect(resolveBootRoute({
      search: '?level=2-04',
      env: { ANGRY_BIRD_DEV: true }
    })).toEqual({
      scene: 'Game',
      data: { level: '2-04' },
      transientLevelParam: true
    });

    expect(stripTransientLevelParamFromUrl('http://localhost:4100/?level=2-04')).toBe(
      'http://localhost:4100/'
    );
  });

  it('keeps level-select boot URLs reloadable after abandoning mid-level', () => {
    expect(resolveBootRoute({
      search: '?scene=LevelSelect&episode=2',
      env: { ANGRY_BIRD_DEV: true }
    })).toEqual({
      scene: 'LevelSelect',
      data: { episode: 2 },
      transientLevelParam: false
    });
  });

  it('resolves a bird that leaves through the top edge within the cleanup window', () => {
    const resolveFlyingBird = vi.fn();
    const slingshot = {
      dragging: false,
      scene: {
        isSlingshotPaused: () => false
      },
      flyingBird: {
        x: 240,
        y: -8,
        updateFlight: vi.fn(),
        getVelocity: () => ({ x: 0, y: -12, speed: 12 })
      },
      levelWidth: 1280,
      flightStartedAt: 100,
      outOfWorldAt: null,
      restStartedAt: null,
      resolveFlyingBird
    };

    Slingshot.prototype.update.call(slingshot, 1000);
    expect(resolveFlyingBird).not.toHaveBeenCalled();

    Slingshot.prototype.update.call(
      slingshot,
      1000 + PHYSICS_CONFIG.birdOffWorldCleanupMs + 1
    );

    expect(resolveFlyingBird).toHaveBeenCalledWith('off-world');
  });
});
