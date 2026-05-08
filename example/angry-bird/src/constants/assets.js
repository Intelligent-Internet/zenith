import { GAMEPLAY_AUDIO_ASSETS } from './audio.js';

function svgDataUri(svg) {
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function simpleSvg({ fill, stroke = '#1f2933', label, width = 96, height = 96, shape = 'rect' }) {
  const body = shape === 'circle'
    ? `<circle cx="${width / 2}" cy="${height / 2}" r="${Math.min(width, height) * 0.38}" fill="${fill}" stroke="${stroke}" stroke-width="6" />`
    : `<rect x="8" y="8" width="${width - 16}" height="${height - 16}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="6" />`;

  return svgDataUri(`
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      ${body}
      <text x="50%" y="55%" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" font-weight="700" fill="#ffffff">${label}</text>
    </svg>
  `);
}

export const BIRD_SPRITE_FRAME_WIDTH = 96;
export const BIRD_SPRITE_FRAME_HEIGHT = 96;

export const BIRD_SPRITE_FRAMES = {
  idleCry: 0,
  fly: 1,
  hit: 2,
  abilityPre: 3,
  abilityPost: 4
};

export const BIRD_SPRITE_FRAME_COUNT = Object.keys(BIRD_SPRITE_FRAMES).length;

export const BIRD_SPRITE_TYPES = ['red', 'blues', 'chuck', 'matilda', 'bomb', 'hal'];

export const PIG_SPRITE_TYPES = ['small', 'medium', 'large', 'helmeted'];

export const MATERIAL_SPRITE_TYPES = ['wood', 'glass', 'stone'];

export const MATERIAL_PARTICLE_TYPES = ['wood', 'glass', 'stone'];

export const EPISODE_BACKGROUND_IDS = [1, 2, 3];
export const EPISODE_HERO_IDS = [1, 2, 3];
export const EPISODE_HERO_TITLES = {
  1: 'Poached Eggs',
  2: 'Mighty Hoax',
  3: 'Danger Above'
};

const MATERIAL_PARTICLE_SUFFIXES = {
  wood: 'splinter',
  glass: 'shard',
  stone: 'rubble'
};

export const BIRD_SPRITE_STATES = [
  { key: 'idleCry', label: 'Idle/Cry', frame: BIRD_SPRITE_FRAMES.idleCry },
  { key: 'fly', label: 'Fly', frame: BIRD_SPRITE_FRAMES.fly },
  { key: 'hit', label: 'Hit', frame: BIRD_SPRITE_FRAMES.hit },
  { key: 'abilityPre', label: 'Ability Pre', frame: BIRD_SPRITE_FRAMES.abilityPre },
  { key: 'abilityPost', label: 'Ability Post', frame: BIRD_SPRITE_FRAMES.abilityPost }
];

const BIRD_SPRITE_ASSETS = BIRD_SPRITE_TYPES.map((birdType) => ({
  type: 'spritesheet',
  key: `bird-${birdType}`,
  url: `assets/images/bird-${birdType}-sheet.png`,
  frameWidth: BIRD_SPRITE_FRAME_WIDTH,
  frameHeight: BIRD_SPRITE_FRAME_HEIGHT,
  frameCount: BIRD_SPRITE_FRAME_COUNT
}));

const PIG_SPRITE_ASSETS = PIG_SPRITE_TYPES.map((pigType) => ({
  type: 'image',
  key: `pig-${pigType}`,
  url: `assets/images/pig-${pigType}.png`
}));

const MATERIAL_SPRITE_ASSETS = MATERIAL_SPRITE_TYPES.map((material) => ({
  type: 'image',
  key: `block-${material}`,
  url: `assets/images/block-${material}.png`
}));

const TNT_CRATE_ASSET = {
  type: 'image',
  key: 'tnt-crate',
  url: simpleSvg({
    fill: '#c4472d',
    stroke: '#5b2a1d',
    label: 'TNT',
    width: 72,
    height: 72
  })
};

const BOULDER_ASSET = {
  type: 'image',
  key: 'boulder-stone',
  url: simpleSvg({
    fill: '#9a8c72',
    stroke: '#5f574a',
    label: '',
    width: 96,
    height: 96,
    shape: 'circle'
  })
};

const MATERIAL_PARTICLE_ASSETS = MATERIAL_PARTICLE_TYPES.map((material) => ({
  type: 'image',
  key: `particle-${material}-${MATERIAL_PARTICLE_SUFFIXES[material]}`,
  url: `assets/images/particle-${material}-${MATERIAL_PARTICLE_SUFFIXES[material]}.png`
}));

const EPISODE_BACKGROUND_ASSETS = EPISODE_BACKGROUND_IDS.map((episode) => ({
  type: 'image',
  key: `bg-episode-${episode}`,
  url: `assets/images/bg-episode-${episode}.png`
}));

const EPISODE_HERO_ASSETS = EPISODE_HERO_IDS.map((episode) => ({
  type: 'image',
  key: `chapter-hero-episode-${episode}`,
  url: `assets/images/chapter-hero-episode-${episode}.png`
}));

const SLINGSHOT_ASSET = {
  type: 'image',
  key: 'slingshot',
  url: 'assets/images/slingshot.png'
};

const SMOKE_PARTICLE_ASSET = {
  type: 'image',
  key: 'particle-smoke',
  url: 'assets/images/particle-smoke.png'
};

export const BOOT_ASSETS = [
  {
    type: 'image',
    key: 'loading-bar',
    url: svgDataUri(`
      <svg xmlns="http://www.w3.org/2000/svg" width="320" height="24" viewBox="0 0 320 24">
        <rect width="320" height="24" rx="12" fill="#1f2933" />
        <rect x="4" y="4" width="312" height="16" rx="8" fill="#f8d24a" />
      </svg>
    `)
  }
];

export const PLACEHOLDER_ASSETS = [
  ...EPISODE_BACKGROUND_ASSETS,
  ...EPISODE_HERO_ASSETS,
  { type: 'image', key: 'ground-grass', url: simpleSvg({ fill: '#35a852', label: 'GRD', width: 160, height: 40 }) },
  SLINGSHOT_ASSET,
  ...BIRD_SPRITE_ASSETS,
  { type: 'image', key: 'matilda-egg', url: simpleSvg({ fill: '#fff7d6', label: 'EGG', stroke: '#b0892b', width: 64, height: 80, shape: 'circle' }) },
  ...PIG_SPRITE_ASSETS,
  ...MATERIAL_SPRITE_ASSETS,
  TNT_CRATE_ASSET,
  BOULDER_ASSET,
  ...MATERIAL_PARTICLE_ASSETS,
  SMOKE_PARTICLE_ASSET,
  ...GAMEPLAY_AUDIO_ASSETS,
  { type: 'image', key: 'particle-matilda-egg-pop', url: simpleSvg({ fill: '#ffe08a', label: 'E', width: 32, height: 32, shape: 'circle' }) },
  { type: 'image', key: 'particle-pig-puff', url: simpleSvg({ fill: '#83d951', label: 'P', width: 32, height: 32, shape: 'circle' }) }
];

export function loadAsset(scene, asset) {
  if (asset.type === 'image') {
    scene.load.image(asset.key, asset.url);
  }

  if (asset.type === 'spritesheet') {
    scene.load.spritesheet(asset.key, asset.url, {
      frameWidth: asset.frameWidth,
      frameHeight: asset.frameHeight
    });
  }

  if (asset.type === 'audio') {
    scene.load.audio(asset.key, asset.url);
  }
}

export function getEpisodeBackgroundKey(levelId = '') {
  const episode = Number(String(levelId).split('-')[0]);
  return EPISODE_BACKGROUND_IDS.includes(episode) ? `bg-episode-${episode}` : 'bg-episode-1';
}

export function getEpisodeHeroKey(episode = 1) {
  const episodeNumber = Number(episode);
  return EPISODE_HERO_IDS.includes(episodeNumber)
    ? `chapter-hero-episode-${episodeNumber}`
    : 'chapter-hero-episode-1';
}
