/**
 * Resolves the backend API base URL.
 * Priority: localStorage['gw_flask_url'] (set by the backend's /init redirect handoff)
 *           > VITE_API_BASE_URL build-time env var
 *           > current page origin
 */
export function getApiBase() {
  return (
    localStorage.getItem('gw_flask_url') || import.meta.env.VITE_API_BASE_URL || window.location.origin
  );
}
