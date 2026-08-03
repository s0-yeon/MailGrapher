import { bootstrapApp } from '../main-app.js';
import { initAccountPicker } from '../features/accountPicker.js';
import '../scss/pages/recap.scss';

bootstrapApp('recap');

// 이름/user_id 처리
const params = new URLSearchParams(window.location.search);
const nameParam = params.get('name');
const name = nameParam
  ? decodeURIComponent(nameParam)
  : (sessionStorage.getItem('gw_user_name') || '-');
if (nameParam) sessionStorage.setItem('gw_user_name', decodeURIComponent(nameParam));

const gmailIdParam = params.get('gmail_id');
if (gmailIdParam) localStorage.setItem('gw_user_id', decodeURIComponent(gmailIdParam));

const profileNameEl = document.getElementById('google-profile-name');
if (profileNameEl) profileNameEl.textContent = name;

const userIdPromise = initAccountPicker(document.getElementById('account-picker-mount'));

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function initials(nameStr) {
  const parts = nameStr.trim().split(/\s+/);
  return parts.length >= 2
    ? (parts[0][0] + parts[1][0]).toUpperCase()
    : nameStr.slice(0, 2).toUpperCase();
}

const AVATAR_COLORS = [
  ['#fcd34d','#f59e0b'], ['#a5b4fc','#818cf8'],
  ['#86efac','#4ade80'], ['#f9a8d4','#ec4899'],
  ['#67e8f9','#06b6d4'], ['#fca5a5','#ef4444'],
];

/* ids: { badge, topEl, barList, loadingEl, errorEl, contentEl }
   field: 'received' | 'sent'
   tag: 1위 뱃지 텍스트, unit: 단위 텍스트 */
function renderMailStats(data, field, ids, tag, unit) {
  const sorted = Object.entries(data)
    .map(([email, v]) => ({ email, name: v.name || email, count: v[field] || 0 }))
    .filter(x => x.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  document.getElementById(ids.loadingEl).style.display = 'none';

  if (sorted.length === 0) {
    const err = document.getElementById(ids.errorEl);
    err.style.display = ''; err.textContent = '데이터가 없습니다.';
    return;
  }

  const max = sorted[0].count;
  const top = sorted[0];

  // 히어로 서브타이틀 (received 기준으로만 업데이트)
  if (field === 'received') {
    document.getElementById('rcHeroSub').textContent = (name !== '-' ? name + '님의 ' : '') + '메일함 통계';
  }

  document.getElementById(ids.badge).textContent = sorted.length + '명';
  document.getElementById(ids.badge).style.display = '';

  const [c1, c2] = AVATAR_COLORS[0];
  document.getElementById(ids.topEl).innerHTML = `
    <div class="rc-rank1-card">
      <div class="rc-rank1-avatar" style="background:linear-gradient(135deg,${c1},${c2});">
        ${esc(initials(top.name))}
      </div>
      <div class="rc-rank1-info">
        <div class="rc-rank1-tag">🏆 ${tag}</div>
        <div class="rc-rank1-name">${esc(top.name)}</div>
        <div class="rc-rank1-email">${esc(top.email)}</div>
      </div>
      <div class="rc-rank1-count">
        <div class="rc-rank1-num">${top.count}</div>
        <div class="rc-rank1-unit">${unit}</div>
      </div>
    </div>`;

  document.getElementById(ids.barList).innerHTML = sorted.map((item, i) => {
    const rankClass = i === 0 ? 'rank1' : i === 1 ? 'rank2' : i === 2 ? 'rank3' : '';
    const rankLabel = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : (i + 1);
    const pct = max > 0 ? Math.round(item.count / max * 100) : 0;
    return `
      <li class="rc-bar-item">
        <div class="rc-bar-rank ${i < 3 ? 'top' : ''}">${rankLabel}</div>
        <div class="rc-bar-inner">
          <div class="rc-bar-name" title="${esc(item.email)}">${esc(item.name)}</div>
          <div class="rc-bar-track">
            <div class="rc-bar-fill ${rankClass}" data-pct="${pct}" data-scope="${ids.barList}"></div>
          </div>
        </div>
        <div class="rc-bar-count">${item.count}통</div>
      </li>`;
  }).join('');

  document.getElementById(ids.contentEl).style.display = '';

  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.querySelectorAll(`#${ids.barList} .rc-bar-fill`).forEach(el => {
      el.style.width = el.dataset.pct + '%';
    });
  }));
}

