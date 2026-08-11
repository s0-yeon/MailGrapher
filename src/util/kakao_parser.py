import re
import hashlib
import datetime

from config.settings import MAIL_BLOCK_SEP

# 하루 대화가 너무 길면 GraphRAG 청킹/엔티티 단위가 다루기 힘들어지므로 블록을 나눠서 저장
KAKAO_MAX_MESSAGES_PER_BLOCK = 400

# ── 메시지 매칭 정규식 ──
# 모바일(안드로이드/iOS) 신형: "2024년 1월 1일 오후 3:20, 홍길동 : 내용" (한 줄에 날짜+시간+이름 전부 포함)
_MOBILE_MSG_RE = re.compile(
    r'^(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일\s+(?P<ap>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*(?P<name>.+?)\s*:\s*(?P<msg>.*)$'
)
# 모바일 대체 포맷: "2024. 1. 1. 오후 3:20, 홍길동 : 내용"
_MOBILE_MSG_ALT_RE = re.compile(
    r'^(?P<y>\d{4})\.\s*(?P<mo>\d{1,2})\.\s*(?P<d>\d{1,2})\.\s+(?P<ap>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*(?P<name>.+?)\s*:\s*(?P<msg>.*)$'
)
# 모바일 시스템 메시지(입장/퇴장 등): "2024년 1월 1일 오후 3:20: 홍길동님이 들어왔습니다." (이름:내용 구분 콤마가 없음)
_MOBILE_SYS_RE = re.compile(
    r'^(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일\s+(?P<ap>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2}):\s*(?P<msg>.*)$'
)
# PC(윈도우) 내보내기: "[홍길동] [오후 3:20] 내용" — 날짜는 줄에 없고 별도 구분선에서만 나옴
_PC_MSG_RE = re.compile(
    r'^\[(?P<name>.+?)\]\s*\[(?P<ap>오전|오후)\s*(?P<h>\d{1,2}):(?P<mi>\d{2})\]\s*(?P<msg>.*)$'
)
# PC 날짜 구분선: "--------------- 2024년 1월 1일 월요일 ---------------"
_DATE_SEP_RE = re.compile(
    r'^-+\s*(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일.*-+$'
)
# 파일 맨 앞 헤더에서 방 이름 후보 추출용: "카카오톡 대화 : 가족톡" / "가족톡 님과 카카오톡 대화"
_ROOM_NAME_HINT_RE = re.compile(r'카카오톡\s*대화\s*[:：]?\s*(?P<name>.+)')


def _to_24h(ap: str, h) -> int:
    h = int(h)
    if ap == "오후" and h != 12:
        return h + 12
    if ap == "오전" and h == 12:
        return 0
    return h


# 카카오톡 대화 내보내기 텍스트(.txt)를 모바일/PC 포맷 구분 없이 파싱해서
# [{"dt": datetime, "sender": str|None, "text": str, "is_system": bool}, ...] 로 정규화한다.
# 실제 안드로이드/iOS/PC 내보내기 실물 파일로 정규식을 검증/보정하는 게 아직 필요함(알려진 포맷 기준으로 작성).
def parse_kakao_messages(raw_text: str) -> list[dict]:
    messages: list[dict] = []
    current_date = None  # PC 포맷에서 날짜 구분선으로만 갱신되는 "현재 날짜" 컨텍스트

    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m = _DATE_SEP_RE.match(line)
        if m:
            current_date = datetime.date(int(m.group("y")), int(m.group("mo")), int(m.group("d")))
            continue

        m = _MOBILE_MSG_RE.match(line) or _MOBILE_MSG_ALT_RE.match(line)
        if m:
            dt = datetime.datetime(
                int(m.group("y")), int(m.group("mo")), int(m.group("d")),
                _to_24h(m.group("ap"), m.group("h")), int(m.group("mi")),
            )
            current_date = dt.date()
            messages.append({"dt": dt, "sender": m.group("name").strip(), "text": m.group("msg"), "is_system": False})
            continue

        m = _MOBILE_SYS_RE.match(line)
        if m:
            dt = datetime.datetime(
                int(m.group("y")), int(m.group("mo")), int(m.group("d")),
                _to_24h(m.group("ap"), m.group("h")), int(m.group("mi")),
            )
            current_date = dt.date()
            messages.append({"dt": dt, "sender": None, "text": m.group("msg"), "is_system": True})
            continue

        m = _PC_MSG_RE.match(line)
        if m and current_date:
            dt = datetime.datetime(
                current_date.year, current_date.month, current_date.day,
                _to_24h(m.group("ap"), m.group("h")), int(m.group("mi")),
            )
            messages.append({"dt": dt, "sender": m.group("name").strip(), "text": m.group("msg"), "is_system": False})
            continue

        # 위 패턴에 매치되지 않는 줄은 직전 메시지의 연속 줄(멀티라인 메시지: 사진 전송 안내 뒤 텍스트, 줄바꿈 포함 메시지 등)로 간주.
        # 아직 메시지가 하나도 없으면(파일 맨 앞 안내문 등) 그냥 무시한다.
        if messages:
            messages[-1]["text"] += "\n" + line

    return messages


