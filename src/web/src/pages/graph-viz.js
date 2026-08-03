import { bootstrapApp } from '../main-app.js';
import { initAccountPicker } from '../features/accountPicker.js';
import '../scss/pages/graph-viz.scss';

bootstrapApp('graph-viz');

// 이름/gmail_id 처리
const params = new URLSearchParams(window.location.search);
const nameParam = params.get('name');
const name = nameParam
  ? decodeURIComponent(nameParam)
  : (sessionStorage.getItem('gw_user_name') || '-');
if (nameParam) sessionStorage.setItem('gw_user_name', decodeURIComponent(nameParam));

const gmailIdParam = params.get('gmail_id');
if (gmailIdParam) localStorage.setItem('gw_user_id', decodeURIComponent(gmailIdParam));
const flaskUrlParam = params.get('flask_url');
if (flaskUrlParam) localStorage.setItem('gw_flask_url', decodeURIComponent(flaskUrlParam));

const profileNameEl = document.getElementById('google-profile-name');
if (profileNameEl) profileNameEl.textContent = name;

// 그래프 로드
function _loadScript(src) {
  return new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = src; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
}

// d3 + graph-render.js는 계정 목록 조회와 병렬로 미리 로드해두고, 렌더링 직전에만 대기한다
var rendererReady = _loadScript('https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js')
  .then(function() { return _loadScript('/graph-render.js'); });

// user_id로 해당 계정의 그래프 데이터를 불러와 그린다.
// 계정 전환 시에도 페이지 새로고침 없이 이 함수만 다시 호출해 그 자리에서 다시 그린다.
function loadGraphData(userId) {
  var svg = document.getElementById('graph');
  if (!userId) {
    console.warn('[graph] user_id 없음 → 그래프 로드 생략');
    svg.innerHTML = '';
    return Promise.resolve();
  }
  return fetch('/graph-data?user_id=' + encodeURIComponent(userId))
    .then(function(res) { return res.json(); })
    .then(function(data) {
      if (!data || !Array.isArray(data.nodes)) {
        console.warn('[graph] 그래프 데이터 없음:', data && data.error);
        svg.innerHTML = '';
        return;
      }
      return rendererReady.then(function() {
        svg.innerHTML = '';
        renderGraph(svg, data);
      });
    })
    .catch(function(err) { console.error('[graph] 로드 실패:', err); });
}

window.addEventListener('load', function() {
  initAccountPicker(document.getElementById('account-picker-mount'), loadGraphData)
    .then(function(effectiveUserId) { return loadGraphData(effectiveUserId); });
});
