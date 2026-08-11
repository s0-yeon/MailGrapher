/**
 * 계정 선택 드롭다운 — GET /accounts로 인덱싱된 계정 목록을 가져와
 * container 안에 <select>를 렌더링하고, 확정된 user_id를 반환한다.
 * (해당 페이지에서만 명시적으로 호출 — bootstrapApp()에는 연결하지 않음)
 *
 * @param {HTMLElement|null} container
 * @param {(userId: string) => void} [onChange] 전달하면 계정 변경 시 새로고침 대신 이 콜백을 호출한다
 *   (예: Graph Viz처럼 페이지 새로고침 없이 그 자리에서 다시 그려야 하는 경우).
 */
export async function initAccountPicker(container, onChange) {
  injectStyle();

  const current = localStorage.getItem('gw_user_id') || '';
  let effective = current;

  let select = null;
  if (container) {
    container.innerHTML = '';
    select = document.createElement('select');
    select.id = 'account-picker';
    select.className = 'gw-account-picker';
    const loadingOpt = document.createElement('option');
    loadingOpt.textContent = '계정 불러오는 중...';
    select.appendChild(loadingOpt);
    container.appendChild(select);
  }

  try {
    const res = await fetch('/accounts');
    const data = await res.json();
    const accounts = data.accounts || [];

    if (select) {
      select.innerHTML = '';
      if (accounts.length === 0) {
        const opt = document.createElement('option');
        opt.textContent = '인덱싱된 계정 없음';
        select.appendChild(opt);
      } else {
        const hasCurrent = accounts.some(acc => acc.user_id === current);
        effective = hasCurrent ? current : accounts[0].user_id;
        accounts.forEach(acc => {
          const opt = document.createElement('option');
          opt.value = acc.user_id;
          opt.textContent = acc.user_id + (acc.indexed ? '' : ' (인덱싱 중)');
          if (acc.user_id === effective) opt.selected = true;
          select.appendChild(opt);
        });
        select.onchange = () => {
          localStorage.setItem('gw_user_id', select.value);
          if (onChange) {
            onChange(select.value);
          } else {
            location.reload();
          }
        };
      }
    } else if (accounts.length > 0) {
      const hasCurrent = accounts.some(acc => acc.user_id === current);
      effective = hasCurrent ? current : accounts[0].user_id;
    }
  } catch (err) {
    console.error('[accounts] 로드 실패:', err);
  }

  localStorage.setItem('gw_user_id', effective);
  return effective;
}

function injectStyle() {
  if (document.getElementById('gw-account-picker-style')) return;
  const style = document.createElement('style');
  style.id = 'gw-account-picker-style';
  style.textContent = `
    .gw-account-picker { padding:7px 12px; border-radius:8px; border:1px solid #dde3ea; font-size:0.85rem; background:#fff; color:#2A3F54; cursor:pointer; }
    .gw-account-picker:focus { outline:none; border-color:#26B99A; box-shadow:0 0 0 3px rgba(38,185,154,0.12); }
  `;
  document.head.appendChild(style);
}
