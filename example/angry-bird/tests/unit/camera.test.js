import { describe, expect, it, vi } from 'vitest';

vi.mock('phaser', () => ({
  default: {
    Scene: class Scene {
      constructor(key) {
        this.scene = { key };
      }
    },
    Scenes: {
      Events: {
        SHUTDOWN: 'shutdown'
      }
    }
  }
}));

import Game from '../../src/scenes/Game.js';

describe('wide-level camera behavior', () => {
  it('follows a launched bird and recenters on the slingshot after resolve', () => {
    const scene = new Game();
    const camera = {
      startFollow: vi.fn(),
      stopFollow: vi.fn(),
      centerOn: vi.fn()
    };
    const bird = {
      getDebugState: vi.fn(() => ({ type: 'matilda', canDrag: false })),
      getFlightAudioEvent: vi.fn(() => null)
    };

    scene.levelConfig = {
      id: '3-05',
      cameraWide: true,
      anchor: { x: 230, y: 430 },
      levelWidth: 1920
    };
    scene.cameras = { main: camera };
    scene.birdsLaunched = 0;
    scene.time = { now: 1400 };
    scene.physicsSystem = { markLaunched: vi.fn() };
    scene.recordAudioEvent = vi.fn();
    scene.refreshDebug = vi.fn();
    scene.evaluateLevelEnd = vi.fn();

    scene.handleBirdLaunched(bird, { type: 'matilda' });

    expect(camera.startFollow).toHaveBeenCalledWith(bird, true, 0.08, 0.08);

    scene.handleBirdResolved('stuck-bird-recovery');

    expect(camera.stopFollow).toHaveBeenCalled();
    expect(camera.centerOn).toHaveBeenCalledWith(230, 360);
  });
});
