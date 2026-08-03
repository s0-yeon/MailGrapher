import { bootstrapApp } from '../main-app.js';
import { getApiBase } from '../utils/apiBase.js';
import '../scss/pages/imap-collect.scss';

bootstrapApp('imap-collect');

function now() {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── 수집 개수 "사용자 지정" 선택 시 입력칸 노출 ──
function toggleCustomLimit() {
  const select = document.getElementById('collect-limit');
  const customInput = document.getElementById('collect-limit-custom');
  customInput.style.display = select.value === 'custom' ? '' : 'none';
}

// ── 프리셋 적용 ──
function applyPreset(el) {
  document.querySelectorAll('.gw-preset-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');

  const host = el.dataset.host;
  const port = el.dataset.port;
  const domain = el.dataset.domain || '';
  document.getElementById('imap-host').value = host;
  document.getElementById('imap-port').value = port;

  // 이메일 칸: 다른 프리셋으로 바꾸면 이전에 입력한 아이디는 지우고 "@도메인"만 새로 채움
  const userInput = document.getElementById('imap-user');
  if (domain) {
    userInput.value = '@' + domain;
    userInput.focus();
    // focus() 직후 브라우저가 자체적으로 커서를 맨 뒤로 보내는 경우가 있어서,
    // 그 동작이 끝난 다음 틱에 커서 위치를 다시 맨 앞으로 강제 설정함
    setTimeout(() => userInput.setSelectionRange(0, 0), 0);
  } else {
    userInput.value = '';
  }

  // 다른 서비스로 바꾸면 이전 계정용 비밀번호는 의미가 없으니 같이 비움
  document.getElementById('imap-pass').value = '';
}

// ── 폴더 토글 ──
function toggleFolder(checkbox) {
  const item = checkbox.closest('.gw-folder-item');
  if (checkbox.checked) {
    item.classList.add('checked');
  } else {
    item.classList.remove('checked');
  }
}

// ── 선택된 폴더 목록 반환 ──
function getSelectedFolders() {
  return Array.from(document.querySelectorAll('.gw-folder-item input[type="checkbox"]:checked'))
    .map(cb => cb.value);
}

// ── 폴더 목록 렌더링 (서버가 실제 조회한 폴더명으로 체크박스 생성) ──
function renderFolderList(folders) {
  const container = document.getElementById('folder-list');
  const selectAllBtn = document.getElementById('select-all-btn');
  container.innerHTML = '';

  if (!folders || folders.length === 0) {
    const empty = document.createElement('span');
    empty.className = 'gw-folder-empty';
    empty.textContent = '폴더를 찾을 수 없습니다.';
    container.appendChild(empty);
    selectAllBtn.style.display = 'none';
    return;
  }

  folders.forEach(folder => {
    const isInbox = folder.toUpperCase() === 'INBOX';

    const label = document.createElement('label');
    label.className = 'gw-folder-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = folder;
    checkbox.checked = false;
    checkbox.addEventListener('change', () => toggleFolder(checkbox));

    const icon = document.createElement('i');
    icon.className = isInbox ? 'bi bi-inbox' : 'bi bi-folder';

    const span = document.createElement('span');
    span.className = 'gw-folder-label';
    span.textContent = folder;

    label.appendChild(checkbox);
    label.appendChild(icon);
    label.appendChild(span);
    container.appendChild(label);
  });

  selectAllBtn.style.display = '';
  selectAllBtn.textContent = '전체 선택';
}

// ── 폴더 전체 선택/해제 토글 ──
function toggleSelectAll() {
  const checkboxes = document.querySelectorAll('#folder-list input[type="checkbox"]');
  if (checkboxes.length === 0) return;

  const allChecked = Array.from(checkboxes).every(cb => cb.checked);
  checkboxes.forEach(cb => {
    cb.checked = !allChecked;
    toggleFolder(cb);
  });

  document.getElementById('select-all-btn').textContent = allChecked ? '전체 선택' : '전체 해제';
}

// ── 실제 IMAP 서버에 로그인해서 폴더 목록 조회 ──
async function listFolders() {
  const flaskUrl = getApiBase();
  const host = document.getElementById('imap-host').value.trim();
  const port = parseInt(document.getElementById('imap-port').value) || 993;
  const ssl = document.getElementById('imap-ssl').value === 'true';
  const user = document.getElementById('imap-user').value.trim();
  const pass = document.getElementById('imap-pass').value;

  const btn = document.getElementById('list-folders-btn');
  const hint = document.getElementById('folder-list-hint');

  if (!host) { alert('IMAP 호스트를 입력하세요.'); return; }
  if (!user) { alert('이메일 주소를 입력하세요.'); return; }
  if (!pass) { alert('앱 비밀번호를 입력하세요.'); return; }
  if (!flaskUrl) { alert('Flask 서버 URL이 설정되지 않았습니다.\n/init 페이지를 먼저 방문하세요.'); return; }

  btn.disabled = true;
  hint.style.color = '#73879C';
  hint.textContent = '폴더 목록을 불러오는 중...';

  try {
    const res = await fetch(`${flaskUrl}/imap-list-folders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, ssl, user, password: pass })
    });

    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error(data.error || `서버 오류 (${res.status})`);
    }

    renderFolderList(data.folders || []);
    hint.style.color = '#1a9e6e';
    hint.textContent = `${data.folders.length}개 폴더를 찾았습니다.`;

  } catch (err) {
    hint.style.color = '#a32d2d';
    hint.textContent = `❌ ${err.message}`;
    console.error('[imap-list-folders]', err);
  } finally {
    btn.disabled = false;
  }
}

// ── 로그 추가 ──
function addLog(msg, type = '') {
  const body = document.getElementById('log-body');
  const empty = document.getElementById('log-empty');
  if (empty) empty.remove();

  const line = document.createElement('div');
  line.className = 'gw-log-line';
  line.innerHTML = `
    <span class="gw-log-ts">${now()}</span>
    <span class="gw-log-msg ${type}">${msg}</span>
  `;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

// ── 상태 배지 업데이트 ──
function setStatus(status, label) {
  const badge = document.getElementById('log-status-badge');
  const dot = document.getElementById('log-status-dot');
  const text = document.getElementById('log-status-text');
  badge.className = `gw-status-badge ${status}`;
  dot.className = `gw-status-dot ${status === 'running' ? 'running' : ''}`;
  text.textContent = label;
}

function setProgress(pct) {
  document.getElementById('log-progress-bar').style.width = pct + '%';
}

// ── 수집 시작 ──
async function startCollect() {
  const flaskUrl = getApiBase();
  const host = document.getElementById('imap-host').value.trim();
  const port = parseInt(document.getElementById('imap-port').value) || 993;
  const ssl = document.getElementById('imap-ssl').value === 'true';
  const user = document.getElementById('imap-user').value.trim();
  const pass = document.getElementById('imap-pass').value;
  // "0"(전체)은 falsy라서 `|| 100`으로 처리하면 100으로 덮어써지는 버그가 있었음 → 명시적으로 분기
  const limitRaw = document.getElementById('collect-limit').value;
  const limit = limitRaw === 'custom'
    ? (parseInt(document.getElementById('collect-limit-custom').value) || 0)
    : (limitRaw === '' ? 100 : parseInt(limitRaw));
  const syncMode = document.getElementById('sync-mode').value;
  const folders = getSelectedFolders();

  // 입력 검증
  if (!host) { alert('IMAP 호스트를 입력하세요.'); return; }
  if (!user) { alert('이메일 주소를 입력하세요.'); return; }
  if (!pass) { alert('앱 비밀번호를 입력하세요.'); return; }
  if (limitRaw === 'custom' && limit <= 0) { alert('수집 개수를 입력하세요.'); return; }
  if (folders.length === 0) { alert('수집할 폴더를 하나 이상 선택하세요.'); return; }
  if (!flaskUrl) { alert('Flask 서버 URL이 설정되지 않았습니다.\n/init 페이지를 먼저 방문하세요.'); return; }

  // UI: 수집 중 상태
  const btn = document.getElementById('collect-btn');
  const spinner = document.getElementById('collect-spinner');
  const icon = document.getElementById('collect-icon');
  const hint = document.getElementById('collect-hint');

  btn.disabled = true;
  spinner.classList.add('visible');
  icon.style.display = 'none';
  hint.textContent = '서버에 연결 중...';

  // 로그 패널 표시
  document.getElementById('log-panel').classList.add('visible');
  document.getElementById('result-row').style.display = 'none';

  // 로그 초기화
  const body = document.getElementById('log-body');
  body.innerHTML = '';
  setStatus('running', '수집 중');
  setProgress(5);

  addLog(`IMAP 연결 시작: ${host}:${port} (SSL: ${ssl})`);
  addLog(`계정: ${user}`);
  addLog(`폴더: ${folders.join(', ')}`);
  addLog(`수집 개수: ${limit === 0 ? '전체' : limit + '개'} / 모드: ${syncMode}`);

  try {
    setProgress(20);
    addLog('Flask 서버에 수집 요청 전송 중...');

    const res = await fetch(`${flaskUrl}/imap-collect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host, port, ssl, user, password: pass,
        folders, limit, sync_mode: syncMode,
        user_id: user
      })
    });

    setProgress(60);

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`서버 오류 (${res.status}): ${err.slice(0, 200)}`);
    }

    const data = await res.json();

    if (!data.ok) {
      throw new Error(data.error || '알 수 없는 오류');
    }

    // 이후 대시보드(index.html 등)가 이 값을 user_id로 사용한다.
    localStorage.setItem('gw_user_id', user);

    setProgress(100);
    setStatus('done', '완료');
    addLog(`✅ 수집 완료`, 'success');
    addLog(`수집: ${data.added_count}개 / 중복 스킵: ${data.skipped_count}개`, 'success');
    if (data.job_id) {
      addLog(`인덱싱 job_id: ${data.job_id} — 인덱싱이 백그라운드에서 실행됩니다.`, 'info');
    }

    // 결과 요약 표시
    document.getElementById('result-added').textContent = data.added_count ?? 0;
    document.getElementById('result-skipped').textContent = data.skipped_count ?? 0;
    document.getElementById('result-row').style.display = 'flex';

    hint.textContent = `완료: ${data.added_count}개 수집됨`;

  } catch (err) {
    setStatus('failed', '실패');
    setProgress(0);
    addLog(`❌ ${err.message}`, 'error');
    hint.textContent = '수집 실패. 로그를 확인하세요.';
    console.error('[imap-collect]', err);
  } finally {
    btn.disabled = false;
    spinner.classList.remove('visible');
    icon.style.display = '';
  }
}

