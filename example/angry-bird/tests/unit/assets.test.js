import { describe, expect, it } from 'vitest';

import {
  BIRD_SPRITE_FRAME_HEIGHT,
  BIRD_SPRITE_FRAME_WIDTH,
  BIRD_SPRITE_FRAMES,
  BIRD_SPRITE_TYPES,
  EPISODE_BACKGROUND_IDS,
  EPISODE_HERO_IDS,
  EPISODE_HERO_TITLES,
  getEpisodeBackgroundKey,
  getEpisodeHeroKey,
  MATERIAL_PARTICLE_TYPES,
  MATERIAL_SPRITE_TYPES,
  PIG_SPRITE_TYPES,
  PLACEHOLDER_ASSETS
} from '../../src/constants/assets.js';
import {
  ABILITY_AUDIO_ASSETS,
  ABILITY_SFX,
  BIRD_FLIGHT_AUDIO_ASSETS,
  BIRD_FLIGHT_SFX,
  END_STATE_AUDIO_ASSETS,
  END_STATE_SFX,
  GAMEPLAY_AUDIO_ASSETS,
  MATERIAL_AUDIO_ASSETS,
  MATERIAL_BREAK_SFX,
  MATERIAL_IMPACT_SFX,
  PHYSICS_AUDIO_ASSETS,
  PHYSICS_SFX,
  SLINGSHOT_AUDIO_ASSETS,
  SLINGSHOT_SFX
} from '../../src/constants/audio.js';
import { BLOCK_MATERIALS, TNT_EXPLOSION } from '../../src/constants/materials.js';

