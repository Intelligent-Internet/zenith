import Phaser from 'phaser';

import { registerDebugScene } from '../systems/debug.js';
import { getFailedCardActions } from '../systems/winLose.js';
import { actionLabels, createButton, navigateFromEndCard } from './endCardHelpers.js';

export default class FailedCard extends Phaser.Scene {
  constructor() {
    super('FailedCard');
  }

  init(data = {}) {
    this.cardData = data;
  }

  create() {
    const data = this.normalizeData();
    this.cardData = data;

    this.add.rectangle(640, 360, 1280, 720, 0x0f1720, 0.58);
    this.add.rectangle(640, 344, 560, 330, 0xf6f0d0, 0.98)
      .setStrokeStyle(5, 0x1f2933);
    this.add.text(640, 210, 'LEVEL FAILED', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '44px',
      fontStyle: 'bold',
      color: '#b91c1c'
    }).setOrigin(0.5);
    this.add.text(640, 292, `Score: ${data.score.toLocaleString('en-US')}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '30px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    this.add.text(640, 336, 'No stars awarded', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '22px',
      color: '#475569'
    }).setOrigin(0.5);

    this.renderActions(data.actions);
    this.refreshDebug();
  }

  normalizeData() {
    return {
      levelId: this.cardData.levelId ?? '1-01',
      score: Math.max(0, Math.floor(Number(this.cardData.score) || 0)),
      pigsLeft: Math.max(1, Math.floor(Number(this.cardData.pigsLeft) || 1)),
      save: this.cardData.save,
      actions: this.cardData.actions ?? getFailedCardActions(this.cardData.levelId ?? '1-01')
    };
  }

  getGameScene() {
    return typeof this.scene?.get === 'function' ? this.scene.get('Game') : null;
  }

  renderActions(actions) {
    const spacing = 224;
    const startX = 640 - ((actions.length - 1) * spacing) / 2;

    this.actionRegions = actions.map((action, index) => {
      const x = startX + index * spacing;
      createButton(this, {
        x,
        y: 454,
        label: action.label
      });

      return { action, x, y: 454, width: 210, height: 56 };
    });
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.removeDomPointerHandler();
    });
    this.installDomPointerHandler();
  }

  findActionRegion(x, y) {
    return this.actionRegions?.find((entry) => (
      Math.abs(x - entry.x) <= entry.width / 2
      && Math.abs(y - entry.y) <= entry.height / 2
    ));
  }

  navigateAction(action) {
    if (this.navigating) {
      return;
    }

    this.navigating = true;
    this.removeDomPointerHandler();
    navigateFromEndCard(this, action);
  }

  installDomPointerHandler() {
    const canvas = this.sys.game.canvas;
    if (!canvas) {
      return;
    }

    this.domPointerHandler = (event) => {
      const bounds = canvas.getBoundingClientRect();
      const x = ((event.clientX - bounds.left) / bounds.width) * this.scale.width;
      const y = ((event.clientY - bounds.top) / bounds.height) * this.scale.height;
      const region = this.findActionRegion(x, y);

      if (region) {
        event.preventDefault();
        event.stopPropagation();
        this.pendingAction = region.action;
      }
    };
    canvas.addEventListener('pointerdown', this.domPointerHandler);
  }

  removeDomPointerHandler() {
    const canvas = this.sys.game.canvas;
    if (canvas && this.domPointerHandler) {
      canvas.removeEventListener('pointerdown', this.domPointerHandler);
    }
    this.domPointerHandler = null;
  }

  update() {
    if (this.pendingAction && !this.navigating) {
      const action = this.pendingAction;
      this.pendingAction = null;
      this.navigateAction(action);
      return;
    }

    this.refreshDebug();
  }

  refreshDebug() {
    const data = this.cardData;
    const gameScene = this.getGameScene();
    const audioState = gameScene?.audioState;

    registerDebugScene(this, {
      scene: {
        score: data.score,
        birdsLeft: 0,
        pigsLeft: data.pigsLeft,
        settled: true,
        queue: [],
        endCard: {
          outcome: 'failed',
          levelId: data.levelId,
          score: data.score,
          stars: 0,
          actions: actionLabels(data.actions)
        }
      },
      save: data.save,
      audio: audioState,
      mute: audioState?.muted ?? data.save?.mute ?? false
    });
  }
}