// ── 이벤트 바인딩 ──
document.querySelectorAll('.gw-preset-chip[data-host]').forEach(chip => {
  chip.addEventListener('click', () => applyPreset(chip));
});
document.getElementById('collect-limit').addEventListener('change', toggleCustomLimit);
document.getElementById('list-folders-btn').addEventListener('click', listFolders);
document.getElementById('select-all-btn').addEventListener('click', toggleSelectAll);
document.getElementById('collect-btn').addEventListener('click', startCollect);

// ── 초기화 ──
// URL 파라미터에서 user_id 저장
const params = new URLSearchParams(location.search);
const gid = params.get('user_id');
if (gid) {
  localStorage.setItem('gw_user_id', gid);
  document.getElementById('imap-user').value = gid;
}

const flaskUrlParam = params.get('flask_url');
if (flaskUrlParam) localStorage.setItem('gw_flask_url', decodeURIComponent(flaskUrlParam));

// gw_user_id는 이제 "마지막으로 조회한 계정"이라는 의미로 쓰이므로(계정 선택기 도입),
// 새 계정을 추가하는 이 화면의 로그인 입력칸을 이 값으로 자동 채우지 않는다.
const savedId = localStorage.getItem('gw_user_id');
if (savedId) {
  const nameEl = document.getElementById('google-profile-name');
  if (nameEl) nameEl.textContent = savedId.split('@')[0];
}

// 기본 활성 프리셋(Gmail)의 "@gmail.com"도 클릭했을 때와 동일하게 커서를 맨 앞에 둠
const userInput = document.getElementById('imap-user');
if (userInput.value.startsWith('@')) {
  userInput.focus();
  setTimeout(() => userInput.setSelectionRange(0, 0), 0);
}
