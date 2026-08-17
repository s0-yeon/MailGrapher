import * as d3 from "d3";
import { getNetworkData } from "./mockData.js";

// 참여자 아바타 색(정체성 인코딩)은 mockData.js에서 카테고리 팔레트 순서로
// 배정해서 내려준다 — 여기서는 그 값을 그대로 쓴다("color follows the entity").
const LINK_COLOR = "#8a9e96"; // 링크는 정체성을 지니지 않으므로 중립 회색(라이트 서피스 기준)

function colorFor(node) {
  return node.color;
}

function buildTooltip(root) {
  const el = document.createElement("div");
  el.className = "mg-tooltip";
  el.style.display = "none";
  root.appendChild(el);
  return el;
}

function showTooltip(tooltipEl, rootRect, x, y, html) {
  tooltipEl.innerHTML = html;
  tooltipEl.style.display = "block";
  tooltipEl.style.left = `${x - rootRect.left + 14}px`;
  tooltipEl.style.top = `${y - rootRect.top + 14}px`;
}

function hideTooltip(tooltipEl) {
  tooltipEl.style.display = "none";
}

export function renderNetworkTab(container, roomId) {
  container.innerHTML = "";
  const { nodes, edges } = getNetworkData(roomId);

  const root = document.createElement("div");
  root.className = "mg-network-root";
  container.appendChild(root);

  const graphWrap = document.createElement("div");
  graphWrap.className = "mg-network-graph";
  graphWrap.innerHTML = `
    <div class="mg-network-graph-title">
      RELATIONSHIP NETWORK · ${nodes.length} NODES · ${edges.length} EDGES
    </div>`;
  root.appendChild(graphWrap);

  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "mg-panel-title";
    empty.style.padding = "16px";
    empty.textContent = "이 방에서 아직 추출된 참여자가 없습니다.";
    graphWrap.appendChild(empty);
    root.appendChild(document.createElement("div")).className = "mg-network-list";
    container._mgCleanup?.();
    container._mgCleanup = () => {};
    return;
  }

  const svg = d3
    .select(graphWrap)
    .append("svg")
    .attr("class", "mg-network-svg")
    .attr("width", "100%")
    .attr("height", "100%");

  const tooltip = buildTooltip(graphWrap);

  const list = document.createElement("div");
  list.className = "mg-network-list";
  list.innerHTML = `<div class="mg-panel-title">PARTICIPANTS</div>`;
  const listBody = document.createElement("div");
  list.appendChild(listBody);
  root.appendChild(list);

  const sortedNodes = [...nodes].sort((a, b) => b.messageCount - a.messageCount);
  listBody.innerHTML = sortedNodes
    .map(
      (n) => `
      <div class="mg-network-list-item">
        <span class="mg-avatar-dot" style="background:${colorFor(n)}"></span>
        <span class="mg-network-list-name">${n.name}</span>
        <span class="mg-network-list-count">${n.messageCount.toLocaleString()}</span>
        <span class="mg-network-list-pct">${n.pct.toFixed(1)}%</span>
      </div>`,
    )
    .join("");

  function layout() {
    const rect = graphWrap.getBoundingClientRect();
    const width = Math.max(320, rect.width);
    const height = Math.max(320, rect.height);
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    svg.selectAll("*").remove();

    const maxMsg = d3.max(nodes, (n) => n.messageCount) || 1;
    const radius = d3.scaleSqrt().domain([0, maxMsg]).range([18, 42]);

    const simNodes = nodes.map((n) => ({ ...n, r: radius(n.messageCount) }));
    const simLinks = edges.map((e) => ({ ...e }));

    const simulation = d3
      .forceSimulation(simNodes)
      .force("link", d3.forceLink(simLinks).id((d) => d.id).distance(130).strength(0.35))
      .force("charge", d3.forceManyBody().strength(-420))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide((d) => d.r + 20))
      .stop();

    for (let i = 0; i < 300; i++) simulation.tick();

    // 그래프가 실제로 차지하는 영역(반지름+라벨 여백 포함)을 구해서 캔버스에
    // 꽉 차도록 맞춘다 — 밀집된 소규모 그래프가 한쪽에 뭉치는 것을 방지.
    const labelPad = 46;
    const xs = simNodes.flatMap((d) => [d.x - d.r, d.x + d.r]);
    const ys = simNodes.flatMap((d) => [d.y - d.r, d.y + d.r + labelPad]);
    const bx0 = Math.min(...xs);
    const bx1 = Math.max(...xs);
    const by0 = Math.min(...ys);
    const by1 = Math.max(...ys);
    const graphW = Math.max(1, bx1 - bx0);
    const graphH = Math.max(1, by1 - by0);
    const padding = 32;
    const scale = Math.min(
      (width - padding * 2) / graphW,
      (height - padding * 2) / graphH,
      1.4,
    );
    const tx = width / 2 - scale * (bx0 + bx1) / 2;
    const ty = height / 2 - scale * (by0 + by1) / 2;

    const viewport = svg.append("g").attr("transform", `translate(${tx},${ty}) scale(${scale})`);

    const linkGroup = viewport.append("g").attr("class", "mg-links");

    // 실제로 보이는 얇은 선
    const linkSel = linkGroup
      .selectAll("line.mg-link-visible")
      .data(simLinks)
      .join("line")
      .attr("class", "mg-link-visible")
      .attr("stroke", LINK_COLOR)
      .attr("stroke-width", (d) => 1 + d.weight * 2)
      .attr("stroke-linecap", "round")
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    // 호버 전용 히트 타겟 — 얇은 선은 마우스로 잡기 어려워서 두껍고 투명한 선을 겹쳐 둔다
    // (interaction.md: 히트 타겟은 시각적 마크보다 크게).
    const linkHitSel = linkGroup
      .selectAll("line.mg-link-hit")
      .data(simLinks)
      .join("line")
      .attr("class", "mg-link-hit")
      .attr("stroke", "transparent")
      .attr("stroke-width", 14)
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y)
      .style("cursor", "pointer");

    const nodeSel = viewport
      .append("g")
      .attr("class", "mg-nodes")
      .selectAll("g")
      .data(simNodes)
      .join("g")
      .attr("transform", (d) => `translate(${d.x},${d.y})`)
      .style("cursor", "pointer");

    // 히트 타겟은 시각적 반지름보다 크게 (interaction.md: 24px 이상 확보)
    nodeSel
      .append("circle")
      .attr("r", (d) => Math.max(d.r + 10, 24))
      .attr("fill", "transparent");

    nodeSel
      .append("circle")
      .attr("class", "mg-node-ring")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => `${colorFor(d)}33`)
      .attr("stroke", (d) => colorFor(d))
      .attr("stroke-width", 2.5);

    nodeSel
      .append("text")
      .attr("class", "mg-node-initial")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", (d) => colorFor(d))
      .text((d) => d.name.slice(0, 1));

    nodeSel
      .append("text")
      .attr("class", "mg-node-label")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.r + 16)
      .text((d) => d.name);

    nodeSel
      .append("text")
      .attr("class", "mg-node-pct")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.r + 30)
      .attr("fill", (d) => colorFor(d))
      .text((d) => `${d.pct.toFixed(1)}%`);

    nodeSel
      .on("pointerenter", function (event, d) {
        d3.select(this).select(".mg-node-ring").attr("stroke-width", 4);
        linkSel
          .attr("stroke", (l) => (l.source.id === d.id || l.target.id === d.id ? colorFor(d) : LINK_COLOR))
          .attr("stroke-opacity", (l) => (l.source.id === d.id || l.target.id === d.id ? 0.9 : 0.35));
        const rect2 = graphWrap.getBoundingClientRect();
        showTooltip(
          tooltip,
          rect2,
          event.clientX,
          event.clientY,
          `<strong>${d.name}</strong>
           <div>연결된 관계 <strong>${d.degree.toLocaleString()}</strong>개 · 활동 비중 ${d.pct.toFixed(1)}%</div>`,
        );
      })
      .on("pointermove", (event) => {
        const rect2 = graphWrap.getBoundingClientRect();
        tooltip.style.left = `${event.clientX - rect2.left + 14}px`;
        tooltip.style.top = `${event.clientY - rect2.top + 14}px`;
      })
      .on("pointerleave", function () {
        d3.select(this).select(".mg-node-ring").attr("stroke-width", 2.5);
        linkSel.attr("stroke", LINK_COLOR).attr("stroke-opacity", 1);
        hideTooltip(tooltip);
      });

    // 엣지 호버: 두 사람 사이 관계 설명(GraphRAG가 실제로 뽑은 문장)을 툴팁으로 보여준다.
    linkHitSel
      .on("pointerenter", function (event, d) {
        linkSel
          .filter((l) => l === d)
          .attr("stroke", colorFor(d.source))
          .attr("stroke-width", 2 + d.weight * 2.5);
        const rect2 = graphWrap.getBoundingClientRect();
        const desc = d.description && d.description.trim()
          ? d.description
          : "아직 추출된 관계 설명이 없습니다.";
        showTooltip(
          tooltip,
          rect2,
          event.clientX,
          event.clientY,
          `<strong>${d.source.name} ↔ ${d.target.name}</strong>
           <div class="mg-tooltip-sub" style="max-width:260px;white-space:normal;">${desc}</div>`,
        );
      })
      .on("pointermove", (event) => {
        const rect2 = graphWrap.getBoundingClientRect();
        tooltip.style.left = `${event.clientX - rect2.left + 14}px`;
        tooltip.style.top = `${event.clientY - rect2.top + 14}px`;
      })
      .on("pointerleave", function (event, d) {
        linkSel
          .filter((l) => l === d)
          .attr("stroke", LINK_COLOR)
          .attr("stroke-width", 1 + d.weight * 2);
        hideTooltip(tooltip);
      });
  }

  layout();
  window.addEventListener("resize", layout, { once: false });
  // 탭이 다시 그려질 때 이전 리스너가 누적되지 않도록 컨테이너에 정리 훅을 남긴다.
  container._mgCleanup?.();
  container._mgCleanup = () => window.removeEventListener("resize", layout);
}