function renderSenderStats(data) {
  renderMailStats(data, 'received',
    { badge: 'rcSenderBadge', topEl: 'rcTopSender', barList: 'rcBarList',
      loadingEl: 'rcSenderLoading', errorEl: 'rcSenderError', contentEl: 'rcSenderContent' },
    'TOP RECEIVER', '통 받음');
  renderMailStats(data, 'sent',
    { badge: 'rcMySentBadge', topEl: 'rcTopMySent', barList: 'rcMySentBarList',
      loadingEl: 'rcMySentLoading', errorEl: 'rcMySentError', contentEl: 'rcMySentContent' },
    'TOP SENT', '통 보냄');
}

/* ── 워드 클라우드 색상 팔레트 ── */
const WC_COLORS = [
  '#1b4332','#2d6a4f','#40916c',
  '#e63946','#457b9d','#e07b39',
  '#7b2d8b','#1d6fa0','#b5451b',
  '#2c6e49',
];

function renderKeywordStats(data) {
  const keywords = (data.keywords || []).slice().sort((a, b) => b.count - a.count).slice(0, 10); /*키워드 갯수*/
  if (keywords.length === 0) return;

  const max = keywords[0].count;
  const min = keywords[keywords.length - 1].count;

  document.getElementById('rcKwBadge').textContent = keywords.length + '개 키워드';
  document.getElementById('rcKwBadge').style.display = '';

  const wrap = document.getElementById('rcKwCanvas');
  wrap.innerHTML = '';

  keywords.forEach((kw, idx) => {
    // log scale → 글자 크기 (14 ~ 46px)
    const norm = max === min ? 1 : Math.log1p(kw.count - min) / Math.log1p(max - min);
    const fs = Math.round(14 + norm * 32);
    const color = WC_COLORS[idx % WC_COLORS.length];

    const el = document.createElement('span');
    el.className = 'rc-wc-word';
    el.style.cssText = `font-size:${fs}px; color:${color}; transition-delay:${(idx * 0.06).toFixed(2)}s;`;
    el.title = `${kw.word}: ${kw.count}회`;
    el.innerHTML = `${esc(kw.word)}<sup class="rc-wc-count">${kw.count}</sup>`;
    wrap.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('show')));
  });
}

