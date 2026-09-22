import { useCallback, useEffect, useState } from 'react';
import { apiFetch, isAbortError } from '../api/client.js';

const REFRESH_MS = 60_000;
const EVENT_DEBOUNCE_MS = 1500;

/**
 * `/api/stats` for the dashboard tiles and chart. Refreshed on a slow timer and shortly
 * after every incident/ack event (debounced, so a burst of alerts costs one request).
 */
export function useStats({ subscribe, enabled, hours = 24 }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    const { signal } = controller;

    const load = async () => {
      try {
        const body = await apiFetch(`/api/stats?hours=${hours}`, { signal });
        if (!signal.aborted && body) {
          setStats(body);
          setLoading(false);
        }
      } catch (error) {
        if (!isAbortError(error) && !signal.aborted) setLoading(false);
      }
    };

    queueMicrotask(load);
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, REFRESH_MS);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [enabled, hours, tick]);

  useEffect(() => {
    let timer = null;
    const unsubscribe = subscribe((type) => {
      if (type !== 'incident' && type !== 'ack') return;
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, EVENT_DEBOUNCE_MS);
    });
    return () => {
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [subscribe, refresh]);

  return { stats, loading, refresh };
}
