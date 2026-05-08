export const AUDIO_RESUME_EVENTS = Object.freeze([
  'pointerdown',
  'touchstart',
  'keydown'
]);

export function resumeAudioContext(soundManager) {
  const context = soundManager?.context ?? globalThis.Phaser?.Sound?.context;

  if (soundManager?.locked && typeof soundManager.unlock === 'function') {
    try {
      soundManager.unlock();
    } catch {
      return false;
    }
  }

  if (context?.state !== 'suspended' || typeof context.resume !== 'function') {
    return false;
  }

  try {
    const resumeResult = context.resume();
    resumeResult?.catch?.(() => {});
    return resumeResult;
  } catch {
    return false;
  }
}

export function installDeferredAudioResume({
  target = globalThis.window ?? globalThis.document,
  getSoundManager,
  soundManager,
  events = AUDIO_RESUME_EVENTS
} = {}) {
  if (
    !target
    || typeof target.addEventListener !== 'function'
    || typeof target.removeEventListener !== 'function'
  ) {
    return () => {};
  }

  let installed = true;
  const options = { passive: true };

  function cleanup() {
    if (!installed) {
      return;
    }

    installed = false;
    events.forEach((eventName) => {
      target.removeEventListener(eventName, handleGesture, options);
    });
  }

  function handleGesture() {
    resumeAudioContext(getSoundManager?.() ?? soundManager);
    cleanup();
  }

  events.forEach((eventName) => {
    target.addEventListener(eventName, handleGesture, options);
  });

  return cleanup;
}
