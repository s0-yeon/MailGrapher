# src/util/graphrag_query.py
# 캐싱된 서치 엔진 객체 직접 호출해서 검색 속도 개선함

import os
import re
import asyncio # 비동기 실행 지원 (LocalSearch/GlobalSearch.search()가 async 함수라 필요)
import traceback
import threading
import time
import openai

from util.graphrag_engine import get_engines, get_and_reset_usage # 유저별 캐싱된 local. global 엔진 반환 함수 임포트
from util.database.db_writer import save_query_to_db
from config.settings import MAIL_BLOCK_SEP

# 연합 검색은 query 테이블에 계정마다 행을 따로 남기지 않고 딱 1행만 저장한다.
# user_id는 앱 전체에서 하나로 통일돼 있어 어느 계정으로 저장해도 동일하므로 primary_user_id는 FK 채우기용일 뿐이고,
# 실제로 참고한 계정 목록은 refer_kg에 기록한다. 토큰 사용량은 참여한 계정들의 사용량을 전부 더한 총합으로 저장한다.
def _save_federated_query(accounts_paths: list, primary_user_id: str, original_message: str,
                           elapsed: float, method: str, answer: str, refer_accounts: list = None):
    total_input = 0
    total_output = 0
    model_name = None
    for paths in accounts_paths:
        usage = get_and_reset_usage(paths.USER_ID, method)
        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]
        if not model_name and usage["model_name"]:
            model_name = usage["model_name"]

    # 어떤 계정이 실제로 근거가 됐는지 확신할 수 없으면(로컬 검색에서 인용이 하나도 안 잡힌 경우 등)
    # 참여 계정 전체로 채워넣지 않고 그냥 비워둔다 — 억지로 채운 값은 틀린 정보를 남기는 것과 같음
    refer_kg = ", ".join(refer_accounts) if refer_accounts else None

    try:
        save_query_to_db(
            primary_user_id, original_message, elapsed, method,
            model_name=model_name,
            input_tokens=total_input,
            output_tokens=total_output,
            answer=answer,
            refer_kg=refer_kg,
        )
    except Exception as e:
        print(f"[WARN] 연합 검색 query DB 저장 실패 (무시): {e}")

# 계정의 mail_latest.txt에서 "메일 ID → 실제 발신인" 매핑을 읽어온다.
# GraphRAG가 조립한 컨텍스트나 LLM 답변을 정규식으로 다시 파싱하면 내부 포맷/토큰 잘림/LLM의 필드 혼동 때문에
# 틀리기 쉬워서, 원본 파일에서 직접 읽어와 정답으로 덮어쓰는 방식이 훨씬 안정적이다.
def _load_account_sender_map(paths) -> dict:
    try:
        with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    sender_map = {}
    for block in text.split(MAIL_BLOCK_SEP):
        id_m = re.search(r'^ID:\s*(.+?)\s*$', block, re.MULTILINE)
        sender_m = re.search(r'^발신인:\s*(.+?)\s*$', block, re.MULTILINE)
        if id_m and sender_m:
            sender_map[id_m.group(1).strip().lower()] = sender_m.group(1).strip()
    return sender_map

# 답변에서 "ID: xxx" 뽑을 때 \S+ 가 뒤에 붙은 문장부호(대괄호, 마침표 등)까지 같이 잡아버리는 경우가 있어
# (예: "[ID: xxx@icloud.com]" → "xxx@icloud.com]") 매칭 전에 제거해준다
def _strip_id_punct(mail_id: str) -> str:
    return mail_id.strip(']),.;:》」』')

# LLM이 답변에서 메일을 1, 2, 3... 처럼 순번을 매기다가 그 순번을 그대로 "ID: 2"로 써버리는 경우가 있음.
# 실제 메일 ID는 항상 길고(16자리 hex, 또는 '@'가 포함된 긴 문자열) 이런 순수 짧은 숫자가 나올 수 없으므로,
# 매칭 시도(=필연적으로 실패해서 "알 수 없음"으로 뜸) 자체를 하지 않고 미리 걸러낸다.
def _is_plausible_mail_id(mail_id: str) -> bool:
    return not (mail_id.isdigit() and len(mail_id) <= 6)

