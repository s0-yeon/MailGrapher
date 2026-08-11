"use client";

import React from "react";

/** [홈화면 메뉴 궤도]
 * 궤도 위치/크기 설정 — 전부 순수 2D 변환(scaleY + rotate)으로 타원을 만듦.
 * (이전엔 rotateX + perspective로 진짜 3D 회전을 썼는데, tiltDeg 부호를 뒤집으면
 *  타원이 좌우로 안 뒤집히고 "보는 방향" 자체가 반대로 넘어가버리는 문제가 있었음.
 *  2D 방식은 원을 눌러서(scaleY) 납작한 타원을 만든 다음 그걸 화면 평면에서
 *  그냥 회전(rotate)시키는 거라, 부호를 바꾸면 정확히 좌우 대칭으로만 뒤집힘.)
 *
 *   center.top / center.left : 배경 사진(hero-bg.png) 속 구체 중심 위치.
 *   diameter   : 궤도(찌그러뜨리기 전, 원래 원일 때)의 지름(px)
 *   squash     : 원을 얼마나 납작하게 누를지 (1 = 안 누른 원, 0.4 = 상당히 납작한 타원)
 *   tiltDeg    : 그렇게 만든 타원을 화면에서 몇 도 돌릴지. 양수/음수로 대각선 방향이
 *                정확히 좌우 대칭으로 바뀜 (예: 18 ↔ -18)
 *   duration   : 한 바퀴 도는 데 걸리는 시간(초). 작을수록 빨리 돎.
 */
const ORBIT = {
  center: { top: "38.9%", left: "71.5%" },
  diameter: 1020,
  squash: 0.3,
  tiltDeg: -22,
  duration: 54,
};

/**
 * 노드 각도(angle) — 0deg가 궤도의 정중앙 "위쪽", 시계 방향으로 증가.
 * 4개를 90도 간격 대신 임의 각도로 흩어놔서 자연스럽게 보이도록 함.
 * angle만 바꾸면 해당 노드가 궤도를 따라 다른 위치에서 출발.
 */
const NAV_NODES = [
  { href: "search.html", icon: "bi-search", label: "검색", angle: -20 },
  {
    href: "imap-collect.html",
    icon: "bi-inbox-fill",
    label: "메일 수집",
    angle: 70,
  },
  {
    href: "graph-viz.html",
    icon: "bi-diagram-3-fill",
    label: "지식 그래프",
    angle: 160,
  },
  { href: "mylife.html", icon: "bi-heart-fill", label: "My Life", angle: -110 },
];

/**
 * 카드가 중심 구체보다 앞/뒤 어디 있는지에 따라 z-index를 실시간으로 바꿔서 입체감을 줌.
 * 구체는 zIndex 1 고정(위 CENTER-SPHERE 블록) — 카드는 궤도를 도는 동안 구체보다
 * 뒤(zIndex 0)로 숨었다가 앞(zIndex 20)으로 나왔다가를 반복해야 함.
 *
 * 판정 기준: scaleY로 눌러 타원을 만들기 *전*, 즉 순수한 원 위에서 카드가 아래쪽 절반
 * (90deg~270deg, "화면 앞으로 다가오는 쪽")에 있으면 앞, 위쪽 절반(나머지)이면 뒤.
 * 이후 적용되는 rotate(tiltDeg)는 화면 전체를 그대로 돌리기만 할 뿐 앞/뒤 관계 자체는
 * 안 바꾸므로, 이 판정에는 tiltDeg가 끼어들 필요가 없음.
 *
 * 궤도 애니메이션(orbit-cw)은 매 노드가 같은 시각에 시작해서 같은 duration으로 도니까,
 * 앞/뒤가 바뀌는 시점(90deg, 270deg를 지나는 시점)을 각 노드의 시작 각도 기준으로
 * keyframe 퍼센트로 미리 계산해서 별도 애니메이션으로 심어줌.
 */
