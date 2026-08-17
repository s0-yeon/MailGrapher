import * as d3 from "d3";
import { getActivityData } from "./mockData.js";

// 라이트 서피스 기준으로 검증된 상태(status) 팔레트 — 사이트 공통 success/warning/danger 토큰과 동일.
const STATUS = {
  positive: "#1a9e6e",
  neutral: "#d4a843",
  negative: "#e05252",
};
const GRID_COLOR = "#d8ebe3";

function renderWeeklyChart(mount, days, seriesNames, seriesColors, weeklyFrequency) {
  mount.innerHTML = `
    <div class="mg-panel-title">주간 메시지 빈도</div>
    <div class="mg-chart-legend">
      ${seriesNames.map((name, i) => `<span><i style="background:${seriesColors[i]}"></i>${name}</span>`).join("")}
    </div>`;

  const chartEl = document.createElement("div");
  chartEl.className = "mg-bar-chart";
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
    const margin = { top: 16, right: 16, bottom: 28, left: 42 };
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    const x0 = d3.scaleBand().domain(days).range([margin.left, width - margin.right]).paddingInner(0.35);
    const x1 = d3
      .scaleBand()
      .domain(seriesNames)
      .range([0, x0.bandwidth()])
      .paddingInner(0.12);
    const maxVal = d3.max(weeklyFrequency, (d) => d3.max(d.values)) || 1;
    const y = d3.scaleLinear().domain([0, maxVal]).nice().range([height - margin.bottom, margin.top]);

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

    const barWidth = Math.min(24, x1.bandwidth());
    const barOffset = (x1.bandwidth() - barWidth) / 2;

    const dayGroups = svg
      .append("g")
      .selectAll("g")
      .data(weeklyFrequency)
      .join("g")
      .attr("transform", (d) => `translate(${x0(d.day)},0)`);

    dayGroups
      .selectAll("rect")
      .data((d) => seriesNames.map((name, i) => ({ name, value: d.values[i], day: d.day })))
      .join("rect")
      .attr("x", (d) => x1(d.name) + barOffset)
      .attr("y", (d) => y(d.value))
      .attr("width", barWidth)
      .attr("height", (d) => y(0) - y(d.value))
      .attr("rx", 4)
      .attr("fill", (d) => seriesColors[seriesNames.indexOf(d.name)])
      .on("pointerenter", function (event, d) {
        d3.select(this).style("filter", "brightness(1.15)");
        tooltip.style.display = "block";
        tooltip.innerHTML = `<strong>${d.day} · ${d.name}</strong><div>${d.value.toLocaleString()}건</div>`;
      })
      .on("pointermove", (event) => {
        const rect2 = chartEl.getBoundingClientRect();
        tooltip.style.left = `${event.clientX - rect2.left + 14}px`;
        tooltip.style.top = `${event.clientY - rect2.top + 14}px`;
      })
      .on("pointerleave", function () {
        d3.select(this).style("filter", null);
        tooltip.style.display = "none";
      });

    svg
      .append("g")
      .selectAll("text")
      .data(days)
      .join("text")
      .attr("x", (d) => x0(d) + x0.bandwidth() / 2)
      .attr("y", height - 8)
      .attr("text-anchor", "middle")
      .attr("class", "mg-axis-label")
      .text((d) => d);
  }

  draw();
  window.addEventListener("resize", draw);
  return () => window.removeEventListener("resize", draw);
}

function renderKeywords(mount, keywords) {
  mount.innerHTML = `
    <div class="mg-panel-title">키워드 빈도 · 감정 점수</div>
    <div class="mg-keyword-grid">
      ${keywords
        .map(
          (k) => `
        <div class="mg-keyword-item">
          <span class="mg-keyword-dot" style="background:${STATUS[k.sentiment]}"></span>
          <span class="mg-keyword-word">${k.word}</span>
          <span class="mg-keyword-count">${k.count.toLocaleString()}회</span>
        </div>`,
        )
        .join("")}
    </div>`;
}

function renderStatTiles(mount, statTiles) {
  mount.innerHTML = statTiles
    .map((tile) => {
      const arrow = tile.direction === "up" ? "▲" : "▼";
      // 두 방향 모두 이번 목업에선 "좋은 변화"로 세팅했으므로 success 텍스트 컬러 고정
      return `
      <div class="mg-stat-tile">
        <div class="mg-stat-label">${tile.label}</div>
        <div class="mg-stat-value">${tile.value}<span class="mg-stat-unit">${tile.unit}</span></div>
        <div class="mg-stat-delta mg-stat-delta-good">${arrow} ${tile.delta}% vs 어제</div>
      </div>`;
    })
    .join("");
}

export function renderActivityTab(container, roomId) {
  container.innerHTML = "";
  const { days, seriesNames, seriesColors, weeklyFrequency, keywords, statTiles } = getActivityData(roomId);

  const top = document.createElement("div");
  top.className = "mg-activity-top";
  container.appendChild(top);

  const chartCard = document.createElement("div");
  chartCard.className = "mg-card";
  top.appendChild(chartCard);

  const keywordCard = document.createElement("div");
  keywordCard.className = "mg-card";
  top.appendChild(keywordCard);

  const statsRow = document.createElement("div");
  statsRow.className = "mg-stat-row";
  container.appendChild(statsRow);

  const cleanup = renderWeeklyChart(chartCard, days, seriesNames, seriesColors, weeklyFrequency);
  renderKeywords(keywordCard, keywords);
  renderStatTiles(statsRow, statTiles);

  container._mgCleanup?.();
  container._mgCleanup = cleanup;
}
