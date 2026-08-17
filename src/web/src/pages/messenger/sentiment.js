import * as d3 from "d3";
import { getSentimentData } from "./mockData.js";

// dataviz 스킬 참고: 긍정/중립/부정은 "상태(state)"이므로 카테고리 색이 아니라
// status 팔레트(good/warning/critical, 라이트 서피스 기준 검증)를 그대로 쓴다.
const STATUS = {
  positive: "#1a9e6e",
  neutral: "#d4a843",
  negative: "#e05252",
};
const GRID_COLOR = "#d8ebe3";
const MUTED = "#8a9e96";

function scoreColor(score) {
  if (score >= 75) return STATUS.positive;
  if (score >= 50) return STATUS.neutral;
  return STATUS.negative;
}

function renderTimeline(mount, timeline) {
  mount.innerHTML = `
    <div class="mg-panel-title">SENTIMENT TIMELINE · 오늘</div>
    <div class="mg-chart-legend">
      <span><i style="background:${STATUS.positive}"></i>긍정</span>
      <span><i style="background:${STATUS.neutral}"></i>중립</span>
      <span><i style="background:${STATUS.negative}"></i>부정</span>
    </div>`;

  const chartEl = document.createElement("div");
  chartEl.className = "mg-timeline-chart";
  mount.appendChild(chartEl);

  const svg = d3.select(chartEl).append("svg").attr("class", "mg-svg");
  const tooltip = document.createElement("div");
  tooltip.className = "mg-tooltip";
  tooltip.style.display = "none";
  chartEl.appendChild(tooltip);

  function draw() {
    const rect = chartEl.getBoundingClientRect();
    const width = Math.max(320, rect.width);
    const height = Math.max(220, rect.height);
    const margin = { top: 16, right: 16, bottom: 28, left: 34 };
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    const x = d3.scalePoint().domain(timeline.map((d) => d.time)).range([margin.left, width - margin.right]);
    const y = d3.scaleLinear().domain([0, 100]).range([height - margin.bottom, margin.top]);

    // hairline y-grid (실선, recessive)
    svg
      .append("g")
      .selectAll("line")
      .data(y.ticks(4))
      .join("line")
      .attr("x1", margin.left)
      .attr("x2", width - margin.right)
      .attr("y1", (d) => y(d))
      .attr("y2", (d) => y(d))
      .attr("stroke", GRID_COLOR)
      .attr("stroke-width", 1);

    svg
      .append("g")
      .selectAll("text")
      .data(y.ticks(4))
      .join("text")
      .attr("x", margin.left - 8)
      .attr("y", (d) => y(d))
      .attr("dy", "0.32em")
      .attr("text-anchor", "end")
      .attr("class", "mg-axis-label")
      .text((d) => d);

    svg
      .append("g")
      .selectAll("text")
      .data(timeline.filter((_, i) => i % 2 === 0))
      .join("text")
      .attr("x", (d) => x(d.time))
      .attr("y", height - 8)
      .attr("text-anchor", "middle")
      .attr("class", "mg-axis-label")
      .text((d) => d.time);

    const keys = ["positive", "neutral", "negative"];
    keys.forEach((key) => {
      const line = d3
        .line()
        .x((d) => x(d.time))
        .y((d) => y(d[key]))
        .curve(d3.curveMonotoneX);
      svg
        .append("path")
        .datum(timeline)
        .attr("fill", "none")
        .attr("stroke", STATUS[key])
        .attr("stroke-width", 2)
        .attr("stroke-linejoin", "round")
        .attr("stroke-linecap", "round")
        .attr("d", line);
    });

    // 크로스헤어 + 통합 툴팁 (interaction.md)
    const crosshair = svg
      .append("line")
      .attr("y1", margin.top)
      .attr("y2", height - margin.bottom)
      .attr("stroke", MUTED)
      .attr("stroke-width", 1)
      .style("opacity", 0);

    svg
      .append("rect")
      .attr("x", margin.left)
      .attr("y", margin.top)
      .attr("width", width - margin.left - margin.right)
      .attr("height", height - margin.top - margin.bottom)
      .attr("fill", "transparent")
      .on("pointermove", (event) => {
        const [mx] = d3.pointer(event);
        const idx = Math.round(((mx - margin.left) / (width - margin.left - margin.right)) * (timeline.length - 1));
        const d = timeline[Math.max(0, Math.min(timeline.length - 1, idx))];
        if (!d) return;
        crosshair.attr("x1", x(d.time)).attr("x2", x(d.time)).style("opacity", 1);
        tooltip.style.display = "block";
        tooltip.style.left = `${x(d.time) + 12}px`;
        tooltip.style.top = `${margin.top}px`;
        tooltip.innerHTML = `<strong>${d.time}</strong>
          <div><span style="color:${STATUS.positive}">●</span> 긍정 <strong>${d.positive}</strong></div>
          <div><span style="color:${STATUS.neutral}">●</span> 중립 <strong>${d.neutral}</strong></div>
          <div><span style="color:${STATUS.negative}">●</span> 부정 <strong>${d.negative}</strong></div>`;
      })
      .on("pointerleave", () => {
        crosshair.style("opacity", 0);
        tooltip.style.display = "none";
      });
  }

  draw();
  window.addEventListener("resize", draw);
  return () => window.removeEventListener("resize", draw);
}

