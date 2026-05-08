import Phaser from 'phaser';
import Boot from './scenes/Boot.js';
import Preloader from './scenes/Preloader.js';
import Menu from './scenes/Menu.js';
import EpisodeSelect from './scenes/EpisodeSelect.js';
import LevelSelect from './scenes/LevelSelect.js';
import Game from './scenes/Game.js';
import DebugRoster from './scenes/DebugRoster.js';
import GameOver from './scenes/GameOver.js';
import ClearedCard from './scenes/ClearedCard.js';
import FailedCard from './scenes/FailedCard.js';
import PauseOverlay from './scenes/PauseOverlay.js';
import { installDeferredAudioResume } from './systems/audioUnlock.js';

import './styles.css';

const GAME_WIDTH = 1280;
const GAME_HEIGHT = 720;

const sceneList = [
  Boot,
  Preloader,
  Menu,
  ...(import.meta.env.ANGRY_BIRD_DEV ? [DebugRoster] : []),
  EpisodeSelect,
  LevelSelect,
  Game,
  PauseOverlay,
  GameOver,
  ClearedCard,
  FailedCard
];

const gameConfig = {
  type: Phaser.AUTO,
  width: GAME_WIDTH,
  height: GAME_HEIGHT,
  parent: 'game-container',
  backgroundColor: '#7ec8e3',
  physics: {
    default: 'matter',
    matter: {
      gravity: { x: 0, y: 1 },
      debug: false
    }
  },
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
    width: GAME_WIDTH,
    height: GAME_HEIGHT
  },
  scene: sceneList
};

const game = new Phaser.Game(gameConfig);
installDeferredAudioResume({
  getSoundManager: () => game.sound
});

if (import.meta.env.ANGRY_BIRD_DEV && typeof window !== 'undefined') {
  window.__PHASER_GAME__ = game;
}
