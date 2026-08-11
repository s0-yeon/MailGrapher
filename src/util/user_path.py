import re,os
import json
import shutil
from config.settings import GRAPHRAG_SETTINGS_DIR, GRAPHRAG_PROMPTS_DIR

ACCOUNT_META_FILENAME = "account.json"

_MAX_MAILS_CONFIG = {
    "ddyr1554@gmail.com": 200,
    "inhist44@gmail.com": 1000,
    "cjiyou1090@gmail.com": 1500,
    "csi10186@gmail.com": 500,
    "03yeah03@gmail.com": 300,
}

def _mail_to_dir_name(user_id: str) -> str:
    s = user_id.strip().lower()
    s = s.replace("@", "_at_")
    s = s.replace(".", "_")
    s = s.replace("+", "_plus_")
    s = re.sub(r"[^a-z0-9_]", "_", s)
    return s

class UserPaths:
    def __init__(self, base_dir: str, user_id: str, domain: str):
        self.BASE_DIR = base_dir
        self.USER_ID = user_id
        self.DOMAIN = domain

        dir_name = _mail_to_dir_name(user_id)

        self.USER_ROOT = os.path.join(base_dir, "user_data", dir_name)          # 계정 식별용 (domain 무관)
        self.DOMAIN_ROOT = os.path.join(self.USER_ROOT, domain)                 # 실제 데이터 저장 위치 (domain별)
        self.GRAPHRAG_ROOT = os.path.join(self.DOMAIN_ROOT, "parquet")

        self.USER_GRAPH_SETTINGS_PATH = os.path.join(self.GRAPHRAG_ROOT, "settings.yaml")
        self.USER_GRAPH_PROMPTS_PATH = os.path.join(self.GRAPHRAG_ROOT, "prompts")

        self.GRAPH_JSON_PATH = os.path.join(self.DOMAIN_ROOT, "json", "graphml_data.json")
        self.GRAPH_BUILD_SCRIPT = os.path.join(base_dir, "src", "parquet2json.py")

        self.MAIL_DIR = os.path.join(self.GRAPHRAG_ROOT, "input")
        self.MAIL_LATEST_PATH = os.path.join(self.MAIL_DIR, "mail_latest.txt")
        self.ATTACHMENT_DIR = os.path.join(self.MAIL_DIR, "attachments")

        self.PARQUET_DIR = os.path.join(self.DOMAIN_ROOT, "parquet", "output") # output 폴더: parquet들 저장
        self.ENTITIES_PATH = os.path.join(self.PARQUET_DIR, "entities.parquet") # 노드 데이터: 엔티티 목록
        self.RELATIONSHIPS_PATH = os.path.join(self.PARQUET_DIR, "relationships.parquet") # 엣지 데이터: 엔티티 간 관계
        self.COMMUNITIES_PATH = os.path.join(self.PARQUET_DIR, "communities.parquet") # 커뮤니티 데이터: 군집화한 노드 그룹 정보
        self.MAIL_STATICS_PATH = os.path.join(self.PARQUET_DIR, "statics")
        self.MAIL_CONTACTS_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_contact_stats.json")
        self.MAIL_KEYWORDS_PATH  = os.path.join(self.MAIL_STATICS_PATH, "mail_keyword_stats.json")
        self.MAIL_SUMMARIES_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_summaries.json")
        self.MAIL_PHOTOS_PATH    = os.path.join(self.MAIL_STATICS_PATH, "contact_photos.json")
        self.MAIL_AVATARS_PATH  = os.path.join(self.MAIL_STATICS_PATH, "person_avatars.json")
        self.AVATAR_IMAGES_DIR  = os.path.join(self.MAIL_STATICS_PATH, "avatars")
        self.MAIL_MESSAGE_CACHE_PATH = os.path.join(self.MAIL_STATICS_PATH, "mail_message_cache.json")
        self.UPDATE_DIR = os.path.join(self.GRAPHRAG_ROOT, "update_output")
        self.MAX_MAILS = _MAX_MAILS_CONFIG.get(user_id, None)
        self.ACCOUNT_META_PATH = os.path.join(self.USER_ROOT, ACCOUNT_META_FILENAME)
        _ensure_account_meta(self)