# ID/계정 필드는 근거 추출(계정 매칭, 발신인 교정)에만 쓰고 사용자에게 보여줄 답변에서는 지운다.
# "- ID: xxx"처럼 단독 줄이면 줄째로, "1. ID: xxx"처럼 번호 뒤에 붙어있으면 그 부분만 지우는데,
# 후자의 경우 번호(예: "1.")만 남고 내용이 텅 빈 줄이 생기므로 그것도 같이 정리한다.
def strip_ids_for_display(text: str) -> str:
    text = re.sub(r'^[ \t]*[-*]?[ \t]*(ID|계정):\s*\S+[ \t]*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'(ID|계정):\s*\S+', '', text)
    text = re.sub(r'^[ \t]*(?:\d+[.)]|[-*])[ \t]*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

# cli 호출 방식인 _run_graphrag() 대체용 (get_engines()로 캐싱된 LocalSearch, globalSearch 객체 직접 호출)
def run_graphrag_query(message: str, original_message: str, paths, method: str = "local") -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None} # 스레드 간에 결과나 에러를 공유하기 위한 컨테이너 (스레드 return 값 직접 전달 못해서 dict로 우회함)

    def _run(): # 별도 스레드에서 실행할 함수 (플라스크가 자체 이벤트 루프 갖고 있어서 asyncio.run() 바로 쓰면 충돌날수도 있음)
        loop = asyncio.new_event_loop() # 현재 스레드 전용 새 이벤트 루프 생성
        asyncio.set_event_loop(loop) # 현재 스레드의 기본 루프로 설정
        try:
            async def _search(): # 실제 검색 로직 담은 함수
                output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                local_engine, global_engine = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT) # 유저별 캐싱된 local + global 엔진 둘 다 가져오기 (캐시에서 재사용)
                engine = local_engine if method == "local" else global_engine
                result = await engine.search(message) # cli subprocess 대신 엔진 객체 함수 호출 (subprocess 생성이나 종료가 없어서 속도 빨라짐)
                answer = result.response # 검색 결과 객체에서 답변 텍스트 추출
                answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', answer) # graphrag가 답변에 삽입하는 출처 태그 제거
                answer = re.sub(r'\*+|#+', '', answer) # 마크다운 강조 기호 제거 (**, ## 등)
                answer = answer.strip() # 앞뒤 공백 제거

                # 1차: 답변 텍스트에서 ID 추출
                found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', answer)]
                found = [m for m in found if _is_plausible_mail_id(m)]

                # 2차: LLM이 답변에 ID를 직접 안 썼을 때 → context_text(LLM에 넘긴 원본 청크)에서 추출
                if not found:
                    ctx = result.context_text
                    if isinstance(ctx, list):
                        ctx = '\n'.join(ctx)
                    if isinstance(ctx, str):
                        found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', ctx)]
                        found = [m for m in found if _is_plausible_mail_id(m)]

                # 순서 유지하면서 중복 제거. account를 같이 넣어서 연합 검색(run_federated_local_search) 결과와 형태를 통일함
                seen = set()
                source_ids = []
                for id in found:
                    if id not in seen:
                        seen.add(id)
                        source_ids.append({"id": id, "account": paths.USER_ID})

                display_answer = strip_ids_for_display(answer)

                return display_answer, source_ids # 답변 텍스트와 근거 메일 ID 목록을 튜플로 반환

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # 완전히 새로운 스레드에서 _run 실행
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=120)  # 최대 120초 대기. 120초 넘어도 답이 안 오면 런타임에러 발생 및 CLI fallback로 넘어감. (스레드 종료 ㄴㄴ)

    if t.is_alive():
        raise RuntimeError("graphrag 검색 타임아웃 (120초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    print(f"[ENGINE] 검색 완료: {elapsed:.2f}초")
    answer, source_ids = result_container["result"]  # 언패킹
    print(f"[ENGINE] 답변: {answer}")
    print(f"[ENGINE] source_ids: {source_ids}")
    try:
        usage = get_and_reset_usage(paths.USER_ID, method)
        save_query_to_db(
            paths.USER_ID, original_message, elapsed, method,
            model_name=usage["model_name"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            answer=answer,
        )
    except Exception as e:
        print(f"[WARN] query DB 저장 실패 (무시): {e}")
    return answer, source_ids  # app.py의 _worker()로 튜플 반환

# 여러 계정의 로컬 서치 컨텍스트(벡터 검색 결과)를 계정별로 따로 조립한 뒤,
# 답변 생성 LLM 호출은 전체를 합쳐서 딱 한 번만 실행한다.
# (계정 수만큼 비싼 답변 생성 호출이 늘어나는 걸 막기 위함 — 컨텍스트 조립은 임베딩 검색이라 저렴함)
def run_federated_local_search(message: str, original_message: str, accounts_paths: list,
                                primary_user_id: str = None, per_account_max_tokens: int = 3000) -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _search():
                engines = []
                for paths in accounts_paths:
                    try:
                        output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                        local_engine, _ = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT)
                        engines.append((paths, local_engine))
                    except Exception as e:
                        print(f"[FEDERATED] {paths.USER_ID} 엔진 로드 실패, 스킵: {e}")

                if not engines:
                    return "인덱싱된 계정이 없습니다.", []

                combined_chunks = []
                account_sender_maps = {}  # user_id -> {메일ID(소문자): 진짜 발신인 값}
                for paths, engine in engines:
                    context_result = engine.context_builder.build_context(
                        query=message,
                        **engine.context_builder_params,
                    )
                    chunk_text = context_result.context_chunks
                    if isinstance(chunk_text, list):
                        chunk_text = "\n".join(chunk_text)

                    # 계정 하나가 프롬프트 예산을 독점하지 않도록 계정별로 토큰 상한을 둠
                    tokens = engine.token_encoder.encode(chunk_text)
                    if len(tokens) > per_account_max_tokens:
                        chunk_text = engine.token_encoder.decode(tokens[:per_account_max_tokens])

                    account_sender_maps[paths.USER_ID] = _load_account_sender_map(paths)
                    used_tokens = min(len(tokens), per_account_max_tokens)
                    print(f"[FEDERATED] {paths.USER_ID}: 컨텍스트 {used_tokens}토큰, 보유 메일 {len(account_sender_maps[paths.USER_ID])}건")

                    combined_chunks.append(f"[계정: {paths.USER_ID}]\n{chunk_text}")

                merged_context = "\n\n".join(combined_chunks)

                # 답변에 나온 ID로 원본 데이터를 찾는다. 완전 일치 → 도메인 빠진 경우 → 일부만 옮겨 적힌 경우 순으로 완화.
                # 반환값: (원본 파일 기준 진짜 ID, 그 계정 user_id) 또는 (None, None)
                def _find_real_id(mail_id: str):
                    key = mail_id.lower()

                    for user_id, smap in account_sender_maps.items():
                        if key in smap:
                            return key, user_id

                    key_local = key.split('@')[0]
                    for user_id, smap in account_sender_maps.items():
                        for real_id in smap:
                            if real_id.split('@')[0] == key_local:
                                return real_id, user_id

                    if len(key) >= 8:
                        for user_id, smap in account_sender_maps.items():
                            for real_id in smap:
                                if real_id.startswith(key) or key.startswith(real_id):
                                    return real_id, user_id

                    return None, None

                def _resolve_account(mail_id: str):
                    _, user_id = _find_real_id(mail_id)
                    if not user_id:
                        print(f"[FEDERATED] 계정 매칭 실패, 원본 ID: {mail_id!r}")
                    return user_id

                # 답변 생성 설정(system_prompt/model 등)은 계정마다 동일하므로 첫 번째 엔진 것을 그대로 재사용
                _, first_engine = engines[0]
                search_prompt = first_engine.system_prompt.format(
                    context_data=merged_context,
                    response_type=first_engine.response_type,
                )
                # 여러 계정 데이터가 섞여 있다는 것과, 각 데이터 앞의 [계정: ...] 라벨을 알려줌.
                # 관련 내용이 없는 계정까지 억지로 채우지 말고 실제로 관련 있는 계정만 빠짐없이 다루게 함.
                # 계정 언급은 "근거 계정" 영역에서 별도로 보여주므로 답변 본문에서 굳이 언급하라고 하지는 않음.
                search_prompt += (
                    "\n\n추가 지시사항: 위 데이터는 서로 다른 여러 이메일 계정에서 수집되었으며, "
                    "각 데이터 블록 앞에 [계정: 이메일주소] 형태로 출처 계정이 표시되어 있다. "
                    "질문과 관련된 내용이 여러 계정에 걸쳐 있다면 한쪽 계정에 치우치지 말고 "
                    "관련 있는 계정을 빠짐없이 골고루 다루되, 특정 계정에 관련 내용이 없으면 "
                    "그 계정은 억지로 언급하지 말고 실제로 관련 있는 내용만으로 답하라. "
                    "원본 데이터에는 메일마다 'ID:'와 '발신인:'이 서로 다른 별개 필드로 있으니 "
                    "절대 혼동하지 말 것 — 발신자를 쓸 때는 반드시 '발신인:' 필드의 이메일 주소를 쓰고, "
                    "'ID:' 필드의 값을 발신자 자리에 쓰지 마라. "
                    "목록으로 나열하든 묶어서 요약하든 답변 형식과 무관하게, 실제로 언급/근거로 삼은 "
                    "메일마다 'ID: 원본ID값'을 요약 문장에 섞어 쓰지 말고 그 메일 항목의 별도 줄로 표기하라. "
                    "'ID:' 뒤에는 반드시 데이터에 있는 실제 ID 값을 정확히 그대로 옮겨 적어야 한다. "
                    "답변에서 메일을 1번, 2번처럼 순서대로 나열하더라도 그 순번을 'ID: 1', 'ID: 2'처럼 "
                    "ID인 것으로 쓰지 마라 — 그건 데이터에 없는 값을 지어내는 것이다. "
                    "그리고 언급/근거로 삼은 메일마다 'ID:', '발신인:'과 같은 줄에 '계정: 이메일주소' 줄도 "
                    "추가하라 — 그 메일이 어느 [계정: ...] 블록에서 나온 데이터인지, 컨텍스트에 표시된 "
                    "계정 이메일 주소를 정확히 그대로 옮겨 적어라."
                )
                history_messages = [{"role": "system", "content": search_prompt}]

                # 여러 계정 내용을 종합하는 답변이라 계정 하나만 볼 때보다 더 길어질 수 있어 응답 길이 상한을 넉넉히 둠
                federated_model_params = dict(first_engine.model_params)
                federated_model_params["max_tokens"] = max(
                    federated_model_params.get("max_tokens", 2000), 2000 * len(engines)
                )

                full_response = ""
                async for token in first_engine.model.achat_stream(
                    prompt=message,
                    history=history_messages,
                    model_parameters=federated_model_params,
                ):
                    full_response += token

                answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', full_response)
                answer = re.sub(r'\*+|#+', '', answer)
                answer = answer.strip()

                # 프롬프트로 "발신인 자리에 ID값 쓰지 마라"고 지시해도 LLM이 종종 혼동해서 틀리게 쓰므로,
                # 아예 각 항목의 ID로 원본 데이터를 찾아 진짜 발신인 값으로 강제로 덮어쓴다.
                # (항목을 문단 단위로 나눠서, 그 문단에 있는 ID에 해당하는 발신인만 그 문단 안에서 교체)
                def _fix_paragraph_sender(p):
                    id_m = re.search(r'ID:\s*(\S+)', p)
                    if not id_m:
                        return p
                    real_id, user_id = _find_real_id(_strip_id_punct(id_m.group(1)))
                    if not real_id:
                        return p
                    real_sender = account_sender_maps[user_id].get(real_id)
                    if not real_sender or not re.search(r'발신인:', p):
                        return p
                    return re.sub(r'(발신인:\s*)(.*)$', lambda m: m.group(1) + real_sender, p, count=1, flags=re.MULTILINE)

                answer = '\n\n'.join(_fix_paragraph_sender(p) for p in answer.split('\n\n'))

                # 계정 이메일은 22자짜리 무작위 Message-ID보다 훨씬 짧고 컨텍스트에 반복 등장해서
                # LLM이 그대로 옮겨 적기 쉬우므로, ID→계정 역추적 대신 LLM이 직접 쓴 '계정:' 값을 우선 신뢰한다.
                # 실제 인덱싱된 계정 목록에 없는 값(오타/환각)은 조용히 버린다 — 확신 없는 건 안 보여준다는 원칙 유지.
                valid_accounts = {p.USER_ID.strip().lower(): p.USER_ID for p, _ in engines}
                cited_accounts = []
                for m in re.findall(r'계정:\s*(\S+)', answer):
                    real = valid_accounts.get(_strip_id_punct(m).strip().lower())
                    if real:
                        cited_accounts.append(real)

                if cited_accounts:
                    source_ids = [{"id": None, "account": acc} for acc in cited_accounts]
                else:
                    # LLM이 '계정:'을 안 썼을 때만 예전 ID 기반 역추적으로 폴백
                    found = [_strip_id_punct(m) for m in re.findall(r'ID:\s*(\S+)', answer)]
                    found = [m for m in found if _is_plausible_mail_id(m)]
                    seen = set()
                    source_ids = []
                    for id in found:
                        if id not in seen:
                            seen.add(id)
                            source_ids.append({"id": id, "account": _resolve_account(id)})

                display_answer = strip_ids_for_display(answer)

                return display_answer, source_ids

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # 계정 수가 많으면 컨텍스트 조립(임베딩 검색)에 시간이 더 걸릴 수 있어 기존 120초보다 여유를 둠
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=180)

    if t.is_alive():
        raise RuntimeError("연합 검색 타임아웃 (180초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    answer, source_ids = result_container["result"]
    print(f"[FEDERATED] 검색 완료: {elapsed:.2f}초, 계정 {len(accounts_paths)}개")

    # source_ids에서 실제로 인용된 계정만 refer_kg에 남긴다 (인용이 없으면 refer_kg는 비워둠)
    referenced = []
    seen_accounts = set()
    for s in source_ids:
        acc = s.get("account")
        if acc and acc not in seen_accounts:
            seen_accounts.add(acc)
            referenced.append(acc)
    _save_federated_query(
        accounts_paths, primary_user_id or accounts_paths[0].USER_ID,
        original_message, elapsed, "local", answer, referenced,
    )
    return answer, source_ids

# 여러 계정의 글로벌 서치(map-reduce)를 연합한다.
# map 단계(계정별 커뮤니티 보고서 요약)는 계정마다 각자 돌리되(데이터량만큼 필요한 비용이라 못 줄임),
# reduce 단계(최종 답변 합성)만 전체 계정의 map 결과를 모아 딱 1번만 실행해서 비용을 아낀다.
# 참고: _map_response_single_batch / _reduce_response는 graphrag 라이브러리의 비공개(밑줄) 메서드라
# 버전이 바뀌면 시그니처가 달라질 수 있다.
def run_federated_global_search(message: str, original_message: str, accounts_paths: list,
                                 primary_user_id: str = None) -> tuple[str, list]:
    start_time = time.time()
    result_container = {"result": None, "error": None}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _search():
                engines = []
                for paths in accounts_paths:
                    try:
                        output_dir = os.path.join(paths.GRAPHRAG_ROOT, "output")
                        _, global_engine = get_engines(paths.USER_ID, output_dir, paths.GRAPHRAG_ROOT)
                        engines.append((paths, global_engine))
                    except Exception as e:
                        print(f"[FEDERATED-GLOBAL] {paths.USER_ID} 엔진 로드 실패, 스킵: {e}")

                if not engines:
                    return "인덱싱된 계정이 없습니다.", [], []

                all_map_responses = []
                for paths, engine in engines:
                    context_result = await engine.context_builder.build_context(
                        query=message,
                        **engine.context_builder_params,
                    )
                    # map: 커뮤니티 보고서 묶음마다 개별 LLM 호출 (계정별로 각자 실행)
                    map_responses = await asyncio.gather(*[
                        engine._map_response_single_batch(context_data=data, query=message, **engine.map_llm_params)
                        for data in context_result.context_chunks
                    ])
                    print(f"[FEDERATED-GLOBAL] {paths.USER_ID}: map 배치 {len(map_responses)}개")
                    all_map_responses.extend(map_responses)

                # reduce: 전체 계정의 map 결과를 모아 딱 1번만 합성 (계정 수와 무관하게 항상 1번)
                _, first_engine = engines[0]
                reduce_response = await first_engine._reduce_response(
                    map_responses=all_map_responses,
                    query=message,
                    **first_engine.reduce_llm_params,
                )

                answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', reduce_response.response)
                answer = re.sub(r'\*+|#+', '', answer)
                answer = answer.strip()

                # 글로벌 서치는 원래도 개별 메일을 인용하는 방식이 아니라(전체 경향/패턴 요약) 근거 계정이 없음.
                # 다만 map 단계가 실제로 돌아간 계정 목록은 확실하므로 refer_kg용으로 같이 반환한다.
                participated = [paths.USER_ID for paths, _ in engines]
                return answer, [], participated

            result_container["result"] = loop.run_until_complete(_search())

        except Exception as e:
            traceback.print_exc()
            result_container["error"] = e
        finally:
            loop.close()

    # map 단계가 계정 수만큼 늘어날 수 있어 넉넉하게 대기
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=240)

    if t.is_alive():
        raise RuntimeError("연합 글로벌 검색 타임아웃 (240초)")

    if result_container["error"]:
        raise result_container["error"]

    elapsed = time.time() - start_time
    answer, source_ids, participated = result_container["result"]
    print(f"[FEDERATED-GLOBAL] 검색 완료: {elapsed:.2f}초, 계정 {len(accounts_paths)}개")
    _save_federated_query(
        accounts_paths, primary_user_id or accounts_paths[0].USER_ID,
        original_message, elapsed, "global", answer, participated,
    )
    return answer, source_ids

# 질의 방법 분류
def _classify_query_method(message: str) -> str:
    prompt = f"""다음 질문이 로컬 검색(특정 메일·인물·날짜·주제)에 적합한지,
                글로벌 검색(전체 경향·요약·패턴·빈도)에 적합한지 판단하라.
                "local" 또는 "global" 중 하나만 반환하라.

                질문: {message}"""

    client = openai.OpenAI(api_key=os.environ.get("GRAPHRAG_API_KEY"))

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
        temperature=0
    )

    method = res.choices[0].message.content.strip().lower()
    print(f"[CLASSIFY] 질의: {message[:30]} → {method}")
    return method if method in ("local", "global") else "local"
