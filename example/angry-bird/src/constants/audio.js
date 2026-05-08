export const BIRD_FLIGHT_SFX = Object.freeze({
  red: 'sfx-bird-red-cry',
  blues: 'sfx-bird-blues-flutter',
  chuck: 'sfx-bird-chuck-zip',
  matilda: 'sfx-bird-matilda-glide',
  bomb: 'sfx-bird-bomb-rumble',
  hal: 'sfx-bird-hal-boomerang-flight'
});

export const ABILITY_SFX = Object.freeze({
  blues: 'sfx-blues-split',
  chuck: 'sfx-chuck-burst',
  matilda: 'sfx-matilda-egg-drop',
  bomb: 'sfx-bomb-fuse-explode',
  hal: 'sfx-hal-boomerang'
});

export const SLINGSHOT_SFX = Object.freeze({
  pull: 'sfx-slingshot-pull',
  release: 'sfx-slingshot-release'
});

export const MATERIAL_IMPACT_SFX = Object.freeze({
  wood: 'sfx-wood-impact',
  glass: 'sfx-glass-impact',
  stone: 'sfx-stone-impact'
});

export const MATERIAL_BREAK_SFX = Object.freeze({
  wood: 'sfx-wood-break',
  glass: 'sfx-glass-break',
  stone: 'sfx-stone-break'
});

export const PHYSICS_SFX = Object.freeze({
  pigPop: 'sfx-pig-pop',
  tntExplosion: 'sfx-tnt-explosion'
});

export const END_STATE_SFX = Object.freeze({
  cleared: 'sfx-level-win-stinger',
  failed: 'sfx-level-fail-jingle'
});

function audioAsset(key, metadata = {}) {
  return {
    type: 'audio',
    key,
    url: `assets/audio/${key}.ogg`,
    ...metadata
  };
}

export const BIRD_FLIGHT_AUDIO_ASSETS = Object.entries(BIRD_FLIGHT_SFX).map(([birdType, key]) => audioAsset(key, {
  birdType
}));

export const ABILITY_AUDIO_ASSETS = Object.entries(ABILITY_SFX).map(([birdType, key]) => audioAsset(key, {
  birdType,
  ability: true
}));

export const SLINGSHOT_AUDIO_ASSETS = Object.entries(SLINGSHOT_SFX).map(([action, key]) => audioAsset(key, {
  action
}));

export const MATERIAL_AUDIO_ASSETS = Object.keys(MATERIAL_IMPACT_SFX).flatMap((material) => [
  audioAsset(MATERIAL_IMPACT_SFX[material], {
    material,
    event: 'impact'
  }),
  audioAsset(MATERIAL_BREAK_SFX[material], {
    material,
    event: 'break'
  })
]);

export const PHYSICS_AUDIO_ASSETS = Object.entries(PHYSICS_SFX).map(([event, key]) => audioAsset(key, {
  event
}));

export const END_STATE_AUDIO_ASSETS = Object.entries(END_STATE_SFX).map(([outcome, key]) => audioAsset(key, {
  outcome
}));

export const GAMEPLAY_AUDIO_ASSETS = [
  ...BIRD_FLIGHT_AUDIO_ASSETS,
  ...ABILITY_AUDIO_ASSETS,
  ...SLINGSHOT_AUDIO_ASSETS,
  ...MATERIAL_AUDIO_ASSETS,
  ...PHYSICS_AUDIO_ASSETS,
  ...END_STATE_AUDIO_ASSETS
];

export const GAMEPLAY_SFX_VOLUME = 0.72;
