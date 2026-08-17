/**
 * 메신저 분석 페이지의 데이터 소스.
 *
 * "누가 있는지"(방 목록, 참여자 이름/식별자)와 "관계망 탭"은 graphData.js를 통해
 * 실제 GraphRAG 인덱싱 결과(/accounts, /graph-data)를 그대로 쓴다.
 * 반면 감정분석/활동통계 탭의 수치(감정 점수, 시간대별 빈도, 키워드 카운트 등)는
 * 아직 이 값을 계산하는 실제 백엔드가 없어서, 참여자 "정체성"만 실데이터에서
 * 가져오고 값 자체는 방 id를 시드로 한 절차적 목업으로 채운다. 나중에 값 계산
 * 백엔드가 생기면 getSentimentData/getActivityData 내부만 fetch()로 바꾸면 된다.
 */

import { loadRooms, getCachedGraph } from "./graphData.js";

// ---- 시드 기반 의사난수: 같은 방은 새로고침해도 같은 값이 나오게 한다 ----
function hashSeed(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return h >>> 0;
  };
}

function mulberry32(seedStr) {
  const seedFn = hashSeed(seedStr);
  let a = seedFn();
  return function rand() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickN(rand, pool, n) {
  const copy = [...pool];
  const out = [];
  for (let i = 0; i < n && copy.length; i++) {
    const idx = Math.floor(rand() * copy.length);
    out.push(copy.splice(idx, 1)[0]);
  }
  return out;
}

// dataviz 스킬 라이트 서피스 기준 검증된 카테고리 팔레트 (고정 순서, 인접쌍 CVD 검증 완료).
// 참여자 = 정체성(카테고리) 인코딩이므로 이 순서를 그대로 순환해서 배정한다.
const AVATAR_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

const KEYWORD_POOL = [
  "프로젝트", "배포", "버그", "미팅", "완료", "지연", "업데이트", "검토",
  "승인", "오류", "기능", "테스트", "일정", "공유", "자료", "확인", "질문", "보고",
];

// 실데이터(personNodes)를 참여자 목록으로 변환 — 이름/식별자는 실데이터, 그 외
// (messageCount/sentimentPct 등 값 계산 백엔드가 없는 항목)만 시드로 채운다.
function buildParticipants(rand, roomId) {
  const { personNodes, personEdges } = getCachedGraph(roomId);

  const degreeById = new Map(personNodes.map((n) => [n.id, n.degree || 0]));
  const totalDegree = personNodes.reduce((sum, n) => sum + (n.degree || 0), 0) || 1;

  const participants = personNodes.map((n, i) => {
    // 실제로 계산된 메시지 수 백엔드가 없어 degree(연결 수) 비중으로 대략적인
    // 메시지 볼륨을 흉내낸다 — 완전 랜덤보다는 실제 그래프 밀도를 반영.
    const share = (degreeById.get(n.id) || 0) / totalDegree;
    const messageCount = Math.max(3, Math.round(share * (400 + rand() * 1200)));
    return {
      id: n.id,
      name: n.label || n.id,
      color: AVATAR_COLORS[i % AVATAR_COLORS.length],
      degree: n.degree || 0,
      messageCount,
      sentimentPct: Math.round(45 + rand() * 50),
    };
  });

  participants.sort((a, b) => b.messageCount - a.messageCount);
  return { participants, personEdges };
}

function withPercent(participants) {
  const total = participants.reduce((sum, p) => sum + p.messageCount, 0) || 1;
  return participants.map((p) => ({ ...p, pct: (p.messageCount / total) * 100 }));
}

const roomCache = new Map();
let roomListCache = [];

// messenger.js가 초기화 시점에 한 번 호출 — 방 목록 + 방별 그래프를 먼저 로드해둔다.
export async function initRealData() {
  roomListCache = await loadRooms();
  return roomListCache;
}

function getRoomState(roomId) {
  if (roomCache.has(roomId)) return roomCache.get(roomId);

  const rand = mulberry32(roomId);
  const built = buildParticipants(rand, roomId);
  const participants = withPercent(built.participants);
  const personEdges = built.personEdges;
  const totalMessages = participants.reduce((sum, p) => sum + p.messageCount, 0);
  const moodPct = participants.length
    ? Math.round(participants.reduce((sum, p) => sum + p.sentimentPct, 0) / participants.length)
    : 0;

  const room = roomListCache.find((r) => r.id === roomId) || { id: roomId, name: roomId };
  const state = { room, rand, participants, personEdges, totalMessages, moodPct };
  roomCache.set(roomId, state);
  return state;
}

export function getRoomList() {
  return roomListCache.map((r) => ({ ...r }));
}

export function getRoomDetail(roomId) {
  const { room, participants, totalMessages, moodPct } = getRoomState(roomId);
  return {
    room,
    participants,
    headerStats: {
      memberCount: participants.length,
      totalMessages,
      moodPct,
    },
  };
}

// 관계망 탭: PERSON 노드/PERSON-PERSON 엣지를 그대로 쓴다 (완전 실데이터,
// description은 GraphRAG가 실제로 뽑은 두 사람 사이 관계 설명 문장).
export function getNetworkData(roomId) {
  const { participants, personEdges } = getRoomState(roomId);

  const nodes = participants.map((p) => ({
    id: p.id,
    name: p.name,
    color: p.color,
    pct: p.pct,
    degree: p.degree,
    messageCount: p.messageCount,
  }));

  // 같은 (source,target) 쌍의 중복 엣지는 weight가 큰 쪽(더 central한 관계 설명)만 남긴다.
  const edgeByKey = new Map();
  personEdges.forEach((e) => {
    const key = e.source < e.target ? `${e.source}|${e.target}` : `${e.target}|${e.source}`;
    const existing = edgeByKey.get(key);
    if (!existing || (e.weight || 0) > (existing.weight || 0)) {
      edgeByKey.set(key, e);
    }
  });

  const maxWeight = Math.max(1, ...Array.from(edgeByKey.values()).map((e) => e.weight || 0));
  const edges = Array.from(edgeByKey.values()).map((e) => ({
    source: e.source,
    target: e.target,
    weight: Math.min(1, (e.weight || 0) / maxWeight) * 0.7 + 0.3,
    description: e.description,
    rawWeight: e.weight,
  }));

  return { nodes, edges };
}

export function getSentimentData(roomId) {
  const { rand, participants } = getRoomState(roomId);

  const hours = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"];
  let positive = 55 + rand() * 15;
  let neutral = 20 + rand() * 10;
  let negative = 5 + rand() * 5;
  const timeline = hours.map((time) => {
    positive = Math.min(95, Math.max(30, positive + (rand() - 0.5) * 18));
    neutral = Math.min(50, Math.max(5, neutral + (rand() - 0.5) * 10));
    negative = Math.min(25, Math.max(2, negative + (rand() - 0.5) * 6));
    return { time, positive: Math.round(positive), neutral: Math.round(neutral), negative: Math.round(negative) };
  });

  const radarAxes = ["반응 속도", "메시지 길이", "관계 긴밀도", "링크 공유", "이모지 사용"];
  // 참여자별 행동 프로필 값을 전원 계산해둔다 — 토글로 몇 명을 고르든 같은 값을 재사용하고,
  // 색상도 참여자 고유 색(p.color, 네트워크 탭과 동일)을 그대로 써서 정체성이 유지되게 한다.
  const radarByParticipant = participants.map((p) => ({
    id: p.id,
    name: p.name,
    color: p.color,
    values: radarAxes.map(() => Math.round(30 + rand() * 65)),
  }));

  const participantScores = [...participants]
    .sort((a, b) => b.sentimentPct - a.sentimentPct)
    .map((p) => ({ ...p }));

  return { timeline, radarAxes, radarByParticipant, participantScores };
}

export function getActivityData(roomId) {
  const { rand, room, participants, totalMessages, moodPct } = getRoomState(roomId);

  const days = ["월", "화", "수", "목", "금", "토", "일"];
  const seriesNames = ["3주 전", "2주 전", "지난주"];
  // 카테고리 슬롯 1~3 (dataviz 스킬: 3개 이하는 all-pairs 검증 통과, 라이트 서피스 기준)
  const seriesColors = ["#3987e5", "#d95926", "#199e70"];
  const weeklyFrequency = days.map((day, i) => {
    const isWeekend = i >= 5;
    const base = isWeekend ? 80 : 250;
    return {
      day,
      values: seriesNames.map(() => Math.round(base + rand() * (isWeekend ? 120 : 300))),
    };
  });

  const keywordCount = 10 + Math.floor(rand() * 3);
  const keywords = pickN(rand, KEYWORD_POOL, keywordCount)
    .map((word) => ({
      word,
      count: Math.round(20 + rand() * 340),
      sentiment: rand() < 0.55 ? "positive" : rand() < 0.85 ? "neutral" : "negative",
    }))
    .sort((a, b) => b.count - a.count);

  const todayTotal = Math.round(totalMessages * (0.3 + rand() * 0.3));
  const avgResponseMin = Math.round((2 + rand() * 8) * 10) / 10;
  const activeParticipants = Math.max(1, Math.round(participants.length * (2 + rand() * 3)));

  const statTiles = [
    { label: "오늘 총 메시지", value: todayTotal.toLocaleString(), unit: "msg", delta: Math.round(4 + rand() * 15), direction: "up" },
    { label: "평균 응답 시간", value: avgResponseMin.toFixed(1), unit: "min", delta: Math.round(3 + rand() * 12), direction: "down" },
    { label: "활성 참여자", value: activeParticipants.toString(), unit: "명", delta: Math.round(2 + rand() * 10), direction: "up" },
    { label: "감정 지수", value: moodPct.toString(), unit: "%", delta: Math.round(1 + rand() * 6), direction: "up" },
  ];

  return { room, days, seriesNames, seriesColors, weeklyFrequency, keywords, statTiles };
}
