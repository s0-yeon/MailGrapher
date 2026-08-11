import { bootstrapApp } from '../main-app.js';
import { initAccountPicker } from '../features/accountPicker.js';
import '../scss/pages/mytime.scss';

bootstrapApp('mytime');

const userIdPromise = initAccountPicker(document.getElementById('account-picker-mount'));

(async function () {
  const track = document.getElementById('track');
  const gmailId = (await userIdPromise) || '';

  /* ── 실제 /mail-summaries 결과를 그대로 사용 ── */
  async function fetchSummaries(type) {
    try {
      const res = await fetch('/mail-summaries', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user_id: gmailId, type })
      });
      if (!res.ok) return {};
      const j = await res.json();
      return j[type] || {};
    } catch (e) {
      console.error(`mail-summaries(${type}) 오류:`, e);
      return {};
    }
  }

  const MONTH_DATA = await fetchSummaries('monthly');
  const YEAR_DATA  = await fetchSummaries('yearly');

  const ALL_KEYS  = Object.keys(MONTH_DATA).sort();
  const YEAR_KEYS = Object.keys(YEAR_DATA).sort();

  if (!ALL_KEYS.length) {
    track.innerHTML = '<div style="color:#8fb5a9;font-size:.85rem;padding:20px 0;">아직 생성된 요약이 없습니다. 인덱싱을 먼저 실행해주세요.</div>';
    return;
  }

  /* ── 포인터 전체 범위 ── */
  const FIRST_NUM = monthToNum(ALL_KEYS[0]);
  const LAST_NUM  = monthToNum(ALL_KEYS[ALL_KEYS.length-1]);
  const TOTAL     = LAST_NUM - FIRST_NUM;

  function monthToNum(k) { const [y,m]=k.split('-').map(Number); return y*12+m; }
  function monthToPct(k) { return (monthToNum(k)-FIRST_NUM)/TOTAL; }
  function yearToPct(y)  { return (Number(y)*12+1-FIRST_NUM)/TOTAL; }

  /* ── 상태 ── */
  let mode = 'month';
  let centerIdx = 2; // ALL_KEYS index (월별) or YEAR_KEYS index (연별)
  let pinnedKey = null; // 클릭으로 고정된 키

  const WIN = { month:8, year:5 };

  function getWindowKeys() {
    const keys = mode==='month' ? ALL_KEYS : YEAR_KEYS;
    const win  = WIN[mode];
    let start = Math.max(0, centerIdx - Math.floor(win/2));
    start = Math.min(start, keys.length - win);
    start = Math.max(0, start);
    return keys.slice(start, start + win);
  }

  /* ── 렌더 ── */
  function render() {
    const keys = getWindowKeys();
    const data = mode==='month' ? MONTH_DATA : YEAR_DATA;
    const track = document.getElementById('track');
    track.innerHTML = '';
    pinnedKey = null;
    document.getElementById('infoPanel').classList.remove('pinned');
    hidePanel();

    keys.forEach((k) => {
      const d = data[k];
      if (!d) return;

      const col = document.createElement('div');
      col.className = 'mt-node-col';
      col.dataset.key = k;

      const dot = document.createElement('div');
      dot.className = 'mt-dot';

      const lbl = document.createElement('div');
      lbl.className = 'mt-node-label';
      lbl.textContent = mode==='month'
        ? `${k.slice(0,4)}.${k.slice(5)}`
        : `${k}년`;

      const cnt = document.createElement('div');
      cnt.className = 'mt-node-count';
      cnt.textContent = d.count ? `${d.count.toLocaleString()}건` : '';

      col.appendChild(dot);
      col.appendChild(lbl);
      col.appendChild(cnt);
      track.appendChild(col);

      col.addEventListener('mouseenter', () => { if (!pinnedKey) showPanel(col, k, d); });
      col.addEventListener('mouseleave', () => { if (!pinnedKey) hidePanel(); });
      col.addEventListener('click', () => {
        if (pinnedKey === k) {
          // 같은 노드 재클릭 → 고정 해제
          pinnedKey = null;
          col.classList.remove('pinned');
          document.getElementById('infoPanel').classList.remove('pinned');
          hidePanel();
        } else {
          // 새 노드 클릭 → 고정 (지금 보는 시점 · 슬라이더 커서 · 좌측 메일 목록도 함께 동기화)
          pinnedKey = k;
          document.querySelectorAll('.mt-node-col').forEach(c => c.classList.remove('pinned'));
          col.classList.add('pinned');
          showPanel(col, k, d);
          document.getElementById('infoPanel').classList.add('pinned');
          centerIdx = (mode==='month' ? ALL_KEYS : YEAR_KEYS).indexOf(k);
          updatePointerCursor();
        }
      });
    });

    updatePointerWindow();
  }

  /* ── 인포 패널 ── */
  function showPanel(col, key, d) {
    document.querySelectorAll('.mt-node-col').forEach(c => c.classList.toggle('active', c===col));

    document.getElementById('panelPeriod').textContent =
      mode==='month' ? `${key.slice(0,4)}년 ${key.slice(5)}월` : `${key}년`;
    document.getElementById('panelCount').innerHTML =
      d.count ? `<strong>${d.count.toLocaleString()}</strong>건 &nbsp;·&nbsp; ${d.threads}개 대화` : '';
    document.getElementById('panelSummary').textContent = d.summary;

    const cc = document.getElementById('panelContacts');
    cc.innerHTML = '';
    d.contacts.forEach(c => {
      const el = document.createElement('div');
      el.className = 'mt-panel-contact';
      el.textContent = c;
      cc.appendChild(el);
    });

    document.getElementById('infoPanel').classList.add('show');
  }

  function hidePanel() {
    document.getElementById('infoPanel').classList.remove('show');
    document.querySelectorAll('.mt-node-col').forEach(c=>c.classList.remove('active'));
  }

  /* ── 모드 토글 ── */
  document.querySelectorAll('.mt-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      mode = btn.dataset.mode;
      centerIdx = mode==='month' ? 3 : 0;
      document.querySelectorAll('.mt-mode-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      render();
      updatePointerCursor();
    });
  });

  /* ── 포인터 ── */
  function buildPointer() {
    const track = document.getElementById('pointerTrack');
    track.querySelectorAll('.mt-pm').forEach(el=>el.remove());

    ALL_KEYS.forEach((k, idx) => {
      const pm = document.createElement('div');
      pm.className = 'mt-pm';
      pm.style.left = `${monthToPct(k)*100}%`;
      pm.addEventListener('click', e => {
        e.stopPropagation();
        centerIdx = mode==='month' ? idx : Math.floor(idx/(ALL_KEYS.length/YEAR_KEYS.length));
        centerIdx = Math.max(0, Math.min(
          (mode==='month' ? ALL_KEYS : YEAR_KEYS).length - 1, centerIdx));
        updatePointerCursor(); render();
      });
      track.insertBefore(pm, document.getElementById('pointerWindow'));
    });

    const axis = document.getElementById('pointerAxis');
    axis.innerHTML = '';
    YEAR_KEYS.forEach(y => {
      const pct = Math.max(0, Math.min(98, yearToPct(y)*100));
      const lbl = document.createElement('div');
      lbl.className = 'mt-pa-lbl';
      lbl.textContent = y;
      lbl.style.left = pct+'%';
      axis.appendChild(lbl);
    });

    updatePointerCursor();
    updatePointerWindow();
  }

  function updatePointerCursor() {
    const keys = mode==='month' ? ALL_KEYS : YEAR_KEYS;
    const k = keys[Math.max(0,Math.min(keys.length-1,centerIdx))];
    const pct = mode==='month' ? monthToPct(k)*100 : yearToPct(k)*100;
    document.getElementById('pointerCursor').style.left = Math.max(0,Math.min(100,pct))+'%';

    const nowEl = document.getElementById('mtSideNow');
    if (nowEl) {
      nowEl.textContent = mode==='month' ? `${k.slice(0,4)}년 ${k.slice(5)}월` : `${k}년`;
    }
  }

  function updatePointerWindow() {
    const wKeys = getWindowKeys();
    if (!wKeys.length) return;
    const s = mode==='month' ? monthToPct(wKeys[0]) : yearToPct(wKeys[0]);
    const e = mode==='month' ? monthToPct(wKeys[wKeys.length-1]) : yearToPct(wKeys[wKeys.length-1]) + 12/TOTAL;
    const win = document.getElementById('pointerWindow');
    win.style.left  = `${Math.max(0,s*100)}%`;
    win.style.width = `${Math.min(100,(e-s)*100)}%`;
  }

  document.getElementById('pointerTrack').addEventListener('click', e => {
    if (e.target.classList.contains('mt-pm')) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct  = (e.clientX - rect.left) / rect.width;
    const totalIdx = Math.round(pct * ALL_KEYS.length);
    if (mode==='month') {
      centerIdx = Math.max(0, Math.min(ALL_KEYS.length-1, totalIdx));
    } else {
      centerIdx = Math.max(0, Math.min(YEAR_KEYS.length-1, Math.floor(totalIdx / (ALL_KEYS.length/YEAR_KEYS.length))));
    }
    updatePointerCursor(); render();
  });

  /* ── 좌측 사이드바: "{아이디}'s Time" 타이틀 + 전체 타임라인 기간 ── */
  function initSideProfile() {
    const myName  = sessionStorage.getItem('gw_user_name') || '나';
    const titleEl = document.getElementById('mtSideTitle');
    if (titleEl) titleEl.innerHTML = `${myName}<span> Time</span>`;

    const rangeEl = document.getElementById('mtSideRange');
    if (rangeEl && ALL_KEYS.length) {
      const fmt = k => `${k.slice(0,4)}.${k.slice(5)}`;
      rangeEl.textContent = `전체 타임라인 ${fmt(ALL_KEYS[0])} ~ ${fmt(ALL_KEYS[ALL_KEYS.length-1])}`;
    }
  }

  /* ── "나" 아바타: My People과 동일하게 캐시 우선 조회 후 없으면 생성.
     타임슬라이더 커서와 우측 사이드바 프로필, 두 군데에 동시에 채워 넣는다. ── */
  async function initSelfAvatar() {
    if (!gmailId) return;
    const applyAvatar = url => {
      if (!url) return;
      const cursorEl = document.getElementById('pointerCursor');
      const sideEl   = document.getElementById('mtSideAvatar');
      if (cursorEl) cursorEl.innerHTML = `<img src="${url}" alt="나">`;
      if (sideEl)   sideEl.innerHTML   = `<img src="${url}" alt="나">`;
    };
    try {
      const cacheRes = await fetch('/self-avatar', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user_id: gmailId })
      });
      if (cacheRes.ok) {
        const j = await cacheRes.json();
        if (j.url) { applyAvatar(j.url); return; }
      }
      const myName = sessionStorage.getItem('gw_user_name') || '나';
      const genRes = await fetch('/generate-self-avatar', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user_id: gmailId, name: myName })
      });
      if (genRes.ok) {
        const j = await genRes.json();
        if (j.url) applyAvatar(j.url);
      }
    } catch (e) {
      console.error('내 아바타 로드 오류:', e);
    }
  }

  /* ── 초기화 ── */
  buildPointer();
  render();
  initSideProfile();
  initSelfAvatar();
})();