/* ── 친밀도 렌더 (DOMContentLoaded 밖에 선언) ── */
function renderAffinityStats(data) {
  const list = (Array.isArray(data) ? data : []).slice(0, 7);
  if (list.length === 0) return;

  const sorted = [...list].sort((a, b) => (b.affinity ?? 0) - (a.affinity ?? 0));
  const totalAffinity = sorted.reduce((sum, item) => sum + (item.affinity ?? 0), 0);

  const badge = document.getElementById('rcAfBadge');
  badge.textContent = sorted.length + '명';
  badge.style.display = '';

  const AF_COLORS = [
    '#ec4899','#a78bfa','#f97316',
    '#06b6d4','#10b981','#f59e0b','#ef4444',
  ];
  const RANK_LABELS = ['🥇','🥈','🥉'];

  // 중앙 숫자 업데이트
  const topScore = sorted[0].affinity ?? 0;
  document.getElementById('rcAfCenterNum').textContent = Math.round(topScore * 100) + '%';

  // SVG 도넛 차트 생성
  const svg = document.getElementById('rcAfDonutSvg');
  const radius = 82.5;
  const circumference = 2 * Math.PI * radius;

  let currentOffset = 0;

  sorted.forEach((item, i) => {
    const score = item.affinity ?? 0;
    const percentage = totalAffinity > 0 ? score / totalAffinity : 0;
    const segmentLength = circumference * percentage;
    const color = AF_COLORS[i % AF_COLORS.length];

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('class', 'rc-af-donut-segment');
    circle.setAttribute('cx', '100');
    circle.setAttribute('cy', '100');
    circle.setAttribute('r', radius.toString());
    circle.setAttribute('stroke', color);
    circle.setAttribute('stroke-dasharray', `${segmentLength} ${circumference}`);
    circle.setAttribute('stroke-dashoffset', (-currentOffset).toString());
    circle.style.transition = 'all 0.8s cubic-bezier(0.22, 1, 0.36, 1)';

    // 호버 효과
    circle.addEventListener('mouseenter', () => {
      document.querySelectorAll('.rc-af-legend-item').forEach((el, idx) => {
        if (idx === i) {
          el.style.background = 'rgba(240, 240, 244, 0.8)';
          el.style.transform = 'translateX(6px) scale(1.02)';
        } else {
          el.style.opacity = '0.5';
        }
      });
    });

    circle.addEventListener('mouseleave', () => {
      document.querySelectorAll('.rc-af-legend-item').forEach(el => {
        el.style.background = 'rgba(240, 240, 244, 0.3)';
        el.style.transform = 'translateX(0) scale(1)';
        el.style.opacity = '1';
      });
    });

    svg.appendChild(circle);
    currentOffset += segmentLength;
  });

  // 범례 생성
  document.getElementById('rcAfLegend').innerHTML = sorted.map((item, i) => {
    const score = item.affinity ?? 0;
    const color = AF_COLORS[i % AF_COLORS.length];
    const rankLabel = i < 3 ? RANK_LABELS[i] : (i + 1);
    const percentage = Math.round(score * 100);

    return `
      <div class="rc-af-legend-item" data-index="${i}">
        <div class="rc-af-legend-rank">${rankLabel}</div>
        <div class="rc-af-legend-color" style="background:${color};"></div>
        <div class="rc-af-legend-info">
          <div class="rc-af-legend-name">${esc(item.name || item.email)}</div>
          <div class="rc-af-legend-email">${esc(item.email || '')}</div>
        </div>
        <div class="rc-af-legend-score" style="color:${color};">${percentage}%</div>
      </div>`;
  }).join('');

  // 범례 호버 효과
  document.querySelectorAll('.rc-af-legend-item').forEach((el, idx) => {
    el.addEventListener('mouseenter', () => {
      const segments = document.querySelectorAll('.rc-af-donut-segment');
      segments.forEach((seg, i) => {
        if (i === idx) {
          seg.style.strokeWidth = '40';
          seg.style.filter = 'brightness(1.1)';
        } else {
          seg.style.opacity = '0.4';
        }
      });
    });

    el.addEventListener('mouseleave', () => {
      const segments = document.querySelectorAll('.rc-af-donut-segment');
      segments.forEach(seg => {
        seg.style.strokeWidth = '35';
        seg.style.filter = 'none';
        seg.style.opacity = '1';
      });
    });
  });

  // 애니메이션 트리거
  requestAnimationFrame(() => {
    const segments = document.querySelectorAll('.rc-af-donut-segment');
    segments.forEach(seg => {
      seg.style.strokeDashoffset = seg.getAttribute('stroke-dashoffset');
    });
  });
}

/* ── 동기화 통계 렌더링 ── */
function renderSyncStats(data) {
  // sync_time "2-30" → "2시간 30분"
  function fmtTime(t) {
    if (!t) return '—';
    const [h, m] = String(t).split('-');
    if (m === undefined) return h;
    return (parseInt(h) ? h + '시간 ' : '') + (parseInt(m) ? m : '');
  }
  // sync_update_date "2026-04-22" → "26.04.22"
  function fmtDate(d) {
    if (!d) return '—';
    const parts = String(d).split('-');
    if (parts.length === 3) return parts[0].slice(2) + '.' + parts[1] + '.' + parts[2];
    return d;
  }

  // 숫자 카운트업 애니메이션
  function countUp(el, target, duration = 900) {
    const start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(ease * target).toLocaleString();
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  const count = data.mail_count || 0;
  const countEl = document.getElementById('rcSyncCount');
  countUp(countEl, count);
  // 단위 표시 (애니메이션 끝나면 "통" 추가)
  setTimeout(() => { countEl.textContent = count.toLocaleString() + '통'; }, 940);

  document.getElementById('rcSyncTime').textContent = fmtTime(data.sync_time);
  document.getElementById('rcSyncDate').textContent = fmtDate(data.sync_update_date);
  document.getElementById('rcSyncLoading').style.display = 'none';
  document.getElementById('rcSyncContent').style.display = '';
}

/* ── 만족도 게이지 렌더링 ── */
function renderRatingStats(data) {
  const score = Math.min(100, Math.max(0, data.total_rating || 0));
  // 반원 둘레 = π * r = π * 80 ≈ 251.3
  const ARC = 251.3;
  const offset = ARC * (1 - score / 100);

  // 숫자 카운트업
  const numEl = document.getElementById('rcGaugeNum');
  const start = performance.now();
  function countTick(now) {
    const p = Math.min((now - start) / 1200, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    numEl.textContent = Math.round(ease * score);
    if (p < 1) requestAnimationFrame(countTick);
  }
  requestAnimationFrame(countTick);

  // 게이지 채우기
  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.getElementById('rcGaugeFill').style.strokeDashoffset = offset;
  }));

  // 별 표시 (20점 당 별 1개, 최대 5개)
  const stars = Math.round(score / 20);
  const starsEl = document.getElementById('rcGaugeStars');
  starsEl.innerHTML = '';
  let html = '';
  for (let i = 0; i < 5; i++) {
    html += `<span style="opacity:${i < stars ? 1 : 0.2};transition:opacity 0.3s ${i*0.12}s;">⭐</span>`;
  }
  // 별 순차 등장
  setTimeout(() => { starsEl.innerHTML = html; }, 400);

  // 레이블 문구
  const label = score >= 90 ? '매우 만족 🎉' : score >= 70 ? '만족 😊' : score >= 50 ? '보통 😐' : '개선 필요 😅';
  document.getElementById('rcGaugeLabel').textContent = label;

  document.getElementById('rcRatingLoading').style.display = 'none';
  document.getElementById('rcRatingContent').style.display = '';
}

