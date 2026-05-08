import Phaser from 'phaser';

import { SCORING_POINTS } from '../constants/scoring.js';
import { registerDebugScene } from '../systems/debug.js';
import { getClearedCardActions } from '../systems/winLose.js';
import { actionLabels, createButton, navigateFromEndCard } from './endCardHelpers.js';

export default class ClearedCard extends Phaser.Scene {
  constructor() {
    super('ClearedCard');
  }

  init(data = {}) {
    this.cardData = data;
    this.displayedBonus = 0;
    this.bonusAnimationComplete = false;
  }

  create() {
    const data = this.normalizeData();
    this.cardData = data;

    this.add.rectangle(640, 360, 1280, 720, 0x0f1720, 0.58);
    this.add.rectangle(640, 344, 620, 430, 0xf6f0d0, 0.98)
      .setStrokeStyle(5, 0x1f2933);
    this.add.text(640, 170, 'LEVEL CLEARED!', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '46px',
      fontStyle: 'bold',
      color: '#2f7d32'
    }).setOrigin(0.5);
    this.add.text(640, 228, `STARS: ${data.stars}/3`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '30px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0.5);
    this.add.text(430, 288, `Base Score: ${data.baseScore.toLocaleString('en-US')}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '24px',
      color: '#1f2933'
    }).setOrigin(0, 0.5);
    this.add.text(430, 328, `Unused Birds: ${data.unusedBirdCount}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '24px',
      color: '#1f2933'
    }).setOrigin(0, 0.5);

    this.bonusText = this.add.text(430, 368, 'Bonus: +0', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '24px',
      fontStyle: 'bold',
      color: '#b45309'
    }).setOrigin(0, 0.5);
    this.bonusChips = this.renderBonusChips(data.unusedBirdCount);
    this.finalScoreText = this.add.text(430, 418, `Final Score: ${data.baseScore.toLocaleString('en-US')}`, {
      fontFamily: 'Arial, sans-serif',
      fontSize: '30px',
      fontStyle: 'bold',
      color: '#1f2933'
    }).setOrigin(0, 0.5);

    this.renderActions(data.actions);
    this.animateBonus(data);
    this.refreshDebug();
  }

  normalizeData() {
    const actions = this.cardData.actions ?? getClearedCardActions({
      levelId: this.cardData.levelId,
      save: this.cardData.save
    });

    return {
      levelId: this.cardData.levelId ?? '1-01',
      baseScore: Math.max(0, Math.floor(Number(this.cardData.baseScore) || 0)),
      unusedBirdCount: Math.max(0, Math.floor(Number(this.cardData.unusedBirdCount) || 0)),
      bonus: Math.max(0, Math.floor(Number(this.cardData.bonus) || 0)),
      finalScore: Math.max(0, Math.floor(Number(this.cardData.finalScore) || 0)),
      stars: Math.max(1, Math.min(3, Math.floor(Number(this.cardData.stars) || 1))),
      save: this.cardData.save,
      actions
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
        y: 520,
        label: action.label
      });

      return { action, x, y: 520, width: 210, height: 56 };
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

  renderBonusChips(unusedBirdCount) {
    if (unusedBirdCount === 0) {
      return [];
    }

    const spacing = unusedBirdCount > 4 ? 44 : 62;
    const startX = 700;

    return Array.from({ length: unusedBirdCount }, (_, index) => {
      const x = startX + index * spacing;
      const chip = this.add.container(x, 328);
      chip.add(this.add.rectangle(0, 0, 54, 28, 0xfff1c1)
        .setStrokeStyle(2, 0xb45309));
      chip.add(this.add.text(0, 0, '+10k', {
        fontFamily: 'Arial, sans-serif',
        fontSize: '16px',
        fontStyle: 'bold',
        color: '#b45309'
      }).setOrigin(0.5));
      chip.setAlpha(0.35);
      return chip;
    });
  }

  animateBonus(data) {
    if (data.unusedBirdCount === 0) {
      this.displayedBonus = data.bonus;
      this.bonusAnimationComplete = true;
      this.updateScoreTexts(data);
      return;
    }

    for (let index = 0; index < data.unusedBirdCount; index += 1) {
      this.time.delayedCall(220 * (index + 1), () => {
        this.displayedBonus = Math.min(
          data.bonus,
          this.displayedBonus + SCORING_POINTS.unusedBirdBonus
        );
        this.emitBirdBonus(index);
        this.updateScoreTexts(data);

        if (this.displayedBonus === data.bonus) {
          this.bonusAnimationComplete = true;
          this.refreshDebug();
        }
      });
    }
  }

  emitBirdBonus(index) {
    const chip = this.bonusChips[index];
    chip?.setAlpha(1);
    if (chip) {
      this.tweens.add({
        targets: chip,
        y: 318,
        duration: 120,
        yoyo: true
      });
    }

    const x = 755 + index * 38;
    const bonus = this.add.text(x, 328, '+10000', {
      fontFamily: 'Arial, sans-serif',
      fontSize: '18px',
      fontStyle: 'bold',
      color: '#b45309'
    }).setOrigin(0.5);

    this.tweens.add({
      targets: bonus,
      y: 286,
      alpha: 0,
      duration: 520,
      onComplete: () => bonus.destroy()
    });
  }

  updateScoreTexts(data) {
    const currentScore = data.baseScore + this.displayedBonus;
    this.bonusText.setText(`Bonus: +${this.displayedBonus.toLocaleString('en-US')}`);
    this.finalScoreText.setText(`Final Score: ${currentScore.toLocaleString('en-US')}`);
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
        score: data.finalScore,
        birdsLeft: data.unusedBirdCount,
        pigsLeft: 0,
        settled: true,
        queue: [],
        endCard: {
          outcome: 'cleared',
          levelId: data.levelId,
          baseScore: data.baseScore,
          displayedBonus: this.displayedBonus,
          bonus: data.bonus,
          finalScore: data.finalScore,
          stars: data.stars,
          bonusAnimationComplete: this.bonusAnimationComplete,
          actions: actionLabels(data.actions)
        }
      },
      save: data.save,
      audio: audioState,
      mute: audioState?.muted ?? data.save?.mute ?? false
    });
  }
}
