import { bootstrapApp } from "../main-app.js";
import "../scss/pages/messenger.scss";

import { initRealData, getRoomList, getRoomDetail } from "./messenger/mockData.js";
import { renderNetworkTab } from "./messenger/network.js";
import { renderSentimentTab } from "./messenger/sentiment.js";
import { renderActivityTab } from "./messenger/activity.js";

bootstrapApp("messenger");

const TAB_RENDERERS = {
  network: renderNetworkTab,
  sentiment: renderSentimentTab,
  activity: renderActivityTab,
};

const state = {
  roomId: null,
  activeTab: "network",
  renderedTabs: new Set(),
};

function renderRoomList() {
  const listEl = document.getElementById("mg-room-list");
  const rooms = getRoomList();

  listEl.innerHTML = rooms
    .map(
      (room) => `
      <button type="button" class="mg-room-item" data-room-id="${room.id}">
        <div class="mg-room-item-top">
          <span class="mg-room-name">${room.name}</span>
          <span class="mg-room-badge mg-badge-${room.badge.toLowerCase()}">${room.badge}</span>
        </div>
        <div class="mg-room-item-bottom">
          <span>${room.memberCount}명</span>
          <span>${room.lastActiveLabel}</span>
        </div>
      </button>`,
    )
    .join("");

  listEl.querySelectorAll(".mg-room-item").forEach((btn) => {
    btn.addEventListener("click", () => selectRoom(btn.dataset.roomId));
  });
}

function renderHeaderStats() {
  const { room, headerStats } = getRoomDetail(state.roomId);
  document.getElementById("mg-room-name").textContent = room.name;
  document.getElementById("mg-stat-members").textContent = headerStats.memberCount;
  document.getElementById("mg-stat-messages").textContent = headerStats.totalMessages.toLocaleString();
  document.getElementById("mg-stat-mood").textContent = headerStats.moodPct;
}

function renderActiveTab() {
  const panel = document.getElementById(`mg-panel-${state.activeTab}`);
  const renderFn = TAB_RENDERERS[state.activeTab];
  if (!panel || !renderFn) return;
  renderFn(panel, state.roomId);
}

function selectRoom(roomId) {
  if (roomId === state.roomId) return;
  state.roomId = roomId;
  state.renderedTabs = new Set();

  document.querySelectorAll(".mg-room-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.roomId === roomId);
  });

  renderHeaderStats();
  renderActiveTab();
  state.renderedTabs.add(state.activeTab);
}

function selectTab(tab) {
  if (tab === state.activeTab) return;
  state.activeTab = tab;

  document.querySelectorAll(".mg-tab-btn").forEach((btn) => {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", String(isActive));
  });
  document.querySelectorAll(".mg-tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `mg-panel-${tab}`);
  });

  if (!state.renderedTabs.has(tab)) {
    renderActiveTab();
    state.renderedTabs.add(tab);
  }
}

function initTabBar() {
  document.querySelectorAll(".mg-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => selectTab(btn.dataset.tab));
  });
}

function initRangeToggle() {
  // 목업 데이터 단계라 시간 범위는 시각적 토글만 제공한다 (실데이터 연결 시 재구현).
  document.querySelectorAll(".mg-range-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mg-range-btn").forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", String(b === btn));
      });
    });
  });
}

async function init() {
  initTabBar();
  initRangeToggle();

  const listEl = document.getElementById("mg-room-list");
  listEl.innerHTML = `<div class="mg-panel-title" style="padding:16px;">방 목록 불러오는 중...</div>`;

  try {
    await initRealData();
  } catch (e) {
    console.error("[messenger] 방 목록 로드 실패", e);
    listEl.innerHTML = `<div class="mg-panel-title" style="padding:16px;">방 목록을 불러오지 못했습니다.</div>`;
    return;
  }

  renderRoomList();

  const firstRoom = getRoomList()[0];
  if (firstRoom) {
    selectRoom(firstRoom.id);
  } else {
    listEl.innerHTML = `<div class="mg-panel-title" style="padding:16px;">인덱싱된 카카오톡 방이 없습니다.</div>`;
  }
}

init();
