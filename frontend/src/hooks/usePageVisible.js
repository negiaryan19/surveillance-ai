import { useSyncExternalStore } from 'react';

function subscribe(onChange) {
  document.addEventListener('visibilitychange', onChange);
  return () => document.removeEventListener('visibilitychange', onChange);
}

function getSnapshot() {
  return document.visibilityState === 'visible';
}

/**
 * True while the browser tab is in the foreground.
 *
 * Long-lived connections (MJPEG streams) are only worth holding for a page someone is
 * looking at: browsers cap connections per origin across ALL tabs, so a hidden tab that
 * keeps its streams open can starve a visible one.
 */
export function usePageVisible() {
  return useSyncExternalStore(subscribe, getSnapshot, () => true);
}