// BEHAVIOR PROFILE 레이더 — 참여자를 0~N명 토글로 골라서 겹쳐 볼 수 있게 한다.
// values는 mockData.js가 참여자별로 미리 계산해둔 걸 그대로 쓰므로, 선택을 바꿔도
// 같은 참여자는 항상 같은 값/색을 유지한다("color follows the entity, never rank").
function renderRadar(mount, radarAxes, radarByParticipant) {
  mount.innerHTML = `<div class="mg-panel-title">BEHAVIOR PROFILE</div>`;

  const toggleRow = document.createElement("div");
  toggleRow.className = "mg-participant-toggle-row";
  mount.appendChild(toggleRow);

  const legend = document.createElement("div");
  legend.className = "mg-chart-legend";
  mount.appendChild(legend);

  const chartEl = document.createElement("div");
  chartEl.className = "mg-radar-chart";
  mount.appendChild(chartEl);
  const svg = d3.select(chartEl).append("svg").attr("class", "mg-svg");

  const emptyState = document.createElement("div");
  emptyState.className = "mg-radar-empty";
  emptyState.textContent = "비교할 참여자를 위에서 선택하세요.";
  chartEl.appendChild(emptyState);

  // 기본값: 메시지 수 상위 2명 (기존 동작과 동일한 초기 화면), 참여자가 그보다 적으면 있는 만큼만.
  const selected = new Set(radarByParticipant.slice(0, 2).map((p) => p.id));

  function renderToggles() {
    toggleRow.innerHTML = radarByParticipant
      .map(
        (p) => `
        <button type="button" class="mg-participant-toggle${selected.has(p.id) ? " active" : ""}" data-id="${p.id}" style="--toggle-color:${p.color}">
          <span class="mg-participant-toggle-dot" style="background:${p.color}"></span>${p.name}
        </button>`,
      )
      .join("");

    toggleRow.querySelectorAll(".mg-participant-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        if (selected.has(id)) selected.delete(id);
        else selected.add(id);
        renderToggles();
        draw();
      });
    });
  }

  function selectedSeries() {
    return radarByParticipant.filter((p) => selected.has(p.id));
  }

  function draw() {
    const radar = selectedSeries();

    legend.innerHTML = radar
      .map((r) => `<span><i style="background:${r.color}"></i>${r.name}</span>`)
      .join("");

    emptyState.style.display = radar.length ? "none" : "flex";

    const rect = chartEl.getBoundingClientRect();
    const size = Math.max(220, Math.min(rect.width, rect.height || rect.width));
    const cx = rect.width / 2;
    const cy = size / 2;
    const r = size / 2 - 36;
    const n = radarAxes.length;
    const angle = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;
    const point = (i, value) => {
      const a = angle(i);
      const rr = (value / 100) * r;
      return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
    };

    svg.attr("viewBox", `0 0 ${rect.width} ${size}`);
    svg.selectAll("*").remove();

    // 배경 격자(육각/오각 링) — hairline, 실선
    const rings = [0.25, 0.5, 0.75, 1];
    rings.forEach((ratio) => {
      const pts = d3.range(n).map((i) => point(i, ratio * 100));
      svg
        .append("polygon")
        .attr("points", pts.map((p) => p.join(",")).join(" "))
        .attr("fill", "none")
        .attr("stroke", GRID_COLOR)
        .attr("stroke-width", 1);
    });

    d3.range(n).forEach((i) => {
      const [x, y] = point(i, 100);
      svg.append("line").attr("x1", cx).attr("y1", cy).attr("x2", x).attr("y2", y).attr("stroke", GRID_COLOR).attr("stroke-width", 1);
      const [lx, ly] = point(i, 118);
      svg
        .append("text")
        .attr("x", lx)
        .attr("y", ly)
        .attr("text-anchor", "middle")
        .attr("dy", "0.32em")
        .attr("class", "mg-axis-label")
        .text(radarAxes[i]);
    });

    radar.forEach((series) => {
      const pts = series.values.map((v, i) => point(i, v));
      svg
        .append("polygon")
        .attr("points", pts.map((p) => p.join(",")).join(" "))
        .attr("fill", `${series.color}26`)
        .attr("stroke", series.color)
        .attr("stroke-width", 2)
        .attr("stroke-linejoin", "round");
      pts.forEach(([x, y]) => {
        svg.append("circle").attr("cx", x).attr("cy", y).attr("r", 4).attr("fill", series.color).attr("stroke", "#ffffff").attr("stroke-width", 2);
      });
    });
  }

  renderToggles();
  draw();
  window.addEventListener("resize", draw);
  return () => window.removeEventListener("resize", draw);
}

