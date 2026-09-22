import { useEffect, useRef } from 'react';

/**
 * Ref that is true while the component is mounted. Event-handler driven requests (button
 * clicks) have no effect cleanup to abort them, so they check this before touching state
 * or calling parent callbacks once their promise settles.
 */
export function useMountedRef() {
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  return mountedRef;
}
