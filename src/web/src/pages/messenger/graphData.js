/**
 * 실데이터 로더. /accounts?domain=messenger로 인덱싱된 카카오톡 방 목록을 가져오고,
 * 각 방의 /graph-data(GraphRAG entities/relationships → graph_data.json)를 받아
 * PERSON 노드 + PERSON-PERSON 엣지를 캐시해둔다.
 *
 * mockData.js는 이 캐시를 참고해서 참여자 "정체성"(이름/색)은 실데이터를 쓰고,
 * 아직 실데이터가 없는 값(감정 점수, 주간 빈도 등)만 시드 기반으로 채운다.
 */

const roomListPromise_ = { current: null };
const graphCache = new Map(); // user_id -> { nodes, edges, personNodes, personEdges }

// "OS스터디 [msg_afb96430]" → "OS스터디"
function stripRoomSuffix(userId) {
  return (userId || "").replace(/\s*\[msg_[0-9a-f]{8}\]\s*$/, "").trim() || userId;
}

async function fetchGraphData(userId) {
  const res = await fetch(`/graph-data?user_id=${encodeURIComponent(userId)}&domain=messenger`);
  const data = await res.json();
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  const personIds = new Set(nodes.filter((n) => n.entity_type === "PERSON").map((n) => n.id));

  const personNodes = nodes.filter((n) => personIds.has(n.id));
  const personEdges = edges.filter((e) => personIds.has(e.source) && personIds.has(e.target));

  const entry = { nodes, edges, personNodes, personEdges };
  graphCache.set(userId, entry);
  return entry;
}

// 방 목록 + 방별 그래프 데이터를 한 번에 로드(병렬). 실패한 방은 목록에서 제외.
export async function loadRooms() {
  if (roomListPromise_.current) return roomListPromise_.current;

  roomListPromise_.current = (async () => {
    const accountsRes = await fetch("/accounts?domain=messenger");
    const accountsData = await accountsRes.json();
    const accounts = (accountsData.accounts || []).filter((a) => a.indexed);

    const rooms = await Promise.all(
      accounts.map(async (a) => {
        try {
          const { personNodes, personEdges } = await fetchGraphData(a.user_id);
          const memberCount = personNodes.length;
          const relationCount = personEdges.length;
          // 사람 사이 엣지 밀도를 방 목록의 "활성도" 배지로 대략 표시 (실데이터 기반).
          const density = memberCount > 1 ? relationCount / memberCount : 0;
          const badge = density >= 2 ? "HIGH" : density >= 1 ? "MED" : "LOW";
          return {
            id: a.user_id,
            name: stripRoomSuffix(a.user_id),
            badge,
            memberCount,
            relationCount,
          };
        } catch (e) {
          console.error(`[messenger] 방 데이터 로드 실패: ${a.user_id}`, e);
          return null;
        }
      }),
    );

    return rooms.filter(Boolean);
  })();

  return roomListPromise_.current;
}

export function getCachedGraph(roomId) {
  return graphCache.get(roomId) || { nodes: [], edges: [], personNodes: [], personEdges: [] };
}
