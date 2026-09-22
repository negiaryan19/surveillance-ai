import { useEffect, useRef, useState } from 'react';
import { ShieldAlert, Trash2, UserPlus, Users } from 'lucide-react';
import { apiFetch, isAbortError } from '../api/client.js';
import { useMountedRef } from '../hooks/useMountedRef.js';
import PanelHeader from './PanelHeader.jsx';

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED = ['image/jpeg', 'image/png'];
const NAME_PATTERN = /^[A-Za-z][A-Za-z0-9 -]{0,39}$/;

function clientCheck(name, file) {
  if (!NAME_PATTERN.test(name.trim().replace(/\s+/g, ' '))) {
    return 'Name must start with a letter and use only letters, digits, spaces or hyphens (max 40).';
  }
  if (!file) return 'Choose a JPG or PNG photo.';
  const ext = file.name.split('.').pop()?.toLowerCase();
  if (!ACCEPTED.includes(file.type) && !['jpg', 'jpeg', 'png'].includes(ext)) return 'Only JPG and PNG photos are accepted.';
  if (file.size > MAX_BYTES) return 'The photo must be 5 MB or smaller.';
  return '';
}

/**
 * Enrol / remove known people. Enrolled faces are what makes a person "authorized"
 * (once liveness is confirmed), so the panel says plainly what is stored and where.
 */
export default function FacesPanel({ subscribe, onError }) {
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(null);
  const [tick, setTick] = useState(0);
  const fileRef = useRef(null);
  const mountedRef = useMountedRef();

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const body = await apiFetch('/api/faces', { signal: controller.signal });
        if (controller.signal.aborted) return;
        setPeople(Array.isArray(body?.people) ? body.people : []);
        setLoading(false);
      } catch (loadError) {
        if (isAbortError(loadError) || controller.signal.aborted) return;
        setLoading(false);
        onError(`Could not load known faces: ${loadError.message}`);
      }
    };
    queueMicrotask(load);
    return () => controller.abort();
  }, [tick, onError]);

  useEffect(() => subscribe((type) => {
    if (type === 'faces') setTick((value) => value + 1);
  }), [subscribe]);

  const enroll = async (event) => {
    event.preventDefault();
    const problem = clientCheck(name, file);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const form = new FormData();
      form.append('name', name.trim());
      form.append('image', file, file.name);
      const body = await apiFetch('/api/faces', { method: 'POST', body: form });
      if (!mountedRef.current) return;
      setNotice(`${body?.name ?? name} enrolled (${body?.images ?? 1} photo${body?.images === 1 ? '' : 's'}).`);
      setName('');
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      setTick((value) => value + 1);
    } catch (enrollError) {
      if (mountedRef.current) setError(enrollError.message);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  const remove = async (person) => {
    setBusy(true);
    setNotice('');
    try {
      await apiFetch(`/api/faces/${encodeURIComponent(person)}`, { method: 'DELETE' });
      if (!mountedRef.current) return;
      setNotice(`${person} removed.`);
      setConfirming(null);
      setTick((value) => value + 1);
    } catch (removeError) {
      if (mountedRef.current) onError(`Could not remove ${person}: ${removeError.message}`);
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  };

  return (
    <div className="faces-layout">
      <section className="panel">
        <PanelHeader title="Known faces" subtitle={loading ? 'Loading…' : `${people.length} enrolled`} />
        {people.length === 0 && !loading ? (
          <div className="empty-state">
            <Users size={22} aria-hidden="true" />
            <strong>Nobody enrolled yet</strong>
            <span>Every person is treated as unknown until you add them here.</span>
          </div>
        ) : (
          <ul className="plain-list people-list">
            {people.map((person) => (
              <li key={person.name} className="person-row">
                <div>
                  <strong>{person.name}</strong>
                  <span className="muted small">{person.images} photo{person.images === 1 ? '' : 's'}</span>
                </div>
                {confirming === person.name ? (
                  <div className="confirm-row" role="group" aria-label={`Confirm removing ${person.name}`}>
                    <span className="small">Remove all photos of {person.name}?</span>
                    <button type="button" className="btn danger" disabled={busy} onClick={() => remove(person.name)}>Remove</button>
                    <button type="button" className="btn ghost" disabled={busy} onClick={() => setConfirming(null)}>Cancel</button>
                  </div>
                ) : (
                  <button type="button" className="btn ghost" onClick={() => setConfirming(person.name)} aria-label={`Remove ${person.name}`}>
                    <Trash2 size={16} aria-hidden="true" />
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <PanelHeader title="Enrol a person" subtitle="One clear, front-facing photo with exactly one face" />
        <form className="enroll-form" onSubmit={enroll} noValidate>
          <div className="field">
            <label htmlFor="enroll-name">Name</label>
            <input id="enroll-name" value={name} maxLength={40} autoComplete="off" onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="enroll-photo">Photo (JPG or PNG, up to 5 MB)</label>
            <input
              id="enroll-photo"
              ref={fileRef}
              type="file"
              accept=".jpg,.jpeg,.png,image/jpeg,image/png"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          {notice && <p className="form-ok" role="status">{notice}</p>}
          <button type="submit" className="btn primary" disabled={busy}>
            <UserPlus size={16} aria-hidden="true" />
            {busy ? 'Working…' : 'Enrol'}
          </button>
        </form>
        <p className="privacy-note">
          <ShieldAlert size={14} aria-hidden="true" />
          Tell people before you enrol them. Photos and face encodings are stored unencrypted in the backend's data
          folder until removed here, and alert snapshots may be sent to Telegram.
        </p>
      </section>
    </div>
  );
}
