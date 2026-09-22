import { useCallback, useEffect, useState } from 'react';
import { apiFetch, getToken, isAbortError } from '../api/client.js';

const POLL_MS = 5000;

/**
 * Keep only the documented status fields. Dropping everything else (notably `stream_url`
 * and `snapshot_url`) guarantees media URLs are always derived client-side with
 * `mediaUrl`, never taken from a payload.
 */
function normaliseCamera(raw) {
  return {
    id: String(raw.id),
    name: raw.name || String(raw.id).toUpperCase(),
    online: Boolean(raw.online),
    fps: Number(raw.fps) || 0,
    tracks: Number(raw.tracks) || 0,
    night_mode: Boolean(raw.night_mode),
    last_frame_at: raw.last_frame_at ?? null,
    source: raw.source ?? '',
  };
}

function normaliseCameraList(list) {
  return Array.isArray(list) ? list.filter((item) => item && item.id != null).map(normaliseCamera) : [];
}

/**
 * Merge an SSE `status` camera list INTO the current list by id. Known cameras are patched
 * in place (configured order preserved), unseen ids are appended, and cameras missing from
 * the event are kept - a partial status event must never make a feed disappear.
 */
export function mergeCameras(current, incoming) {
  const updates = new Map(normaliseCameraList(incoming).map((camera) => [camera.id, camera]));
  const merged = current.map((camera) => {
    const update = updates.get(camera.id);
    updates.delete(camera.id);
    return update ? { ...camera, ...update } : camera;
  });
  return [...merged, ...updates.values()];
}

const INITIAL_STATE = {
  status: 'checking', // checking | online | offline | unauthorized
  error: '',
  health: null,
  cameras: [],
  alertsPaused: false,
  modules: null,
};

/**
 * Backend-wide state: health, cameras, alert pause flag and module info.
 *
 * Polls every 5 s (skipped while the page is hidden) and applies SSE `status` events in
 * between. `/api/health` is never authenticated, so it doubles as auth discovery: when it
 * reports `auth_required` and no token is stored, the state goes straight to
 * "unauthorized" without provoking a 401.
 *
 * @param {(listener: Function) => () => void} subscribe from useEventStream
 */
export function useBackend(subscribe) {
  const [state, setState] = useState(INITIAL_STATE);
  const [pollTick, setPollTick] = useState(0);

  /** Poll again right now (after login, after an action that changes backend state). */
  const refresh = useCallback(() => setPollTick((tick) => tick + 1), []);

  const setAlertsPaused = useCallback((paused) => {
    setState((prev) => ({ ...prev, alertsPaused: Boolean(paused) }));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let inFlight = false;

    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const health = await apiFetch('/api/health', { signal });
        if (signal.aborted) return;
        if (health?.auth_required && !getToken()) {
          setState((prev) => ({ ...prev, status: 'unauthorized', error: '', health }));
          return;
        }
        const [cameras, alerts, modules] = await Promise.all([
          apiFetch('/api/cameras', { signal }),
          apiFetch('/api/alerts', { signal }),
          apiFetch('/api/modules', { signal }),
        ]);
        if (signal.aborted) return;
        setState({
          status: 'online',
          error: '',
          health,
          cameras: normaliseCameraList(cameras),
          alertsPaused: Boolean(alerts?.paused),
          modules,
        });
      } catch (error) {
        if (isAbortError(error) || signal.aborted) return;
        if (error.status === 401) {
          setState((prev) => ({ ...prev, status: 'unauthorized', error: '' }));
        } else if (error.status) {
          // The backend answered, so it is up; surface the failure without the offline banner.
          setState((prev) => ({ ...prev, status: 'online', error: error.message }));
        } else {
          setState((prev) => ({ ...prev, status: 'offline', error: error.message }));
        }
      } finally {
        inFlight = false;
      }
    };

    poll();
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') poll();
    }, POLL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') poll();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [pollTick]);

  useEffect(
    () =>
      subscribe((type, data) => {
        if (type === 'status') {
          setState((prev) => ({
            ...prev,
            cameras: mergeCameras(prev.cameras, data.cameras),
            alertsPaused: typeof data.alerts_paused === 'boolean' ? data.alerts_paused : prev.alertsPaused,
          }));
        } else if (type === 'faces') {
          refresh();
        }
      }),
    [subscribe, refresh],
  );

  return { ...state, refresh, setAlertsPaused };
}
