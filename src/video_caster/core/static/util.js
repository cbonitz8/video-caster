export function backoffDelay(attempt) {
  return Math.min(2 ** attempt, 10) * 1000;
}

export function formatTime(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function formatLeft(position, duration) {
  const minutes = Math.max(1, Math.round((duration - position) / 60));
  if (minutes < 60) return `${minutes}m left`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m left`;
}

export function throttle(fn, ms) {
  let last = -Infinity;
  let timer = null;
  let pending = null;
  return (...args) => {
    const wait = last + ms - Date.now();
    if (wait <= 0) {
      last = Date.now();
      fn(...args);
      return;
    }
    pending = args;
    if (timer === null) {
      timer = setTimeout(() => {
        timer = null;
        last = Date.now();
        fn(...pending);
      }, wait);
    }
  };
}

const EPISODE_SUBTITLE = /^(S\d+E(\d+))(?: · (.+))?$/;

export function episodeParts(subtitle) {
  if (subtitle === null) return null;
  const match = EPISODE_SUBTITLE.exec(subtitle);
  if (match === null) return null;
  return { code: match[1], episode: match[2], name: match[3] === undefined ? null : match[3] };
}

export function inProgress(row) {
  return row.position !== null && row.duration !== null && row.duration > 0;
}

export function tileSub(row) {
  const parts = episodeParts(row.subtitle);
  const left = inProgress(row) ? formatLeft(row.position, row.duration) : null;
  if (parts === null) return left;
  if (left !== null) return `${parts.code} · ${left}`;
  return row.subtitle;
}

export function seasonLabel(n) {
  return n === 0 ? "Specials" : `Season ${n}`;
}

export function seasonLine(show) {
  const eps = show.episode_count === 1 ? "1 ep" : `${show.episode_count} eps`;
  const seasons = show.seasons.length === 1 ? seasonLabel(show.seasons[0].season) : `${show.seasons.length} seasons`;
  return `${seasons} · ${eps}`;
}

export function episodeTitle(row) {
  const parts = episodeParts(row.subtitle);
  if (parts === null) return row.title;
  return parts.name === null ? `Episode ${Number(parts.episode)}` : parts.name;
}

export function findShow(library, key) {
  const show = library.shows.find((s) => s.key === key);
  return show === undefined ? null : show;
}
