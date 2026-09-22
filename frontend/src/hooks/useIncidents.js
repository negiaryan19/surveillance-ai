import { useCallback, useEffect, useState } from 'react';
import { apiFetch, isAbortError } from '../api/client.js';

const FALLBACK_POLL_MS = 10_000;

export const DEFAULT_FILTERS = { minThreat: '', zone: '', camera: '', unacknowledged: false };

function buildQuery(filters, page, pageSize) {
  const query = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
  if (filters.minThreat !== '') query.set('min_threat', String(filters.minThreat));
  if (filters.zone) query.set('zone', filters.zone);
  if (filters.camera) query.set('camera', filters.camera);
  if (filters.unacknowledged) query.set('acknowledged', 'false');
  return query.toString();
}

/** Client-side mirror of the server filters, used to decide whether a live incident belongs in the list. */
export function matchesFilters(incident, filters) {
  if (filters.minThreat !== '' && (Number(incident.threat_score) || 0) < Number(filters.minThreat)) return false;
  if (filters.zone && incident.zone_level !== filters.zone) return false;
  if (filters.camera && incident.camera !== filters.camera) return false;
  if (filters.unacknowledged && incident.acknowledged) return false;
  return true;
}

function prependIncident(data, incident, pageSize) {
  if (data.items.some((item) => item.id === incident.id)) return data;
  return { ...data, items: [incident, ...data.items].slice(0, pageSize), total: data.total + 1 };
}

function patchIncident(data, id, patch) {
  if (!data.items.some((item) => item.id === id)) return data;
  return { ...data, items: data.items.map((item) => (item.id === id ? { ...item, ...patch } : item)) };
}

/**
 * A filtered, paginated incident list kept live by SSE.
 *
 * - `incident`: prepended when it matches the filters and the first page is showing
 *   (on later pages only the total grows, so rows do not shift under the reader).
 * - `incident_updated` / `ack`: the matching row is replaced in place. A row that no longer
 *   matches the "unacknowledged" filter stays visible until the next reload, so the user
 *   sees the result of their own click instead of the row vanishing.
 * - While the stream is down the list falls back to polling every 10 s; when the stream
 *   comes back the list reloads once to pick up anything it missed.
 *
 * @param {object} options
 * @param {(listener: Function) => () => void} options.subscribe from useEventStream
 * @param {boolean} options.live whether the event stream is currently connected
 * @param {number} [options.pageSize]
 */
export function useIncidents({ subscribe, live, pageSize = 25 }) {
  const [filters, setFilterState] = useState(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const [data, setData] = useState({ key: null, items: [], total: 0 });
  const [error, setError] = useState('');
  const [reloadTick, setReloadTick] = useState(0);

  const queryKey = buildQuery(filters, page, pageSize);

  const setFilters = useCallback((next) => {
    setFilterState(next);
    setPage(0);
  }, []);

  const refresh = useCallback(() => setReloadTick((tick) => tick + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    const load = async () => {
      try {
        const body = await apiFetch(`/api/incidents?${queryKey}`, { signal });
        if (signal.aborted) return;
        setData({
          key: queryKey,
          items: Array.isArray(body?.items) ? body.items : [],
          total: Number(body?.total) || 0,
        });
        setError('');
      } catch (loadError) {
        if (isAbortError(loadError) || signal.aborted) return;
        setData((prev) => ({ ...prev, key: queryKey }));
        setError(loadError.message);
      }
    };

    load();
    if (live) return () => controller.abort();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, FALLBACK_POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [queryKey, live, reloadTick]);

  useEffect(
    () =>
      subscribe((type, payload) => {
        if (type === 'incident') {
          if (!matchesFilters(payload, filters)) return;
          setData((prev) =>
            page === 0 ? prependIncident(prev, payload, pageSize) : { ...prev, total: prev.total + 1 },
          );
        } else if (type === 'incident_updated') {
          setData((prev) => patchIncident(prev, payload.id, payload));
        } else if (type === 'ack') {
          setData((prev) => patchIncident(prev, payload.id, { acknowledged: Boolean(payload.acknowledged) }));
        }
      }),
    [subscribe, filters, page, pageSize],
  );

  return {
    items: data.items,
    total: data.total,
    loading: data.key !== queryKey,
    error,
    filters,
    setFilters,
    page,
    setPage,
    pageSize,
    refresh,
  };
}
