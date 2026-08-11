// bootstrap JS, main.scss, security, i18n 등 전역 세팅은 그대로 재사용 (side-effect import).
// renderHeader/renderFooter(옛 innerHTML 방식)는 더 이상 안 씀 — HomeApp.jsx가 대신 그림.
import '../main-app.js';
import { mountHomeApp } from '../components/HomeApp.jsx';
import '../scss/pages/home.scss';
import '../styles/tailwind.css';

mountHomeApp('home-app-root');

/* ── URL 파라미터 & 이름 처리 ── */
(function() {
  const params = new URLSearchParams(window.location.search);
  const nameParam = params.get('name');
  const name = nameParam ? decodeURIComponent(nameParam) : (sessionStorage.getItem('gw_user_name') || '-');
  if (nameParam) sessionStorage.setItem('gw_user_name', decodeURIComponent(nameParam));
  const gmailIdParam = params.get('gmail_id');
  if (gmailIdParam) localStorage.setItem('gw_user_id', decodeURIComponent(gmailIdParam));
const flaskUrlParam = params.get('flask_url');
if (flaskUrlParam) localStorage.setItem('gw_flask_url', decodeURIComponent(flaskUrlParam));
// Flask에서 직접 열릴 때 자동으로 ngrok URL 저장
if (!window.location.origin.includes('script.google.com')) {
  localStorage.setItem('gw_flask_url', window.location.origin);
}
  window.currentUserName = name;
  const pnEl = document.getElementById('google-profile-name');
  if (pnEl) pnEl.textContent = name;
})();

/* 등장 애니메이션(.gw-anim → .visible)은 이제 HeroOrbit.jsx 안의 useEffect가 처리함 */
