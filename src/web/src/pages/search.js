import { bootstrapApp } from '../main-app.js';
import { getApiBase } from '../utils/apiBase.js';
import '../scss/pages/search.scss';

bootstrapApp('search');

const FLASK_URL = getApiBase();

// 검색 모드 상수
const RECENT_KEY = 'gw_recent_searches';
const MAX_RECENT = 8;

// URL 파라미터 처리
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
window.currentUserName = name;

// 검색어 URL 파라미터
const urlQuery = params.get('q');
if (urlQuery) document.getElementById('search-input').value = decodeURIComponent(urlQuery);

// ── 공통 유틸 ──
function escapeHtml(str) {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escapeAttr(str) {
  return String(str || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ══════════════════════════════════════
// 검색 모드 기능
// ══════════════════════════════════════

function getRecents() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; }
}
function saveRecent(q) {
  let recents = getRecents().filter(r => r !== q);
  recents.unshift(q);
  if (recents.length > MAX_RECENT) recents = recents.slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_KEY, JSON.stringify(recents));
}
function removeRecent(q) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(getRecents().filter(r => r !== q)));
  renderRecents();
}
function clearRecents() { localStorage.removeItem(RECENT_KEY); renderRecents(); }

function renderRecents() {
  const recents = getRecents();
  const bar = document.getElementById('recent-searches-bar');
  const tagsEl = document.getElementById('recent-tags');
  if (recents.length === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  tagsEl.innerHTML = recents.map(r => `
    <span class="gw-recent-tag" data-q="${escapeAttr(r)}">
      <i class="fas fa-history" style="font-size:0.72rem; color:#aaa;"></i>
      ${escapeHtml(r)}
      <span class="gw-tag-del" data-del="${escapeAttr(r)}" title="삭제">×</span>
    </span>
  `).join('');
  tagsEl.querySelectorAll('.gw-recent-tag').forEach(tag => {
    tag.addEventListener('click', function(e) {
      if (e.target.classList.contains('gw-tag-del')) return;
      const q = this.dataset.q;
      document.getElementById('search-input').value = q;
      runSearch(q);
    });
  });
  tagsEl.querySelectorAll('.gw-tag-del').forEach(btn => {
    btn.addEventListener('click', function(e) { e.stopPropagation(); removeRecent(this.dataset.del); });
  });
}

document.getElementById('clear-recent').addEventListener('click', clearRecents);
renderRecents();

function doSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  runSearch(q);
}
document.getElementById('search-btn').addEventListener('click', doSearch);
document.getElementById('search-input').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

function showLoading(q) {
  document.getElementById('result-container').innerHTML = `
    <div class="gw-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
    <div class="gw-loading"><div class="gw-spinner"></div><span>메일을 분석하고 있습니다...</span></div>
  `;
}
function showResult(q, text, sourceIds) {
  let sourceHtml = '';
  if (sourceIds && sourceIds.length > 0) {
    const items = sourceIds.map(id =>
      `<a class="gw-source-btn" href="https://mail.google.com/mail/u/0/#all/${escapeAttr(id)}" target="_blank" rel="noopener noreferrer">
        <i class="fas fa-envelope"></i> 메일로 확인하기
      </a>`
    ).join('');
    sourceHtml = `<div class="gw-source-emails"><div class="gw-source-label">근거 메일</div><div class="gw-source-btns">${items}</div></div>`;
  }
  document.getElementById('result-container').innerHTML = `
    <div class="gw-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
    <div class="gw-result-card">${escapeHtml(text)}</div>
    ${sourceHtml}
  `;
}
function showError(q, msg) {
  document.getElementById('result-container').innerHTML = `
    <div class="gw-query-label">검색어: <strong>${escapeHtml(q)}</strong></div>
    <div class="gw-error"><i class="fas fa-exclamation-circle me-2"></i>${escapeHtml(msg)}</div>
  `;
}

async function pollJob(jobId, q, interval = 2000, maxTries = 60) {
  for (let i = 0; i < maxTries; i++) {
    await new Promise(r => setTimeout(r, interval));
    try {
      const res = await fetch(`${FLASK_URL}/job-status/${jobId}`);
      const data = await res.json();
      if (data.status === 'done') { showResult(q, data.result || '결과가 없습니다.', data.source_ids || []); return; }
      if (data.status === 'error') { showError(q, data.result || '오류가 발생했습니다.'); return; }
    } catch (e) { showError(q, '서버 연결에 실패했습니다.'); return; }
  }
  showError(q, '응답 시간이 초과되었습니다. 다시 시도해주세요.');
}

async function runSearch(q) {
  showLoading(q);
  saveRecent(q);
  renderRecents();
  const gmailId = localStorage.getItem('gw_user_id') || '';
  try {
    const res = await fetch(`${FLASK_URL}/run-query-async`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: q, resType: 'structed', user_id: gmailId })
    });
    const data = await res.json();
    if (!data.jobId) { showError(q, '검색 요청에 실패했습니다.'); return; }
    await pollJob(data.jobId, q);
  } catch (e) {
    showError(q, '서버에 연결할 수 없습니다. Flask 서버가 실행 중인지 확인하세요.');
  }
}

if (urlQuery && urlQuery.trim()) runSearch(decodeURIComponent(urlQuery));
