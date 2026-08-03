import { bootstrapApp } from '../main-app.js';
import '../scss/pages/home.scss';

bootstrapApp('home');

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

  function typeGreeting(text) {
    const el = document.getElementById('home-greeting');
    if (!el) return;
    const cursor = el.querySelector('.gw-cursor');
    el.textContent = '';
    if (cursor) el.appendChild(cursor);
    let i = 0;
    (function tick() {
      if (i < text.length) {
        el.insertBefore(document.createTextNode(text[i++]), cursor || null);
        setTimeout(tick, 48);
      }
    })();
  }
  const greet = name !== '-' ? name + '님, 반갑습니다!' : '반갑습니다!';
  setTimeout(() => typeGreeting(greet), 400);
})();

/* ── Knowledge Graph 초기화 ── */
function initKGraph() {
  const container = document.getElementById('kgraph');
  const svg = document.getElementById('kg-svg');
  if (!container || !svg) return;
  const W = container.offsetWidth, H = container.offsetHeight;

  const nodes = [
    {id:'kn-search',       px:0.10, py:0.34, color:'#26B99A'},
    {id:'kn-mylife',       px:0.38, py:0.74, color:'#26B99A'},
    {id:'kn-imap-collect', px:0.65, py:0.16, color:'#26B99A'},
    {id:'kn-graph-viz',    px:0.88, py:0.60, color:'#26B99A'}
  ];

  const pos = {};
  nodes.forEach(n => {
    const el = document.getElementById(n.id); if(!el) return;
    const x = W * n.px, y = H * n.py;
    pos[n.id] = {x, y, color: n.color};
    el.style.left = x + 'px';
    el.style.top  = y + 'px';
  });

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = '';

  const defs = document.createElementNS('http://www.w3.org/2000/svg','defs');
  const chain = ['kn-search','kn-mylife','kn-imap-collect','kn-graph-viz'];

  /* 엣지별 선형 그라데이션 정의 */
  for(let i = 0; i < chain.length - 1; i++) {
    const a = pos[chain[i]], b = pos[chain[i+1]];
    if(!a || !b) continue;
    const g = document.createElementNS('http://www.w3.org/2000/svg','linearGradient');
    g.id = `eg${i}`; g.setAttribute('gradientUnits','userSpaceOnUse');
    g.setAttribute('x1',a.x); g.setAttribute('y1',a.y);
    g.setAttribute('x2',b.x); g.setAttribute('y2',b.y);
    [[a.color,'0%','0.7'],[b.color,'100%','0.7']].forEach(([c,off,op]) => {
      const s = document.createElementNS('http://www.w3.org/2000/svg','stop');
      s.setAttribute('offset',off); s.setAttribute('stop-color',c); s.setAttribute('stop-opacity',op);
      g.appendChild(s);
    });
    defs.appendChild(g);
  }
  svg.appendChild(defs);

  /* 연결선 + 여행 점 */
  for(let i = 0; i < chain.length - 1; i++) {
    const a = pos[chain[i]], b = pos[chain[i+1]];
    if(!a || !b) continue;
    const mx = (a.x+b.x)/2, my = (a.y+b.y)/2 - 62;
    const d = `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;

    /* 글로우 레이어 */
    const glow = document.createElementNS('http://www.w3.org/2000/svg','path');
    glow.setAttribute('d',d); glow.setAttribute('fill','none');
    glow.setAttribute('stroke',`url(#eg${i})`);
    glow.setAttribute('stroke-width','18'); glow.setAttribute('opacity','0.14');
    svg.appendChild(glow);

    /* 메인 경로 */
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',d); path.setAttribute('fill','none');
    path.setAttribute('stroke',`url(#eg${i})`);
    path.setAttribute('stroke-width','2.5');
    path.setAttribute('stroke-linecap','round');
    svg.appendChild(path);

    /* 흐르는 점 */
    const dot = document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.setAttribute('r','5.5');
    dot.setAttribute('fill', pos[chain[i+1]].color);
    dot.setAttribute('opacity','0.78');
    const am = document.createElementNS('http://www.w3.org/2000/svg','animateMotion');
    am.setAttribute('dur',(2.0 + i*0.4)+'s');
    am.setAttribute('repeatCount','indefinite');
    am.setAttribute('path',d);
    dot.appendChild(am);
    svg.appendChild(dot);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.gw-anim').forEach(el =>
    requestAnimationFrame(() => el.classList.add('visible'))
  );

  /* particles */
  (function() {
    const canvas = document.getElementById('gw-particles');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let W, H, P;
    function resize() { W = canvas.width = innerWidth; H = canvas.height = innerHeight; }
    addEventListener('resize', resize); resize();
    function mk() { return {x:Math.random()*W,y:Math.random()*H,r:Math.random()*2.2+.7,dx:(Math.random()-.5)*.38,dy:(Math.random()-.5)*.38,a:Math.random()*.55+.25}; }
    P = Array.from({length:90}, mk);
    function draw() {
      ctx.clearRect(0,0,W,H);
      P.forEach(p => {
        p.x+=p.dx; p.y+=p.dy;
        if(p.x<0||p.x>W)p.dx*=-1; if(p.y<0||p.y>H)p.dy*=-1;
        ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
        ctx.fillStyle=`rgba(26,158,110,${p.a})`; ctx.fill();
      });
      for(let i=0;i<P.length;i++) for(let j=i+1;j<P.length;j++){
        const dx=P[i].x-P[j].x,dy=P[i].y-P[j].y,d=Math.sqrt(dx*dx+dy*dy);
        if(d<150){ctx.beginPath();ctx.strokeStyle=`rgba(26,158,110,${.16*(1-d/150)})`;ctx.lineWidth=.9;ctx.moveTo(P[i].x,P[i].y);ctx.lineTo(P[j].x,P[j].y);ctx.stroke();}
      }
      requestAnimationFrame(draw);
    }
    draw();
  })();

  initKGraph();
  addEventListener('resize', () => { clearTimeout(window._kgt); window._kgt = setTimeout(initKGraph, 120); });
});
