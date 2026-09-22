import { useEffect, useRef, useState } from 'react';
import { Lock } from 'lucide-react';
import { apiFetch, setToken } from '../api/client.js';
import { useMountedRef } from '../hooks/useMountedRef.js';

// An Authorization header can only carry printable ASCII; fetch() throws on anything else.
const PRINTABLE_ASCII = /^[\x20-\x7E]+$/;

/**
 * Shown when the backend demands an API token (`/api/health.auth_required`, or any 401).
 * The candidate token is verified against a cheap authenticated endpoint BEFORE it is
 * stored, so a typo never ends up persisted in localStorage.
 */
export default function LoginGate({ onAuthenticated }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);
  const mountedRef = useMountedRef();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate) {
      setError('Enter the API token.');
      return;
    }
    if (!PRINTABLE_ASCII.test(candidate)) {
      setError('The token may only contain printable ASCII characters.');
      return;
    }

    setBusy(true);
    setError('');
    try {
      await apiFetch('/api/alerts', { token: candidate });
      setToken(candidate);
      if (mountedRef.current) onAuthenticated();
    } catch (submitError) {
      if (!mountedRef.current) return;
      setError(submitError.status === 401 ? 'That token was rejected.' : `Could not verify the token: ${submitError.message}`);
      setBusy(false);
    }
  };

  return (
    <section className="panel login-gate" aria-labelledby="login-title">
      <form onSubmit={submit} noValidate>
        <span className="login-icon" aria-hidden="true">
          <Lock size={22} />
        </span>
        <h2 id="login-title">API token required</h2>
        <p>
          This backend is protected. Enter the value of <code>CHANAKYA_API_TOKEN</code> from the
          server&apos;s environment. It is stored in this browser only.
        </p>
        <label htmlFor="login-token">API token</label>
        <input
          id="login-token"
          ref={inputRef}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'login-error' : undefined}
        />
        {error && (
          <p id="login-error" className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? 'Verifying...' : 'Unlock dashboard'}
        </button>
      </form>
    </section>
  );
}