function buildDepthKeyframes(angle: number, name: string) {
  const norm = (deg: number) => ((deg % 360) + 360) % 360;
  const a0 = norm(angle);
  const isFrontAt0 = a0 > 90 && a0 < 270;
  const fracUntil = (target: number) => norm(target - angle) / 360;

  const f1 = fracUntil(90) * 100;
  const f2 = fracUntil(270) * 100;
  const fLow = Math.min(f1, f2);
  const fHigh = Math.max(f1, f2);
  const eps = 0.15;

  const zA = isFrontAt0 ? DEPTH_Z.front : DEPTH_Z.back;
  const zB = isFrontAt0 ? DEPTH_Z.back : DEPTH_Z.front;

  return `
    @keyframes ${name} {
      0% { z-index: ${zA}; }
      ${Math.max(0, fLow - eps).toFixed(2)}% { z-index: ${zA}; }
      ${fLow.toFixed(2)}% { z-index: ${zB}; }
      ${Math.max(0, fHigh - eps).toFixed(2)}% { z-index: ${zB}; }
      ${fHigh.toFixed(2)}% { z-index: ${zA}; }
      100% { z-index: ${zA}; }
    }
  `;
}

const DEPTH_Z = { front: 20, back: 0 };

export default function OrbitingCirclesGlobe() {
  const unsquash = 1 / ORBIT.squash;

  return (
    <div className="relative w-full h-full">
      <style>{`
        /*
         * 원래는 링(ring) div 하나가 rotate(tiltDeg) scaleY(squash)를 갖고, 그 안에서
         * 각 카드의 arm이 rotate(angle)만 갖는 구조였는데, 그러면 "링 div"가 transform이
         * 있다는 이유만으로 자체 stacking context를 만들어버려서 — 그 안의 카드가 z-index를
         * 아무리 바꿔도 stacking context 밖에 있는 구체(sphere)와는 절대 비교되지 않고
         * 항상 구체보다 뒤로만 그려지는 문제가 있었음(z-index가 안 먹히는 것처럼 보임).
         * 그래서 링을 없애고, tiltDeg+squash+angle 회전을 전부 arm 하나에 합쳐서
         * arm 자체가 구체와 같은 부모 밑의 형제(sibling)가 되게 만듦 — 이러면 arm의
         * z-index가 구체의 z-index와 "같은 stacking context"에서 정상적으로 비교됨.
         */
        @keyframes orbit-cw {
          from { transform: translate(-50%, -100%) rotate(${ORBIT.tiltDeg}deg) scaleY(${ORBIT.squash}) rotate(var(--start-angle)) }
          to   { transform: translate(-50%, -100%) rotate(${ORBIT.tiltDeg}deg) scaleY(${ORBIT.squash}) rotate(calc(var(--start-angle) + 360deg)) }
        }
        /*
         * 카드가 항상 화면 정면(원래 동그란 배지 모양)으로 보이게 만드는 상쇄 회전.
         * 순서가 중요함: rotate(공전 각도 상쇄) → scaleY(찌그러뜨린 거 원복) → rotate(타원 기울기 상쇄).
         * 부모 쪽 변환이 "rotate(tiltDeg) scaleY(squash) rotate(nodeAngle)" 순으로 누적되므로,
         * 이 순서 그대로 반대로 하나씩 상쇄해야 각도에 상관없이 정확히 원래 모양으로 돌아옴 —
         * 순서를 섞으면 카드가 공전 각도에 따라 비스듬히 일그러져 보임.
         */
        @keyframes counter-cw {
          from { transform: rotate(var(--counter-offset, 0deg)) scaleY(var(--unsquash, 1)) rotate(var(--counter-tilt, 0deg)) }
          to   { transform: rotate(calc(var(--counter-offset, 0deg) - 360deg)) scaleY(var(--unsquash, 1)) rotate(var(--counter-tilt, 0deg)) }
        }

        /* NAV_NODES 카드 자체를 유리 구체 재질로 — 배경/테두리/그림자만 이 톤으로 교체 */
        .gw-node-card {
          background: radial-gradient(circle at 35% 25%, rgba(255,255,255,.90) 0%, rgba(255,255,255,.45) 20%, rgba(255,255,255,.18) 45%, rgba(255,255,255,.10) 100%);
          border: 1px solid rgba(255,255,255,.78);
          box-shadow: inset 4px 4px 10px rgba(255,255,255,.55), inset -6px -8px 12px rgba(140,160,180,.15), 0 0 16px rgba(255,255,255,.35), 0 0 30px rgba(255,216,157,.28);
          backdrop-filter: blur(10px);
        }
        .gw-node-card:hover {
          box-shadow: inset 4px 4px 10px rgba(255,255,255,.6), inset -6px -8px 12px rgba(140,160,180,.15), 0 0 20px rgba(255,255,255,.45), 0 0 40px rgba(255,216,157,.4);
        }

        /* ===== [CENTER-SPHERE v1 시작] — 버전 다시 고를 때 이 블록 전체를 통째로 교체 ===== */
        .gw-cs-core-glow {
          position: absolute; left: 50%; top: 51%; width: 260px; height: 260px; transform: translate(-50%, -50%);
          border-radius: 50%;
          background: radial-gradient(circle, rgba(255,253,243,1) 0%, rgba(255,240,205,.95) 5%, rgba(255,218,157,.62) 16%, rgba(255,205,139,.22) 34%, rgba(255,205,139,.07) 52%, transparent 72%);
          filter: blur(8px);
          z-index: 2;
          animation: gw-cs-breathe 5s ease-in-out infinite;
        }
        .gw-cs-core {
          position: absolute; left: 50%; top: 51%; width: 26px; height: 26px; transform: translate(-50%, -50%);
          border-radius: 50%;
          background: radial-gradient(circle at 42% 38%, #ffffff 0%, #fffaf0 35%, #ffe4ae 70%, #efc77e 100%);
          box-shadow: 0 0 10px #fff, 0 0 30px rgba(255,226,168,.9), 0 0 70px rgba(255,211,145,.65);
          z-index: 8;
        }
        .gw-cs-sphere-shadow {
          position: absolute; left: 50%; top: 53%; width: 440px; height: 440px; transform: translate(-50%, -50%);
          border-radius: 50%;
          background: radial-gradient(circle, transparent 48%, rgba(255,255,255,.04) 60%, rgba(70,88,108,.12) 75%, transparent 78%);
          filter: blur(14px);
          z-index: 3;
        }
        .gw-cs-sphere {
          position: absolute; left: 50%; top: 51%; width: 440px; height: 440px; transform: translate(-50%, -50%);
          border-radius: 50%;
          background:
            radial-gradient(circle at 37% 25%, rgba(255,255,255,.48), transparent 17%),
            radial-gradient(circle at 55% 54%, rgba(255,245,218,.06), transparent 50%),
            radial-gradient(circle at 70% 78%, rgba(255,255,255,.12), transparent 20%);
          border: 2px solid rgba(255,255,255,.65);
          box-shadow:
            inset 10px 8px 30px rgba(255,255,255,.45),
            inset -20px -25px 45px rgba(83,105,125,.12),
            0 0 20px rgba(255,255,255,.35),
            0 0 70px rgba(255,235,196,.18);
          backdrop-filter: blur(3px);
          opacity: 0.55;
          z-index: 5;
        }
        .gw-cs-sphere-inner-ring {
          position: absolute; left: 50%; top: 51%; width: 310px; height: 310px; transform: translate(-50%, -50%);
          border-radius: 50%;
          border: 1px solid rgba(255,255,255,.36);
          box-shadow: inset 0 0 22px rgba(255,255,255,.10), 0 0 15px rgba(255,255,255,.12);
          z-index: 6;
        }
        .gw-cs-reflection {
          position: absolute; width: 185px; height: 110px; left: 25%; top: 22%; transform: rotate(-30deg);
          border-radius: 60% 45% 60% 35%;
          background: linear-gradient(135deg, rgba(255,255,255,.92), rgba(255,255,255,.55) 38%, rgba(255,255,255,.10) 75%, transparent);
          filter: blur(1.5px);
          opacity: .85;
          box-shadow: 0 0 22px rgba(255,255,255,.38);
          z-index: 8;
        }
        .gw-cs-rim {
          position: absolute; left: 50%; top: 51%; width: 440px; height: 440px; transform: translate(-50%, -50%) rotate(-18deg);
          border-radius: 50%;
          border: 3px solid transparent;
          border-top-color: rgba(255,255,255,.85);
          border-left-color: rgba(255,255,255,.38);
          border-right-color: rgba(255,237,199,.55);
          filter: blur(.3px) drop-shadow(0 0 8px rgba(255,255,255,.32));
          z-index: 9;
        }
        .gw-cs-specular {
          position: absolute; width: 12px; height: 12px; border-radius: 50%;
          background: white;
          box-shadow: 0 0 8px white, 0 0 20px rgba(255,218,153,.8);
          z-index: 15;
        }
        .gw-cs-specular-a { left: 22%; top: 41%; }
        .gw-cs-specular-b { right: 22%; bottom: 28%; }

        @keyframes gw-cs-breathe {
          0%, 100% { transform: translate(-50%, -50%) scale(.96); opacity: .82; }
          50% { transform: translate(-50%, -50%) scale(1.04); opacity: 1; }
        }
        /* ===== [CENTER-SPHERE v1 끝] ===== */

        ${NAV_NODES.map((node, i) => buildDepthKeyframes(node.angle, `orbit-z-${i}`)).join("\n")}
      `}</style>

      {/* ===== [CENTER-SPHERE v1 시작] — NAV_NODES가 도는 중심 구체 (장식용, ORBIT.center/diameter에 맞춰 스케일) ===== */}
      <div
        className="pointer-events-none"
        style={{
          position: "absolute",
          top: ORBIT.center.top,
          left: ORBIT.center.left,
          width: 700,
          height: 700,
          zIndex: 1,
          transform: `translate(-50%, -50%) scale(0.99)`,
        }}
      >
        <div className="gw-cs-sphere-shadow" />
        <div className="gw-cs-core-glow" />
        <div className="gw-cs-sphere" />
        <div className="gw-cs-sphere-inner-ring" />
        <div className="gw-cs-reflection" />
        <div className="gw-cs-rim" />
        <div className="gw-cs-specular gw-cs-specular-a" />
        <div className="gw-cs-specular gw-cs-specular-b" />
        <div className="gw-cs-core" />
      </div>
      {/* ===== [CENTER-SPHERE v1 끝] ===== */}

      {/* 궤도 카드 — arm 각각이 구체(zIndex 1)와 같은 부모 밑의 형제라서 z-index가 정상 비교됨 */}
      {NAV_NODES.map((node, i) => (
        <div
          key={node.href}
          className="absolute origin-bottom flex flex-col justify-start items-center pointer-events-none"
          style={
            {
              top: ORBIT.center.top,
              left: ORBIT.center.left,
              height: ORBIT.diameter / 2,
              "--start-angle": `${node.angle}deg`,
              animation: `orbit-cw ${ORBIT.duration}s linear infinite, orbit-z-${i} ${ORBIT.duration}s linear infinite`,
            } as React.CSSProperties
          }
        >
          <a
            href={node.href}
            className="gw-node-card pointer-events-auto w-20 h-20 sm:w-24 sm:h-24 rounded-full -mt-8 relative flex flex-col items-center justify-center gap-1 text-decoration-none transition-shadow"
            style={
              {
                "--counter-offset": `${-node.angle}deg`,
                "--unsquash": unsquash,
                "--counter-tilt": `${-ORBIT.tiltDeg}deg`,
                animation: `counter-cw ${ORBIT.duration}s linear infinite`,
              } as React.CSSProperties
            }
          >
            <i
              className={`bi ${node.icon}`}
              style={{
                fontSize: "1.1rem",
                color: "var(--accent-foreground)",
              }}
            ></i>
            <span
              style={{
                fontSize: ".7rem",
                fontWeight: 600,
                color: "var(--accent-foreground)",
                textAlign: "center",
                lineHeight: 1.15,
              }}
            >
              {node.label}
            </span>
          </a>
        </div>
      ))}
    </div>
  );
}
