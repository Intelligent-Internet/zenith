export function resolveBootRoute({
  search = '',
  env = import.meta.env
} = {}) {
  const params = new globalThis.URLSearchParams(search);
  const scene = params.get('scene');
  const levelId = params.get('level');

  if (params.get('roster') === '1' && env?.ANGRY_BIRD_DEV) {
    return {
      scene: 'DebugRoster',
      data: undefined,
      transientLevelParam: false
    };
  }

  if (scene === 'LevelSelect') {
    return {
      scene: 'LevelSelect',
      data: {
        episode: Number(params.get('episode')) || 1
      },
      transientLevelParam: false
    };
  }

  if (scene === 'EpisodeSelect') {
    return {
      scene: 'EpisodeSelect',
      data: undefined,
      transientLevelParam: false
    };
  }

  if (levelId) {
    return {
      scene: 'Game',
      data: { level: levelId },
      transientLevelParam: true
    };
  }

  return {
    scene: 'Menu',
    data: undefined,
    transientLevelParam: false
  };
}

export function stripTransientLevelParamFromUrl(href) {
  const url = new globalThis.URL(href);

  if (!url.searchParams.has('level')) {
    return url.toString();
  }

  url.searchParams.delete('level');
  url.search = url.searchParams.toString();
  return url.toString();
}

export function clearTransientLevelParam(windowLike = globalThis.window) {
  if (!windowLike?.location || typeof windowLike.history?.replaceState !== 'function') {
    return false;
  }

  const nextUrl = stripTransientLevelParamFromUrl(windowLike.location.href);
  if (nextUrl === windowLike.location.href) {
    return false;
  }

  windowLike.history.replaceState(windowLike.history.state ?? null, '', nextUrl);
  return true;
}
