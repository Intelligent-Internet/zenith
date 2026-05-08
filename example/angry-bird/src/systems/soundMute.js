export function setGlobalSoundMute(soundManager, muted) {
  if (!soundManager) {
    return false;
  }

  const nextMuted = Boolean(muted);

  if (typeof soundManager.setMute === 'function') {
    soundManager.setMute(nextMuted);
  } else {
    soundManager.mute = nextMuted;
  }

  const expectedGain = nextMuted ? 0 : 1;
  const gain = soundManager.masterMuteNode?.gain;

  if (gain && soundManager.mute !== nextMuted) {
    const currentTime = Number(soundManager.context?.currentTime) || 0;

    gain.cancelScheduledValues?.(currentTime);
    if (typeof gain.setValueAtTime === 'function') {
      gain.setValueAtTime(expectedGain, currentTime);
    }
    if (gain.value !== expectedGain) {
      gain.value = expectedGain;
    }
  }

  return true;
}