async function postStat(endpoint, gmailId) {
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }, //내가 보내는게 json이야~
    body: JSON.stringify({ user_id: gmailId }) // json 객체 생성
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

document.addEventListener('DOMContentLoaded', async () => {
  const gmailId = await userIdPromise;

  if (!gmailId) {
    ['rcSenderLoading','rcKwLoading','rcAfLoading'].forEach(id => {
      document.getElementById(id).style.display = 'none';
    });
    ['rcSenderError','rcKwError','rcAfError'].forEach(id => {
      const el = document.getElementById(id);
      el.style.display = '';
      el.textContent = '인덱싱된 계정이 없습니다. 먼저 메일을 수집해주세요.';
    });
    return;
  }

  // 다섯 API 병렬 호출
  const [mailStatsResult, keywordResult, affinityResult, syncResult, ratingResult] = await Promise.allSettled([
    postStat('/mail-stats', gmailId),
    postStat('/keyword-stats', gmailId),
    postStat('/high_affinity_person_stats', gmailId),
    postStat('/mail_sync_stats', gmailId),
    postStat('/user_rating_stats', gmailId),
  ]);

  // ── 발신자/수신자 통계 ──
  renderSenderStats(mailStatsResult.status === 'fulfilled' ? (mailStatsResult.value.data || {}) : {});

  // ── 키워드 통계 ──
  {
    const kwData = keywordResult.status === 'fulfilled' ? keywordResult.value.data : null;
    document.getElementById('rcKwLoading').style.display = 'none';
    if (kwData && (kwData.keywords || []).length) {
      renderKeywordStats(kwData);
      document.getElementById('rcKwContent').style.display = '';
    } else {
      const err = document.getElementById('rcKwError');
      err.style.display = ''; err.textContent = '데이터가 없습니다.';
    }
  }

  // ── 친밀도 통계 ──
  {
    const afData = affinityResult.status === 'fulfilled' ? affinityResult.value.data : null;
    document.getElementById('rcAfLoading').style.display = 'none';
    if (Array.isArray(afData) && afData.length) {
      renderAffinityStats(afData);
      document.getElementById('rcAfContent').style.display = '';
    } else {
      const err = document.getElementById('rcAfError');
      err.style.display = ''; err.textContent = '데이터가 없습니다.';
    }
  }

  // ── 동기화 통계 ──
  if (syncResult.status === 'fulfilled' && syncResult.value.data) {
    renderSyncStats(syncResult.value.data);
  } else {
    document.getElementById('rcSyncLoading').style.display = 'none';
    const err = document.getElementById('rcSyncError');
    err.style.display = '';
    err.textContent = syncResult.status === 'rejected'
      ? '불러오기 실패: ' + syncResult.reason.message : '데이터가 없습니다.';
  }

  // ── 만족도 통계 ──
  if (ratingResult.status === 'fulfilled' && ratingResult.value.data) {
    renderRatingStats(ratingResult.value.data);
  } else {
    document.getElementById('rcRatingLoading').style.display = 'none';
    const err = document.getElementById('rcRatingError');
    err.style.display = '';
    err.textContent = ratingResult.status === 'rejected'
      ? '불러오기 실패: ' + ratingResult.reason.message : '데이터가 없습니다.';
  }
});