# 계정 폴더가 이미 존재하는 경우에만 원본 user_id를 메타 파일로 남겨서
# 나중에 폴더명(디렉터리 sanitize로 인해 원본 문자열이 손실됨)만으로도
# 실제 계정 목록을 복원할 수 있게 한다. (/accounts 엔드포인트에서 사용)
def _ensure_account_meta(paths: "UserPaths"):
    if not os.path.isdir(paths.USER_ROOT) or os.path.exists(paths.ACCOUNT_META_PATH):
        return
    try:
        with open(paths.ACCOUNT_META_PATH, "w", encoding="utf-8") as f:
            json.dump({"user_id": paths.USER_ID}, f, ensure_ascii=False)
    except OSError:
        pass

# user_data 디렉터리를 훑어서 (user_id, 인덱싱 완료 여부) 목록을 반환
def list_accounts(base_dir: str) -> list[dict]:
    from util.graphrag import _is_index_ready

    user_data_dir = os.path.join(base_dir, "user_data")
    accounts = []

    if os.path.isdir(user_data_dir):
        for dir_name in sorted(os.listdir(user_data_dir)):
            dir_path = os.path.join(user_data_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue
            # "base"(이메일) 도메인 데이터가 실제로 있는 폴더만 계정으로 인정.
            # 카카오톡 전용 폴더({room}/kakao/만 있고 {room}/base/는 없음)가 이메일 계정 셀렉터에
            # "인덱싱 중" 유령 계정으로 뜨는 걸 방지함.
            if not os.path.isdir(os.path.join(dir_path, "base")):
                continue

            meta_path = os.path.join(dir_path, ACCOUNT_META_FILENAME)
            user_id = None
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        user_id = (json.load(f).get("user_id") or "").strip()
                except (OSError, json.JSONDecodeError):
                    user_id = None

            if not user_id:
                # 메타 파일이 아직 없는 계정(이 기능 추가 이전에 만들어진 폴더) →
                # 폴더명에서 최선으로 역추정만 하고, 파일에 쓰지는 않는다.
                user_id = dir_name.replace("_at_", "@", 1).replace("_", ".")

            # TODO: 실제 domain 선택 로직이 생기면 "base" 리터럴을 그 값으로 교체
            paths = UserPaths(base_dir, user_id, "base")
            accounts.append({
                "user_id": user_id,
                "indexed": _is_index_ready(paths),
            })

    return accounts

# 인덱싱까지 완료된 계정의 user_id만 반환 (연합 검색 대상 계정 목록으로 사용)
def list_indexed_user_ids(base_dir: str) -> list[str]:
    return [a["user_id"] for a in list_accounts(base_dir) if a["indexed"]]

# 도메인별 공용 settings.yaml, prompts를 사용자 parquet 폴더에 복사
def user_graphrag_init(paths):
    domain = paths.DOMAIN

    # 1. parquet 폴더 보장
    os.makedirs(paths.GRAPHRAG_ROOT, exist_ok=True)

    # 2. 도메인별 공용 템플릿 존재 확인
    if not os.path.exists(GRAPHRAG_SETTINGS_DIR(domain)):
        raise FileNotFoundError(
            f"[ERROR] {domain} 공용 settings.yaml 없음: {GRAPHRAG_SETTINGS_DIR(domain)}"
        )
    if not os.path.exists(GRAPHRAG_PROMPTS_DIR(domain)):
        raise FileNotFoundError(
            f"[ERROR] {domain} 공용 prompts 폴더 없음: {GRAPHRAG_PROMPTS_DIR(domain)}"
        )

    # 3. settings.yaml복사(있으면 덮어쓰기), 항상 최신 settings.yaml을 사용하기 위함
    shutil.copy2(GRAPHRAG_SETTINGS_DIR(domain), paths.USER_GRAPH_SETTINGS_PATH)
    print(f"[INIT] settings.yaml 복사/덮어쓰기 완료 → {paths.USER_GRAPH_SETTINGS_PATH}")

    # 4. prompts 폴더 전체 복사(있으면 덮어쓰기), 항상 최신 prompts를 사용하기 위함
    shutil.copytree(
        GRAPHRAG_PROMPTS_DIR(domain),
        paths.USER_GRAPH_PROMPTS_PATH,
        dirs_exist_ok=True  # 기존 프롬프트가 있으면 덮어쓰기
    )