# 파일 헤더 영역에서 방 이름 후보를 시도 추출. 실패하면 fallback(보통 업로드 파일명) 반환.
# 최종적으로는 프론트 폼에서 사용자가 직접 입력/수정한 값이 우선하므로 이 함수는 초기값 추정 용도.
def guess_room_name(raw_text: str, fallback: str) -> str:
    for line in raw_text.splitlines()[:5]:
        line = line.strip()
        if not line:
            continue
        m = _ROOM_NAME_HINT_RE.search(line)
        if m and m.group("name").strip():
            return m.group("name").strip()
        break  # 첫 non-blank 줄만 후보로 봄 — 그 아래는 이미 대화 본문일 가능성이 높음
    return fallback


# 메시지 목록을 날짜별로 묶어(하루 메시지가 너무 많으면 max_per_block개씩 추가 분할) GraphRAG 인풋용
# "메일 블록" 호환 텍스트로 변환한다 (구분자 MAIL_BLOCK_SEP, 블록당 ID:/날짜: 필수 — mail_data_manager.py 요구사항).
def build_kakao_blocks(messages: list[dict], room_name: str, max_per_block: int = KAKAO_MAX_MESSAGES_PER_BLOCK) -> list[str]:
    if not messages:
        return []

    ordered = sorted(messages, key=lambda m: m["dt"])

    groups: dict[datetime.date, list[dict]] = {}
    for msg in ordered:
        groups.setdefault(msg["dt"].date(), []).append(msg)

    blocks = []
    block_index = 0
    for date in sorted(groups.keys()):
        day_messages = groups[date]
        for chunk_start in range(0, len(day_messages), max_per_block):
            chunk = day_messages[chunk_start:chunk_start + max_per_block]
            block_index += 1
            chunk_seq = chunk_start // max_per_block + 1
            mail_id = f"{date.isoformat()}_{chunk_seq:02d}"

            participants = []
            seen = set()
            for msg in chunk:
                if msg["is_system"] or not msg["sender"]:
                    continue
                if msg["sender"] not in seen:
                    seen.add(msg["sender"])
                    participants.append(msg["sender"])

            body_lines = []
            for msg in chunk:
                time_str = msg["dt"].strftime("%H:%M")
                if msg["is_system"]:
                    body_lines.append(f"{time_str} [알림] {msg['text']}")
                else:
                    body_lines.append(f"{time_str} {msg['sender']}: {msg['text']}")

            block_text = "\n".join([
                MAIL_BLOCK_SEP,
                f"[대화 {block_index}]",
                "",
                f"ID: {mail_id}",
                f"채팅방: {room_name}",
                f"날짜: {chunk[0]['dt'].strftime('%Y-%m-%d %H:%M:%S')}",
                "참여자: " + (", ".join(participants) if participants else "알 수 없음"),
                "",
                "[대화 내용]",
                "\n".join(body_lines),
                MAIL_BLOCK_SEP,
            ])
            blocks.append(block_text)

    return blocks


# 대화방 이름만으로 안정적인 합성 user_id를 만든다 (같은 방 이름을 다시 올리면 항상 같은 값 → append 대상 계정이 유지됨).
# _mail_to_dir_name()이 한글을 전부 밑줄로 뭉개서 방 이름만으로는 폴더 충돌 가능성이 있으므로,
# ASCII 해시 서픽스를 붙여 폴더명 레벨의 유니크성을 보장한다. 원본 표시 이름은 account.json에 그대로 보존됨.
def build_kakao_room_id(room_name: str) -> str:
    normalized = (room_name or "").strip()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{normalized} [kakao_{digest}]"