function renderScoreList(mount, participantScores) {
  const maxCount = d3.max(participantScores, (p) => p.messageCount) || 1;
  mount.innerHTML = `
    <div class="mg-panel-title">PARTICIPANT SENTIMENT SCORE</div>
    <div class="mg-score-list">
      ${participantScores
        .map((p) => {
          const color = scoreColor(p.sentimentPct);
          return `
          <div class="mg-score-row">
            <span class="mg-score-name">${p.name}</span>
            <div class="mg-score-track">
              <div class="mg-score-fill" style="width:${p.sentimentPct}%;background:${color}"></div>
            </div>
            <span class="mg-score-count">${p.messageCount.toLocaleString()}</span>
            <span class="mg-score-pct" style="color:${color}">${p.sentimentPct}%</span>
          </div>`;
        })
        .join("")}
    </div>`;
}

export function renderSentimentTab(container, roomId) {
  container.innerHTML = "";
  const { timeline, radarAxes, radarByParticipant, participantScores } = getSentimentData(roomId);

  const top = document.createElement("div");
  top.className = "mg-sentiment-top";
  container.appendChild(top);

  const timelineCard = document.createElement("div");
  timelineCard.className = "mg-card";
  top.appendChild(timelineCard);

  const radarCard = document.createElement("div");
  radarCard.className = "mg-card";
  top.appendChild(radarCard);

  const scoreCard = document.createElement("div");
  scoreCard.className = "mg-card mg-score-card";
  container.appendChild(scoreCard);

  const cleanups = [
    renderTimeline(timelineCard, timeline),
    renderRadar(radarCard, radarAxes, radarByParticipant),
  ];
  renderScoreList(scoreCard, participantScores);

  container._mgCleanup?.();
  container._mgCleanup = () => cleanups.forEach((fn) => fn && fn());
}