describe('sprite assets', () => {
  it('loads every bird as a five-frame 96px spritesheet', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    expect(Object.values(BIRD_SPRITE_FRAMES)).toEqual([0, 1, 2, 3, 4]);

    BIRD_SPRITE_TYPES.forEach((birdType) => {
      const asset = assetsByKey.get(`bird-${birdType}`);

      expect(asset).toMatchObject({
        type: 'spritesheet',
        key: `bird-${birdType}`,
        url: `assets/images/bird-${birdType}-sheet.png`,
        frameWidth: BIRD_SPRITE_FRAME_WIDTH,
        frameHeight: BIRD_SPRITE_FRAME_HEIGHT
      });
    });
  });

  it('loads pig, block, and material particle sprites from original PNG assets', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    PIG_SPRITE_TYPES.forEach((pigType) => {
      expect(assetsByKey.get(`pig-${pigType}`)).toMatchObject({
        type: 'image',
        key: `pig-${pigType}`,
        url: `assets/images/pig-${pigType}.png`
      });
    });

    MATERIAL_SPRITE_TYPES.forEach((material) => {
      expect(assetsByKey.get(`block-${material}`)).toMatchObject({
        type: 'image',
        key: `block-${material}`,
        url: `assets/images/block-${material}.png`
      });
    });

    const particleSuffixByMaterial = {
      wood: 'splinter',
      glass: 'shard',
      stone: 'rubble'
    };

    MATERIAL_PARTICLE_TYPES.forEach((material) => {
      const key = `particle-${material}-${particleSuffixByMaterial[material]}`;
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'image',
        key,
        url: `assets/images/${key}.png`
      });
    });
  });

  it('loads one original PNG background for each episode', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    EPISODE_BACKGROUND_IDS.forEach((episode) => {
      expect(assetsByKey.get(`bg-episode-${episode}`)).toMatchObject({
        type: 'image',
        key: `bg-episode-${episode}`,
        url: `assets/images/bg-episode-${episode}.png`
      });
    });
  });

  it('loads one original chapter-card hero illustration for each episode', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    expect(EPISODE_HERO_TITLES).toEqual({
      1: 'Poached Eggs',
      2: 'Mighty Hoax',
      3: 'Danger Above'
    });

    EPISODE_HERO_IDS.forEach((episode) => {
      expect(assetsByKey.get(`chapter-hero-episode-${episode}`)).toMatchObject({
        type: 'image',
        key: `chapter-hero-episode-${episode}`,
        url: `assets/images/chapter-hero-episode-${episode}.png`
      });
      expect(getEpisodeHeroKey(episode)).toBe(`chapter-hero-episode-${episode}`);
    });

    expect(getEpisodeHeroKey('unknown')).toBe('chapter-hero-episode-1');
  });

  it('loads slingshot and smoke particle sprites from original PNG assets', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    expect(assetsByKey.get('slingshot')).toMatchObject({
      type: 'image',
      key: 'slingshot',
      url: 'assets/images/slingshot.png'
    });
    expect(assetsByKey.get('particle-smoke')).toMatchObject({
      type: 'image',
      key: 'particle-smoke',
      url: 'assets/images/particle-smoke.png'
    });
  });

  it('resolves a level id to its episode background key', () => {
    expect(getEpisodeBackgroundKey('1-01')).toBe('bg-episode-1');
    expect(getEpisodeBackgroundKey('2-03')).toBe('bg-episode-2');
    expect(getEpisodeBackgroundKey('3-05')).toBe('bg-episode-3');
    expect(getEpisodeBackgroundKey('sandbox')).toBe('bg-episode-1');
  });

  it('loads distinct per-bird flight and ability SFX assets', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));
    const flightKeys = Object.values(BIRD_FLIGHT_SFX);
    const abilityKeys = Object.values(ABILITY_SFX);

    expect(Object.keys(BIRD_FLIGHT_SFX)).toEqual(BIRD_SPRITE_TYPES);
    expect(new Set(flightKeys).size).toBe(BIRD_SPRITE_TYPES.length);
    expect(ABILITY_SFX).toEqual({
      blues: 'sfx-blues-split',
      chuck: 'sfx-chuck-burst',
      matilda: 'sfx-matilda-egg-drop',
      bomb: 'sfx-bomb-fuse-explode',
      hal: 'sfx-hal-boomerang'
    });
    expect(new Set(abilityKeys).size).toBe(5);

    BIRD_FLIGHT_AUDIO_ASSETS.forEach(({ birdType, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        birdType
      });
    });

    ABILITY_AUDIO_ASSETS.forEach(({ birdType, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        birdType,
        ability: true
      });
    });

    [...BIRD_FLIGHT_AUDIO_ASSETS, ...ABILITY_AUDIO_ASSETS].forEach(({ key }) => {
      expect(GAMEPLAY_AUDIO_ASSETS.some((asset) => asset.key === key)).toBe(true);
    });
  });

  it('loads slingshot, material, pig, and TNT SFX assets', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    expect(SLINGSHOT_SFX).toEqual({
      pull: 'sfx-slingshot-pull',
      release: 'sfx-slingshot-release'
    });
    SLINGSHOT_AUDIO_ASSETS.forEach(({ action, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        action
      });
    });

    expect(MATERIAL_IMPACT_SFX).toEqual({
      wood: 'sfx-wood-impact',
      glass: 'sfx-glass-impact',
      stone: 'sfx-stone-impact'
    });
    expect(MATERIAL_BREAK_SFX).toEqual({
      wood: 'sfx-wood-break',
      glass: 'sfx-glass-break',
      stone: 'sfx-stone-break'
    });
    expect(new Set([
      ...Object.values(MATERIAL_IMPACT_SFX),
      ...Object.values(MATERIAL_BREAK_SFX)
    ]).size).toBe(6);

    MATERIAL_AUDIO_ASSETS.forEach(({ material, event, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        material,
        event
      });
    });
    MATERIAL_SPRITE_TYPES.forEach((material) => {
      expect(BLOCK_MATERIALS[material].impactSfx).toBe(MATERIAL_IMPACT_SFX[material]);
      expect(BLOCK_MATERIALS[material].breakSfx).toBe(MATERIAL_BREAK_SFX[material]);
    });

    expect(PHYSICS_SFX).toEqual({
      pigPop: 'sfx-pig-pop',
      tntExplosion: 'sfx-tnt-explosion'
    });
    PHYSICS_AUDIO_ASSETS.forEach(({ event, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        event
      });
    });
    expect(TNT_EXPLOSION.audioEvent).toBe(PHYSICS_SFX.tntExplosion);

    expect(GAMEPLAY_AUDIO_ASSETS).toHaveLength(23);
    expect(new Set(GAMEPLAY_AUDIO_ASSETS.map((asset) => asset.key)).size).toBe(23);
  });

  it('loads distinct win and fail end-state SFX assets', () => {
    const assetsByKey = new Map(PLACEHOLDER_ASSETS.map((asset) => [asset.key, asset]));

    expect(END_STATE_SFX).toEqual({
      cleared: 'sfx-level-win-stinger',
      failed: 'sfx-level-fail-jingle'
    });
    expect(new Set(Object.values(END_STATE_SFX)).size).toBe(2);

    END_STATE_AUDIO_ASSETS.forEach(({ outcome, key }) => {
      expect(assetsByKey.get(key)).toMatchObject({
        type: 'audio',
        key,
        url: `assets/audio/${key}.ogg`,
        outcome
      });
    });
  });
});
