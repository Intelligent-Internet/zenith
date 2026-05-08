export function createButton(scene, {
  x,
  y,
  label,
  width = 210,
  onClick
}) {
  scene.add.rectangle(x, y, width, 56, 0xf8d24a)
    .setStrokeStyle(4, 0x1f2933);
  scene.add.text(x, y, label, {
    fontFamily: 'Arial, sans-serif',
    fontSize: '22px',
    fontStyle: 'bold',
    color: '#1f2933'
  }).setOrigin(0.5);

  const hitArea = scene.add.zone(x, y, width, 56)
    .setOrigin(0.5)
    .setInteractive({ useHandCursor: true });

  if (onClick) {
    hitArea.on('pointerdown', onClick);
  }
  return hitArea;
}

export function navigateFromEndCard(scene, action) {
  if (typeof window !== 'undefined') {
    const nextUrl = new window.URL(window.location.href);
    nextUrl.search = '';

    if (action.target === 'game') {
      nextUrl.searchParams.set('level', action.levelId);
    } else if (action.target === 'level-select') {
      nextUrl.searchParams.set('scene', 'LevelSelect');
      nextUrl.searchParams.set('episode', action.episode);
    } else {
      nextUrl.searchParams.set('scene', 'EpisodeSelect');
    }

    window.location.assign(nextUrl.toString());
    return;
  }

  const sceneManager = scene.sys.game.scene;
  const currentKey = scene.sys.settings.key;

  sceneManager.stop(currentKey);
  sceneManager.stop('Game');

  if (action.target === 'game') {
    sceneManager.start('Game', { level: action.levelId });
    return;
  }

  if (action.target === 'level-select') {
    sceneManager.start('LevelSelect', { episode: action.episode });
    return;
  }

  sceneManager.start('EpisodeSelect');
}

export function actionLabels(actions = []) {
  return actions.map((action) => action.label);
}
