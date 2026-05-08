import { describe, expect, it, vi } from 'vitest';

import {
  AUDIO_RESUME_EVENTS,
  installDeferredAudioResume,
  resumeAudioContext
} from '../../src/systems/audioUnlock.js';

function createEventTarget() {
  const listeners = new Map();

  return {
    addEventListener: vi.fn((eventName, handler) => {
      listeners.set(eventName, handler);
    }),
    removeEventListener: vi.fn((eventName, handler) => {
      if (listeners.get(eventName) === handler) {
        listeners.delete(eventName);
      }
    }),
    dispatch(eventName) {
      listeners.get(eventName)?.({ type: eventName });
    }
  };
}

describe('deferred audio resume', () => {
  it('waits for the first user gesture before resuming Phaser audio', () => {
    const target = createEventTarget();
    const soundManager = {
      locked: true,
      unlock: vi.fn(),
      context: {
        state: 'suspended',
        resume: vi.fn(() => Promise.resolve())
      }
    };

    installDeferredAudioResume({
      target,
      soundManager,
      events: ['pointerdown', 'keydown']
    });

    expect(target.addEventListener).toHaveBeenCalledTimes(2);
    expect(soundManager.context.resume).not.toHaveBeenCalled();

    target.dispatch('pointerdown');
    target.dispatch('keydown');

    expect(soundManager.unlock).toHaveBeenCalledTimes(1);
    expect(soundManager.context.resume).toHaveBeenCalledTimes(1);
    expect(target.removeEventListener).toHaveBeenCalledTimes(2);
  });

  it('uses pointer, touch, and keyboard gestures by default', () => {
    expect(AUDIO_RESUME_EVENTS).toEqual(['pointerdown', 'touchstart', 'keydown']);
  });

  it('does not resume an already running audio context', () => {
    const soundManager = {
      context: {
        state: 'running',
        resume: vi.fn()
      }
    };

    expect(resumeAudioContext(soundManager)).toBe(false);
    expect(soundManager.context.resume).not.toHaveBeenCalled();
  });
});
