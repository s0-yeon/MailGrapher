# src/app.py
import datetime
import os
import re
import subprocess
import time
import sys
import json
import threading
import uuid
import openai  
import base64
import requests
import shutil
import zlib
import traceback
import urllib.parse
import imaplib     
from concurrent.futures import ( 
    ThreadPoolExecutor,
    as_completed 
)
from dotenv import load_dotenv
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    Response,
    stream_with_context
)
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document
import olefile
import csv
from pptx import Presentation
from openpyxl import load_workbook

# Job 이용 공통함수 import
from util.jobs.job_store import *
from config.settings import *

# RAG_ENGINE(config/settings.py)에 따라 인덱싱 파이프라인 진입점을 고른다.
# job_run_graphrag.py/job_run_lightrag.py 둘 다 함수 이름을
# start_graph_pipeline_background/start_graph_update_pipeline_background로 맞춰뒀기 때문에
# import 경로만 바뀌고 아래에서 이 함수들을 부르는 코드는 그대로 쓸 수 있다.
if RAG_ENGINE == "lightrag":
    from util.jobs.job_run_lightrag import (
        start_graph_pipeline_background,
        start_graph_update_pipeline_background
    )
elif RAG_ENGINE == "graphrag":
    from util.jobs.job_run_graphrag import (
        start_graph_pipeline_background,
        start_graph_update_pipeline_background
    )

# 날짜 범위 질의(예: "어제 메일 보여줘") 처리 함수도 RAG_ENGINE에 따라 고른다.
# GraphRAG 버전은 entities.parquet을 읽는데, LightRAG 버전(lightrag_date_query.py)은
# 원본 mail_latest.txt를 직접 읽는다 — parquet이 없는 LightRAG 모드에서 이 함수가
# 그대로 크래시 나던 문제를 여기서 고쳤다.
if RAG_ENGINE == "lightrag":
    from util.lightrag_backend.lightrag_date_query import run_date_range_query
elif RAG_ENGINE == "graphrag":
    from util.graphrag_date_query import run_date_range_query

from util.user_path import UserPaths, list_accounts, list_indexed_user_ids
from util.database.db_reader import (
    get_mail_stats,
    get_keyword_stats,
    get_mail_sync_stats,
    get_user_rating_stats,
    get_high_affinity_person_stats,
    get_keywords_by_person_date,
    get_mail_date_range,
    get_mail_exchange_stats,
    calculate_eis,
    get_person_descriptions,
    get_date_range_person_stats,
    get_person_mail_ids_in_range
)
from util.file_manager import (
    _sanitize_filename
)
from util.attachment_manager import (
    _save_attachment_from_base64,
    _extract_text_from_pdf,
    _extract_text_from_docx,
    _extract_text_from_hwp,
    _extract_text_from_txt,
    _extract_text_from_pptx,
    _extract_text_from_xlsx,
    _extract_text_from_csv,
)
if RAG_ENGINE == "lightrag":
    from util.jobs.job_run_lightrag import _summarize_attachment_text, _merge_summarized_attachments
elif RAG_ENGINE == "graphrag":
    from util.jobs.job_run_graphrag import _summarize_attachment_text, _merge_summarized_attachments
from util.database.db_writer import (
    save_query_to_db,
    init_processed_attachments_table,
    init_mail_keyword_table,
    filter_unprocessed_attachments,
    mark_attachments_as_processed,
    rebuild_keyword_mail,
)
from util.extract_statics import start_statics_pipeline_background
from util.avatar_generator import (
    get_cached_person_avatars,
    generate_person_avatars_batch,
    get_cached_self_avatar,
    generate_self_avatar,
)
from util.sse_broadcaster import (
    subscribe,
    unsubscribe,
    broadcast
)
from config.db import get_db_connection
from util.graphrag import (
    _run_graphrag,
    _is_index_ready
)
from util.graphrag_query import _classify_query_method

# _is_index_ready(GraphRAG, output/stats.json 존재 여부)와 lightrag_engine.is_index_ready
# (LightRAG, graphml 파일 존재 여부) 중 RAG_ENGINE에 맞는 쪽을 골라서 판단하는 공용 헬퍼.
# append 전환 판단(/upload)과 첨부파일 처리 게이트(/upload-attachments)가 이걸 같이 쓴다.
def _index_ready(paths) -> bool:
    if RAG_ENGINE == "lightrag":
        from util.lightrag_backend.lightrag_engine import is_index_ready
        return is_index_ready(paths.LIGHTRAG_ROOT)
    elif RAG_ENGINE == "graphrag":
        return _is_index_ready(paths)
from util.mail_data_manager import (
    _read_latest_text,
    _extract_message_ids,
    _split_mail_blocks,
    _extract_mail_id_from_block,
    _renumber_mail_blocks,
    _extract_block_for_sort,
    _build_mail_csv
)
from util.file_manager import _delete_incremental_files
from util.imap_connect import (
    _imap_parse_list_line,
    _imap_fetch_content
)
from util.message_parser import (
    parse_message_export,
    build_message_blocks,
    guess_room_name,
    build_room_id,
)
# 환경변수 로드
load_dotenv("src/parquet/.env")

# RAG_ENGINE(GraphRAG/LightRAG 스위치)은 config/settings.py에 상수로 정의돼 있고
# 위 "from config.settings import *"로 이미 가져온 상태 — 여기서 따로 안 읽는다.
# 서버 시작 시 터미널에서 바로 보이도록 한 번 크게 찍어준다.
print("=" * 60)
print(f"[RAG_ENGINE] 서버가 사용할 RAG 엔진: {RAG_ENGINE.upper()}")
print("=" * 60)

# Flask 앱 초기화
app = Flask(__name__)
CORS(app)

# 서버 시작 시 테이블 초기화 실행
init_processed_attachments_table()
init_mail_keyword_table()

# 한글 출력 시 깨지거나 에러 나는 것 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 근거메일보기 버튼
# def _extract_source_mail_ids(answer: str) -> list:
#     return list(set(re.findall(r'ID:\s*([0-9A-Fa-f]{16})', answer)))

# 엔드포인트: POST /run-query-async
@app.route('/run-query-async', methods=['POST'])
def run_query_async():
    data = request.json or {}

    print("[DEBUG] content_type =", request.content_type)
    print("[DEBUG] raw body =", request.data)
    print("[DEBUG] parsed data =", data)

    if data is None:
        return jsonify({'error': 'JSON 본문을 읽지 못했습니다.'}), 400

    message = request.json.get('message', '')
    resMethod = request.json.get('resMethod', 'local')
    resType = request.json.get('resType', 'text')
    user_id = data.get('user_id', '').strip()
    domain = (data.get('domain') or 'mail').strip().lower()

    if not str(message).strip():
        return jsonify({'error': 'message가 비어있습니다.'}), 400

    if not user_id:
        return jsonify({'error': 'user_id가 비어있습니다.'}), 400

    print("[DEBUG] message =", repr(message))
    print("[DEBUG] user_id =", repr(user_id))

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="query")
    update_job(job_id, status="pending", result=None, resType=resType)

    def _worker():  # 백그라운드 스레드에서 실행되는 실제 작업 함수
        try:
            env = os.environ.copy()
            env["USER_ID"] = user_id

            # local/global, 날짜 범위 쿼리 모두 해당 도메인에서 인덱싱된 계정(또는 카카오 대화방) 전체를 대상으로 함(연합 검색).
            accounts_paths = [UserPaths(BASE_DIR, uid, domain) for uid in list_indexed_user_ids(BASE_DIR, domain)]

            # 인덱싱된 계정/방이 하나도 없을 때만 프론트가 보낸 user_id로 폴백 경로를 만든다.
            # UserPaths()는 생성 시점에 폴더/account.json을 만드는 부작용이 있어서, 메시지 도메인처럼
            # user_id가 실제 방을 가리키지 않는 자리표시자("message")인 경우 매 요청마다 유령 계정
            # 폴더가 다시 생기는 걸 방지하기 위해 정말 필요할 때만(인덱싱된 계정이 없을 때만) 만든다.
            if not accounts_paths:
                accounts_paths = [UserPaths(BASE_DIR, user_id, domain)]

            fallback_paths = accounts_paths[0]

            # 날짜 범위 쿼리 직접 필터링(parquet)은 "발신인:/제목:" 같은 이메일 전용 필드 포맷을 가정하고
            # 있어서 카카오 도메인엔 안 맞음 — mail 도메인일 때만 시도하고, 그 외엔 곧장 GraphRAG/LightRAG로 보낸다.
            # accounts_paths 전체(인덱싱된 계정 전부)를 대상으로 연합해서 필터링한다.
            answer = run_date_range_query(message, accounts_paths) if domain == "mail" else None # 이게 None이면 GraphRAG/LightRAG로
            source_ids = []  # 초기화
            if answer is None:
                full_message = message + " 영어 말고 한국어로 답변해줘."

                if RAG_ENGINE == "lightrag":
                    from util.lightrag_backend.lightrag_query import _classify_query_method as _classify_lightrag_method, run_federated_search, run_lightrag_query
                    # GraphRAG는 local/global 둘뿐이지만 LightRAG는 6개 모드(local/global/hybrid/
                    # naive/mix/bypass)라 분류기도, 아래 호출도 모드를 그대로 통과시킨다.
                    resMethod = _classify_lightrag_method(message)
                    print(f"[QUERY] RAG_ENGINE=lightrag mode={resMethod}")

                    if len(accounts_paths) == 1:
                        # 계정(또는 방)이 하나뿐이면 연합 검색이 의미가 없으니 바로 단일 엔진으로 검색한다.
                        answer, source_ids = run_lightrag_query(full_message, message, fallback_paths, method=resMethod)
                    else:
                        try:
                            answer, source_ids = run_federated_search(full_message, message, accounts_paths, resMethod, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE][lightrag] 연합 검색 실패, 선택된 계정으로 폴백: {e}")
                            # LightRAG는 CLI가 없어서 GraphRAG처럼 마지막에 subprocess로 더 폴백할 데가 없다.
                            # 여기서도 실패하면 바깥 except가 잡아서 job을 error 상태로 남긴다.
                            answer, source_ids = run_lightrag_query(full_message, message, fallback_paths, method=resMethod)

                elif RAG_ENGINE == "graphrag":
                    from util.graphrag_query import run_graphrag_query, run_federated_local_search, run_federated_global_search
                    resMethod = _classify_query_method(message)
                    print(f"[QUERY] RAG_ENGINE=graphrag mode={resMethod}")

                    if len(accounts_paths) == 1:
                        # 계정(또는 방)이 하나뿐이면 연합 검색(계정 라벨링/ID 역추적)이 의미가 없으니
                        # 바로 단일 엔진으로 검색한다.
                        try:
                            answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                        except Exception as e2:
                            print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                            answer = _run_graphrag(full_message, message, resMethod, fallback_paths, resType)
                    elif resMethod == "local":
                        try:
                            answer, source_ids = run_federated_local_search(full_message, message, accounts_paths, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE] 연합 검색 실패, 선택된 계정으로 폴백: {e}")
                            try:
                                answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                            except Exception as e2:
                                print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                                answer = _run_graphrag(full_message, message, resMethod, fallback_paths, resType)
                    else:
                        try:
                            answer, source_ids = run_federated_global_search(full_message, message, accounts_paths, primary_user_id=user_id)
                        except Exception as e:
                            print(f"[ENGINE] 연합 글로벌 검색 실패, 선택된 계정으로 폴백: {e}")
                            try: # 엔진 객체 직접 호출 방식
                                answer, source_ids = run_graphrag_query(full_message, message, fallback_paths, method=resMethod)
                            except Exception as e2:
                                # API 방식 실패 시 기존 CLI 방식으로 자동 fallback
                                print(f"[ENGINE] API 실패, CLI fallback: {e2}")
                                answer = _run_graphrag(full_message, message, resMethod, fallback_paths, resType)
                                # source_ids = _extract_source_mail_ids(answer)

            result = answer
            update_job(job_id, status="done", result=result, source_ids=source_ids)

        except Exception as e:
            update_job(job_id, status="error", result=str(e))

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"jobId": job_id})

# 엔드포인트: GET /job-status/<job_id>
@app.route('/job-status/<job_id>', methods=['GET'])
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    if job["status"] == "done" and job["resType"].lower() == "calendar":
        try:
            return jsonify({"status": "done", "data": json.loads(job["result"])})
        except Exception:
            return jsonify({"status": "done", "data": {"events": []}})

    # text 타입: result 필드에 문자열 그대로 반환
    return jsonify({
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "result": job["result"] or "",
        "source_ids": job.get("source_ids") or [],
    })

# 엔드포인트: GET /indexing-stream (SSE)
# 브라우저가 연결을 유지하면 서버가 인덱싱 progress/완료/실패 이벤트를 즉시 push
# 15초마다 keepalive 전송 (연결 유지용)
@app.route("/indexing-stream", methods=["GET"])
def indexing_stream():
    q = subscribe()

    @stream_with_context
    def generate():
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return Response(generate(), content_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                        "ngrok-skip-browser-warning": "true",
                    })

# 엔드포인트: GET /indexing-history
@app.route("/indexing-history", methods=["GET"])
def indexing_history():
    """최근 job 상태 목록 반환 (페이지 로드 시 이전 상태 복원용)"""
    all_jobs = get_all_jobs()
    # 최신순 정렬, 최대 20개
    sorted_jobs = sorted(all_jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)[:20]
    events = []
    for job in sorted_jobs:
        events.append({
            "type": job.get("status", "idle"),
            "job_id": job.get("job_id"),
            "progress": job.get("progress", 0),
            "message": job.get("message", ""),
        })
    return jsonify(events)

# 엔드포인트: POST /run-query (동기 버전)
@app.route('/run-query', methods=['POST'])
def run_query():
    data = request.json or {}
    message = data.get('message', '')
    resMethod = data.get('resMethod', 'local')
    resType = data.get('resType', 'text')
    user_id = (data.get('user_id') or '').strip().lower()

    print(f'message: {message}')
    print(f'resMethod: {resMethod}')
    print(f'resType: {resType}')

    if not str(message).strip():
        return jsonify({'error': 'message가 비어있습니다.'}), 400
    if not user_id:
        return jsonify({'error': 'user_id가 비어있습니다.'}), 400

    paths = UserPaths(BASE_DIR, user_id, "mail")
    message += " 영어 말고 한국어로 답변해줘."

    try:
        if RAG_ENGINE == "lightrag":
            print(f"[QUERY] RAG_ENGINE=lightrag mode={resMethod}")
            from util.lightrag_backend.lightrag_query import run_lightrag_query
            answer, _source_ids = run_lightrag_query(message, message, paths, method=resMethod)
        elif RAG_ENGINE == "graphrag":
            print(f"[QUERY] RAG_ENGINE=graphrag mode={resMethod}")
            answer = _run_graphrag(message, resMethod, paths, resType)
    except Exception as e:  # lightrag 쪽은 RuntimeError 외의 예외도 던질 수 있어 범위를 넓힘
        return jsonify({'error': str(e)}), 500

    return jsonify({'result': answer})

# 수집한 첨부파일을 메인 인덱싱이 시작되기 *전에* 텍스트 추출·요약해서 mail_latest.txt에
# 병합해둔다. 그러면 CSV 빌드(_build_mail_csv)와 GraphRAG 인덱싱이 첨부 내용까지 포함한 채로
# 한 번에 돈다.
def _extract_and_merge_attachments(paths, attachments, user_id):
    unprocessed = filter_unprocessed_attachments(user_id, attachments)
    if not unprocessed:
        return

    attachment_texts_by_mail: dict[str, list[dict]] = {}
    for file_info in unprocessed:
        f_name = file_info.get("name") or "attachment.bin"
        mail_id = str(file_info.get("mail_id") or "").strip()
        try:
            saved_path, original_name = _save_attachment_from_base64(file_info, paths.ATTACHMENT_DIR)
            ext = os.path.splitext(original_name)[-1].lower()
            mime = (file_info.get("mime") or "").lower()
            file_text = ""
            if ext == ".pdf" or "pdf" in mime:      file_text = _extract_text_from_pdf(saved_path)
            elif ext == ".docx":                     file_text = _extract_text_from_docx(saved_path)
            elif ext == ".hwp":                      file_text = _extract_text_from_hwp(saved_path)
            elif ext == ".txt" or "plain" in mime:   file_text = _extract_text_from_txt(saved_path)
            elif ext == ".pptx":                     file_text = _extract_text_from_pptx(saved_path)
            elif ext == ".xlsx":                     file_text = _extract_text_from_xlsx(saved_path)
            elif ext == ".csv":                      file_text = _extract_text_from_csv(saved_path)

            if file_text and file_text.strip():
                summary = _summarize_attachment_text(file_text.strip(), paths, original_name)
                attachment_texts_by_mail.setdefault(mail_id, []).append({"name": original_name, "text": summary})
        except Exception as e:
            print(f"[UPLOAD] 첨부파일 추출 실패 {f_name}: {e}")

    if attachment_texts_by_mail:
        _merge_summarized_attachments(paths.MAIL_LATEST_PATH, attachment_texts_by_mail)
        print(f"[UPLOAD] 첨부파일 {len(attachment_texts_by_mail)}건 본문에 병합 완료")

    mark_attachments_as_processed(user_id, unprocessed)

# 엔드포인트: POST /upload
# mail_id 기반 중복 블록 체크: rewrite/append 관계없이 항상 적용
@app.route("/upload", methods=["POST"])
def upload():
    # 1) 데이터 수신
    data = request.json or {}
    filename = data.get("filename") or f"mail_{int(time.time())}.txt"
    mail_platform = (data.get("mail_platform") or "gmail").strip().lower()
    content = data.get("content") or ""
    attachments = data.get("attachment") or []
    requested_mode = data.get("syncmode", "append")
    user_id = (data.get("user_id") or "").strip().lower()
    domain = (data.get("domain") or "mail").strip().lower()
    # 메일은 최신 메일이 위로 오는 "받은편지함" 순서를, 카카오는 대화를 처음부터 읽어내려가는
    # "대화 기록" 순서(오래된 게 위)를 기대하므로 도메인별로 정렬 방향을 다르게 함.
    sort_newest_first = domain != "messenger"

    paths = UserPaths(BASE_DIR, user_id, domain)

    if not str(content).strip():
        return jsonify({"ok": False, "error": "content가 비어있습니다."}), 400
    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    print("user_id =", user_id)

    # append인데 기존 인덱스가 없으면 rewrite로 전환
    fallback_to_rewrite = False
    sync_mode = requested_mode

    if requested_mode == "append" and not _index_ready(paths):
        print("[UPLOAD] index not ready -> fallback to rewrite")
        sync_mode = "rewrite"
        fallback_to_rewrite = True

    # 2) 저장 디렉토리 준비
    os.makedirs(paths.MAIL_DIR, exist_ok=True)

    if sync_mode == "rewrite":
        # rewrite: input 폴더 내 기존 메일 파일 전체 초기화
        # mail_latest.txt, mail_latest.csv, inc_*.txt 등 전부 삭제
        # 이전 데이터가 남아있으면 중복 체크에 걸려 새 메일이 스킵되는 버그 방지
        if os.path.exists(paths.MAIL_DIR):
            for fname in os.listdir(paths.MAIL_DIR):
                fpath = os.path.join(paths.MAIL_DIR, fname)
                try:
                    if os.path.isfile(fpath):  # 파일만 삭제, 폴더는 건너뜀
                        os.remove(fpath)
                except Exception as e:
                    print(f"[CLEAN] 파일 삭제 실패 (무시): {fpath} / {e}")

            print(f"[CLEAN] input 폴더 초기화 완료: {paths.MAIL_DIR}")
        if os.path.exists(paths.ATTACHMENT_DIR):
            shutil.rmtree(paths.ATTACHMENT_DIR)
            print(f"[CLEAN] attachment 폴더 초기화 완료: {paths.ATTACHMENT_DIR}")

        # [추가] 인덱스 준비 여부 판단 기준 파일 삭제 → 첨부파일 트리거가 인덱스 없음으로
        # 판단해 거절됨. rewrite 완료 전에 첨부파일이 먼저 처리되는 문제 방지.
        # _index_ready()가 보는 파일이 엔진마다 다르므로(GraphRAG: output/stats.json,
        # LightRAG: graph_chunk_entity_relation.graphml) RAG_ENGINE에 맞는 파일을 지운다.
        if RAG_ENGINE == "lightrag":
            ready_marker_path = os.path.join(paths.LIGHTRAG_ROOT, "graph_chunk_entity_relation.graphml")
        elif RAG_ENGINE == "graphrag":
            ready_marker_path = os.path.join(paths.GRAPHRAG_ROOT, "output", "stats.json")
        if os.path.exists(ready_marker_path):
            try:
                os.remove(ready_marker_path)
                print(f"[CLEAN] 인덱스 준비 마커 삭제 완료 (rewrite 시작): {ready_marker_path}")
            except Exception as e:
                print(f"[CLEAN] 인덱스 준비 마커 삭제 실패 (무시): {e}")

        try:
            from util.database.db_writer import get_latest_mail_account
            latest_account = get_latest_mail_account(user_id)
            if latest_account:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM processed_attachments WHERE user_mail_account_id = %s AND index_date = %s",
                    (latest_account["user_mail_account_id"], latest_account["index_date"])
                )
                conn.commit()
                cursor.close()
                conn.close()
            print(f"[CLEAN] processed_attachments DB 초기화 완료 (user_id={user_id})")
        except Exception as e:
            print(f"[CLEAN] processed_attachments DB 초기화 실패 (무시): {e}")

    # 3) 원본 메일 텍스트 저장 (append 모드만 — rewrite는 mail_latest.txt에 바로 씀)
    if sync_mode != "rewrite":
        file_path = os.path.join(paths.MAIL_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    extracted_count = 0
    failed_attachments = []
    valid_attachments = []

    # 4) 첨부파일 메타데이터 카운트. 실제 텍스트 추출/그래프 반영은 인덱싱 직전 _extract_and_merge_attachments가 처리한다.
    for file_info in attachments:
        f_name = file_info.get("name") or "attachment.bin"
        mail_id = str(file_info.get("mail_id") or "").strip()
        if f_name and mail_id:
            extracted_count += 1
            valid_attachments.append(file_info)

    # 5) 로그
    print(f"[UPLOAD] Received filename: {filename}")
    print(f"[UPLOAD] Content length: {len(content)}")
    print(f"[UPLOAD] Attachment count received: {len(attachments)}")
    print(f"[UPLOAD] Attachment extracted count: {extracted_count}")
    print(f"[UPLOAD] Requested mode: {requested_mode}")
    print(f"[UPLOAD] Actual mode: {sync_mode}")
    print("[UPLOAD] cwd:", os.getcwd())

    added_count  = 0
    skipped_count = 0
    saved_mail_path = ""

    # 메일 텍스트 누적 로직
    # rewrite: mail_latest.txt를 새로 씀 (기존 내용 무시)
    # append: 기존 mail_latest.txt를 읽어서 합친 후 재저장
    # 공통: mail_id 기반 중복 체크
    if sync_mode == "rewrite":
        existing_text = ""
        existing_ids  = set()
    else:
        existing_text = _read_latest_text(paths)
        existing_ids  = _extract_message_ids(existing_text)

    # 카카오는 블록 ID가 "그 날짜의 대화 전체"를 가리켜서(이메일처럼 발송 시점에 내용이 고정되는 게
    # 아니라 다음 내보내기 전까지 계속 자랄 수 있음), 기존에 저장된 가장 최근 날짜의 블록만 예외로
    # 취급한다 — 그 날짜의 새 블록이 오면 "이미 있음"으로 스킵하지 않고 최신 내용으로 덮어쓴다.
    # 그 외 과거 날짜는 이미 끝난 대화라 내용이 안 바뀌므로 지금처럼 ID 기준으로 정상 스킵한다.
    overwrite_ids = set()
    if domain == "messenger" and existing_ids:
        dated_ids = [i for i in existing_ids if re.match(r"^\d{4}-\d{2}-\d{2}", i)]
        if dated_ids:
            latest_date = max(i[:10] for i in dated_ids)
            overwrite_ids = {i for i in dated_ids if i.startswith(latest_date)}

    new_blocks    = _split_mail_blocks(content)
    append_blocks = []

    for block in new_blocks:
        msg_id = _extract_mail_id_from_block(block)
        if not msg_id:
            skipped_count += 1
            continue
        if msg_id in existing_ids and msg_id not in overwrite_ids:
            skipped_count += 1
            continue
        append_blocks.append(block.strip())
        existing_ids.add(msg_id)

    # overwrite_ids 중 실제로 새 블록이 들어온 것만 "교체 확정"으로 남긴다 — 최신 날짜가 이번 파일에
    # 아예 없는 예외적인 경우(부분 내보내기 등)까지 옛 블록을 지워버리면 데이터가 통째로 사라지므로,
    # 대체본이 실제로 도착했을 때만 옛 블록 제거를 진행한다.
    if overwrite_ids:
        replaced_ids = {_extract_mail_id_from_block(b) for b in append_blocks}
        overwrite_ids &= replaced_ids

    added_count = len(append_blocks)

    if sync_mode == "rewrite":
        _delete_incremental_files(paths)

    if append_blocks:
        append_blocks.sort(key=_extract_block_for_sort, reverse=sort_newest_first)
        inc_content = "\n\n".join(append_blocks).strip() + "\n"
        if sync_mode == "rewrite":
            with open(paths.MAIL_LATEST_PATH, "w", encoding="utf-8") as f:
                f.write(_renumber_mail_blocks(inc_content))
        else:
            # append: 기존 내용 앞에 새 메일 추가 후 mail_latest.txt 저장
            existing_lines = existing_text.splitlines()
            existing_clean = "\n".join(existing_lines).lstrip("\n")
            if overwrite_ids:
                # 덮어쓰기 대상(카카오 최신 날짜) 블록은 기존 내용에서 먼저 제거 — 안 그러면 새 버전과
                # 옛 버전이 둘 다 파일에 남아 중복된다.
                kept_blocks = [
                    b for b in _split_mail_blocks(existing_clean)
                    if _extract_mail_id_from_block(b) not in overwrite_ids
                ]
                existing_clean = "\n\n".join(b.strip() for b in kept_blocks).strip()
            updated_content = inc_content + "\n" + existing_clean
            with open(paths.MAIL_LATEST_PATH, "w", encoding="utf-8") as f:
                f.write(_renumber_mail_blocks(updated_content.strip()))

        saved_mail_path = paths.MAIL_LATEST_PATH

        # 새로 추가된 메일 ID 수집
        new_ids = set()
        for block in append_blocks:
            mid = _extract_mail_id_from_block(block)
            if mid:
                new_ids.add(mid)

        # statics 파이프라인 — 발신/수신 연락처 집계 등 이메일 전용 통계라 base 도메인에서만 실행.
        # 카카오는 sent_by/sent_to 같은 고정 관계 타입이 없어서 이 파이프라인이 의미 있는 결과를 못 냄.
        if domain == "mail":
            statics_job_id = str(uuid.uuid4())[:8]
            create_job(statics_job_id, job_type="statics")

            if sync_mode == "rewrite":
                final_text = _read_latest_text(paths)
                statics_blocks = _split_mail_blocks(final_text)
                statics_blocks = [b for b in statics_blocks if _extract_mail_id_from_block(b)]
            else:
                statics_blocks = append_blocks

            start_statics_pipeline_background(
                statics_job_id, paths,
                mode="rewrite" if sync_mode == "rewrite" else "append"
            )

    else:
        saved_mail_path = ""
        new_ids = set()

    print("[UPLOAD] added:", added_count)
    print("[UPLOAD] skipped:", skipped_count)
    if saved_mail_path:
        print("[UPLOAD] saved mail path:", os.path.abspath(saved_mail_path))

    # GraphRAG 파이프라인 실행
    graph_job_id = str(uuid.uuid4())[:8]

    if sync_mode == "rewrite":
        create_job(graph_job_id, job_type="index")
        update_job(graph_job_id, message="업로드 완료, 그래프 파이프라인 시작")
    else:
        create_job(graph_job_id, job_type="update")
        update_job(graph_job_id, message="업로드 완료, 그래프 업데이트 파이프라인 시작")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # 첨부파일은 CSV 빌드 전에 텍스트 추출/요약해서 mail_latest.txt에 미리 병합해둔다 —
    # 그래야 뒤이어 만드는 CSV/인덱싱에 첨부 내용까지 같이 반영된다 (순서 중요).
    if valid_attachments:
        _extract_and_merge_attachments(paths, valid_attachments, user_id)

    if sync_mode == "rewrite":
        update_dir = os.path.join(paths.GRAPHRAG_ROOT, "update_output")
        if os.path.exists(update_dir):
            shutil.rmtree(update_dir)
            print(f"[CLEAN] update_output 삭제 완료: {update_dir}")

        # _build_mail_csv는 동기 실행 후 GraphRAG 스레드 시작
        # CSV 파일이 완전히 쓰인 뒤 GraphRAG가 읽도록 순서 보장
        _build_mail_csv(paths)
        final_text = _read_latest_text(paths)
        total_mail_count = len([b for b in _split_mail_blocks(final_text) if _extract_mail_id_from_block(b)])
        print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 전체 인덱싱(rewrite) 시작 job_id={graph_job_id}")
        start_graph_pipeline_background(graph_job_id, paths, env, added_count=total_mail_count, max_mails=paths.MAX_MAILS, mail_platform=mail_platform)

    else:  # append
        if new_ids:
            # _build_mail_csv 반환값 None 체크 추가
            # new_ids 없을 때 None 반환하도록 수정했으므로 None이면 update 생략
            csv_path = _build_mail_csv(paths, mode="append", new_ids=new_ids)
            if csv_path:
                print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 증분 업데이트 시작 job_id={graph_job_id}")
                start_graph_update_pipeline_background(graph_job_id, paths, env)
            else:
                update_job(graph_job_id, status="done", message="CSV 없음, 업데이트 생략")
                print("[UPLOAD] CSV 생성 실패 → graphrag update 생략")
        else:
            # 증분 대상(new_ids)이 없다고 해서 무조건 건너뛰면 안 되는 경우가 있다:
            # 예를 들어 mail_latest.txt/인덱스는 그대로인데 MySQL만 초기화된 상황처럼,
            # "새로 추가할 메일은 없지만 실제로는 처음부터 다시 채워 넣어야 하는" 상태일 수
            # 있다. 이런 걸 사용자가 매번 수동으로 "전체 재인덱싱"을 눌러서 우회해야 했는데,
            # 여기서 자동으로 rewrite 파이프라인으로 전환한다 — mail_latest.txt는 이미
            # 최신/완전한 상태이므로 그걸 그대로 전체 인덱싱 입력으로 쓰면 된다.
            # (LightRAG의 ainsert()는 upsert라서 이미 인덱싱된 문서를 다시 넣어도 안전하다 —
            # job_run_lightrag.py의 build_lightrag_index 주석 참고.)
            print("[UPLOAD] new_ids 없음 → 증분할 새 메일 없음, 전체 재인덱싱으로 전환")
            update_job(graph_job_id, message="증분 대상 없음 → 전체 재인덱싱으로 전환")

            _build_mail_csv(paths)
            final_text = _read_latest_text(paths)
            total_mail_count = len([b for b in _split_mail_blocks(final_text) if _extract_mail_id_from_block(b)])
            print(f"[INDEX] RAG_ENGINE={RAG_ENGINE} 로 전체 인덱싱(rewrite, 증분 폴백) 시작 job_id={graph_job_id}")
            start_graph_pipeline_background(graph_job_id, paths, env, added_count=total_mail_count, max_mails=paths.MAX_MAILS, mail_platform=mail_platform)
            sync_mode = "rewrite"  # 응답 필드(actual_mode)에도 실제로 rewrite로 처리됐음을 반영
            fallback_to_rewrite = True  # index-not-ready 폴백과 같은 필드로 프론트에 "요청과 다르게 처리됨"을 알림

    return jsonify({
        "ok": True,
        "requested_mode": requested_mode,
        "job_id": graph_job_id,
        "actual_mode": sync_mode,
        "fallback_to_rewrite": fallback_to_rewrite,
        "latest_path": os.path.abspath(paths.MAIL_LATEST_PATH),
        "saved_mail_path": os.path.abspath(saved_mail_path) if saved_mail_path else "",
        "attachment_dir": os.path.abspath(paths.ATTACHMENT_DIR),
        "content_length": len(content),
        "added_count": added_count,
        "skipped_count": skipped_count,
        "attachment_received_count": len(attachments),
        "attachment_extracted_count": extracted_count,
        "failed_attachments": failed_attachments,
    })

# 엔드포인트: GET /graph-data
@app.route("/graph-data", methods=["GET", "OPTIONS"])
def graph_data():
    if request.method == "OPTIONS":
        return "", 200

    user_id = (request.args.get("user_id") or "").strip().lower()
    domain = (request.args.get("domain") or "mail").strip().lower()

    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    paths = UserPaths(BASE_DIR, user_id, domain)

    # 그래프 시각화 json 경로도 엔진별로 분리돼 있다(paths.GRAPH_JSON_PATH는 GraphRAG,
    # paths.LIGHTRAG_GRAPH_JSON_PATH는 LightRAG) — job_run_lightrag.py의 build_graph_json이
    # 인덱싱 직후 후자를 채운다.
    if RAG_ENGINE == "lightrag":
        graph_json_path = paths.LIGHTRAG_GRAPH_JSON_PATH
    elif RAG_ENGINE == "graphrag":
        graph_json_path = paths.GRAPH_JSON_PATH

    if not os.path.exists(graph_json_path):
        return jsonify({"nodes": [], "edges": [], "error": "graph json not found"}), 200

    try:
        with open(graph_json_path, "rb") as f:
            raw = f.read().rstrip(b'\x00')  # null 바이트 제거 (비정상 종료 방어)
        data = json.loads(raw.decode("utf-8"))
        print(f"[GRAPH-DATA] 반환: {len(data.get('nodes', []))} 노드")
        return jsonify(data)
    except Exception as e:
        print(f"[GRAPH-DATA] 에러: {e}")
        return jsonify({"nodes": [], "edges": [], "error": str(e)}), 500

# 엔드포인트: GET /graph-view
@app.route("/graph-view", methods=["GET"])
def graph_view():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "json"),
        "graph_view.html"
    )

# 공유 그래프 렌더링 함수
@app.route('/graph-render.js')
def graph_render_js():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "json"),
        "graph-render.js"
    )

# 엔드포인트: GET /index-status
@app.route("/index-status", methods=["GET"])
def index_status():
    user_id = (request.args.get("user_id") or "").strip().lower()
    if not user_id:
        return jsonify({"error": "user_id가 비어있습니다."}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"indexed": _index_ready(paths)})

# 엔드포인트: GET /init  — localStorage에 flask_url 자동 저장 후 대시보드로 이동
@app.route('/init')
def init_storage():
    from flask import request as _req
    origin = _req.host_url.rstrip('/')
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Initializing...</title></head>
<body>
<script>
  localStorage.setItem('gw_flask_url', {repr(origin)});
  window.location.replace('/dashboard/');
</script>
<p>설정 중... 자동으로 이동합니다.</p>
</body></html>""", 200, {{'Content-Type': 'text/html; charset=utf-8'}}

# 엔드포인트: GET /dashboard/
@app.route('/dashboard/', defaults={'path': 'production/index.html'})
@app.route('/dashboard/<path:path>')
def dashboard(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist')
    if not path.startswith('production/') and path.endswith('.html'):
        path = 'production/' + path
    return send_from_directory(dist_dir, path)

@app.route('/assets/<path:path>')
def static_assets(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'assets')
    return send_from_directory(dist_dir, path)

@app.route('/js/<path:path>')
def static_js(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'js')
    return send_from_directory(dist_dir, path)

@app.route('/fonts/<path:path>')
def static_fonts(path):
    dist_dir = os.path.join(os.path.dirname(__file__), 'web', 'dist', 'fonts')
    return send_from_directory(dist_dir, path)

# 웹앱용 통계 라우트
@app.route("/mail-stats", methods=["POST"])
def send_mail_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    print(f"[MAIL_STATS] user_id={user_id}")
    print(f"[MAIL_STATS] path={paths.USER_ROOT}")
    return jsonify({"user_id": user_id, "data": get_mail_stats(paths)})

@app.route("/mail-date-range", methods=["POST"])
def send_mail_date_range():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user_id": user_id, "data": get_mail_date_range(user_id)})

@app.route("/keyword-stats", methods=["POST"])
def send_keyword_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_keyword_stats(paths)})

@app.route("/keyword-by-person-date", methods=["POST"]) # 각 사람마다 주고받은 메일의 키위드 리턴
def keyword_by_person_date():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    person_user_id = data.get("person_user_id", "").strip()
    # 시간 범위 내에 있는 메일의 키워드들을 추출
    start_date = data.get("start_date", "").strip()
    end_date = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_user_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    try:
        keywords = get_keywords_by_person_date(user_id, person_user_id, start_date, end_date)
        return jsonify({"keywords": keywords})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rebuild-keyword-mail", methods=["POST"])
def rebuild_keyword_mail_route():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    try:
        rebuild_keyword_mail(paths)
        return jsonify({"ok": True, "message": "mail_keyword 테이블 재구성 완료"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload-photos", methods=["POST"])
def upload_contact_photos():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    photos   = data.get("photos", {})
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not isinstance(photos, dict) or not photos:
        return jsonify({"ok": True, "message": "사진 없음"}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    existing = {}
    if os.path.exists(paths.MAIL_PHOTOS_PATH):
        with open(paths.MAIL_PHOTOS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing.update({k.lower(): v for k, v in photos.items()})
    with open(paths.MAIL_PHOTOS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "saved": len(photos)})

@app.route("/contact-photos", methods=["POST"])
def get_contact_photos():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    if not os.path.exists(paths.MAIL_PHOTOS_PATH):
        return jsonify({}), 200
    with open(paths.MAIL_PHOTOS_PATH, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

@app.route("/person-avatars", methods=["POST"])
def get_person_avatars():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify(get_cached_person_avatars(paths))

@app.route("/generate-person-avatars", methods=["POST"])
def generate_person_avatars():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    people = data.get("people", [])
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    result = generate_person_avatars_batch(paths, people)
    return jsonify({"user_id": user_id, "data": result})

@app.route("/person-avatar-image/<user_id>/<filename>")
def person_avatar_image(user_id, filename):
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return send_from_directory(paths.AVATAR_IMAGES_DIR, filename)

@app.route("/self-avatar", methods=["POST"])
def get_self_avatar():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"url": get_cached_self_avatar(paths)})

@app.route("/generate-self-avatar", methods=["POST"])
def generate_self_avatar_route():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    name = data.get("name", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    url = generate_self_avatar(paths, name)
    return jsonify({"url": url})

@app.route("/high_affinity_person_stats", methods=["POST"])
def send_high_affinity_person_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_high_affinity_person_stats(paths)})

@app.route("/user_rating_stats", methods=["POST"])
def send_user_rating_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_user_rating_stats()})

@app.route("/mail_sync_stats", methods=["POST"])
def send_mail_sync_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id, "mail")
    return jsonify({"user_id": user_id, "data": get_mail_sync_stats(paths)})

@app.route("/mail-exchange-stats", methods=["POST"])
def send_mail_exchange_stats():
    data = request.json or {}
    user_id       = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"data": get_mail_exchange_stats(user_id, person_mail_id, start_date, end_date)})

_mail_message_cache_lock = threading.Lock()

def _load_mail_message_cache(paths):
    if not os.path.exists(paths.MAIL_MESSAGE_CACHE_PATH):
        return {}
    try:
        with open(paths.MAIL_MESSAGE_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

def _save_mail_message_cache(paths, cache):
    os.makedirs(paths.MAIL_STATICS_PATH, exist_ok=True)
    with open(paths.MAIL_MESSAGE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

@app.route("/mail-person-emails", methods=["POST"])
def send_person_emails_in_range():
    data = request.json or {}
    user_id       = data.get("user_id", "").strip()
    person_mail_id = data.get("person_user_id", "").strip()
    start_date     = data.get("start_date", "").strip()
    end_date       = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_mail_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    # 1) MySQL mail 테이블에서 이 기간에 오간 메일 ID 목록을 가져온다(GraphRAG 인덱싱
    #    캡과 무관하게 전체 동기화 이력을 담고 있어서, 통계 그래프 숫자와 실제 목록
    #    건수가 어긋나지 않는다).
    mail_refs = get_person_mail_ids_in_range(user_id, person_mail_id, start_date, end_date)

    # 2) 제목/본문은 MySQL에 없으므로(집계용 테이블), 메일 ID별로 파일 캐시에서만 조회한다.
    #    캐시에 없는 메일은 건너뛴다.
    paths = UserPaths(BASE_DIR, user_id, "mail")
    mail_cache = _load_mail_message_cache(paths)

    def _fetch_one(ref):
        cached = mail_cache.get(ref["id"])
        if cached:
            return {**cached, "id": ref["id"], "direction": ref["direction"], "date": ref["date"]}
        return None

    emails = []
    if mail_refs:
        with ThreadPoolExecutor(max_workers=min(len(mail_refs), 6)) as executor:
            futures = [executor.submit(_fetch_one, ref) for ref in mail_refs]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    emails.append(result)
    emails.sort(key=lambda e: e["date"])

    return jsonify({"data": emails})

@app.route("/mail-person-sent-stats", methods=["POST"])
def send_mail_person_sent_stats():
    data = request.json or {}
    user_id   = data.get("user_id", "").strip()
    start_date = data.get("start_date", "").strip()
    end_date   = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"user_id": user_id, "data": get_date_range_person_stats(user_id, start_date, end_date, "sent")})

@app.route("/mail-person-received-stats", methods=["POST"])
def send_mail_person_received_stats():
    data = request.json or {}
    user_id   = data.get("user_id", "").strip()
    start_date = data.get("start_date", "").strip()
    end_date   = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    return jsonify({"user_id": user_id, "data": get_date_range_person_stats(user_id, start_date, end_date, "received")})

@app.route("/intimacy", methods=["POST"])
def send_intimacy():
    data = request.json or {}
    user_id        = data.get("user_id", "").strip()
    person_user_id = data.get("person_user_id", "").strip()
    start_date      = data.get("start_date", "").strip()
    end_date        = data.get("end_date", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not person_user_id:
        return jsonify({"error": "person_user_id is required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    result = calculate_eis(
        user_mail_account_id=user_id,
        person_mail_account_id=person_user_id,
        start_date=start_date,
        end_date=end_date,
        apply_volume_correction=False,
        apply_time_decay=False,
    )
    return jsonify({
        "user_id":        user_id,
        "person_user_id": person_user_id,
        "start_date":      start_date,
        "end_date":        end_date,
        "data":            result,
    })

@app.route("/person-descriptions", methods=["POST"])
def send_person_descriptions():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    return jsonify({"user_id": user_id, "data": get_person_descriptions(user_id)})

@app.route("/mail-summaries", methods=["POST"])
def send_mail_summaries():
    data = request.json or {}
    user_id     = data.get("user_id", "").strip()
    summary_type = data.get("type", "").strip()

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if summary_type not in ("monthly", "yearly"):
        return jsonify({"error": "type must be 'monthly' or 'yearly'"}), 400

    paths = UserPaths(BASE_DIR, user_id, "mail")
    if not os.path.exists(paths.MAIL_SUMMARIES_PATH):
        return jsonify({"error": "summaries not generated yet"}), 404

    with open(paths.MAIL_SUMMARIES_PATH, "r", encoding="utf-8") as f:
        summaries = json.load(f)

    return jsonify({summary_type: summaries.get(summary_type, {})})

# 연락처 프록시
@app.route('/contacts-proxy', methods=['POST'])
def contacts_proxy():
    data = request.get_json() or {}
    action = data.get('action', '')
    user_id = (data.get('user_id') or '').strip().lower()

    if not user_id:
        return jsonify({'ok': False, 'error': 'user_id가 비어있습니다.'}), 400

    paths = UserPaths(BASE_DIR, user_id, "mail")

    if action == 'getFrequentContacts':
        max_results = int(data.get('maxResults', 100))
        try:
            if not os.path.exists(paths.MAIL_CONTACTS_PATH):
                return jsonify({'ok': True, 'contacts': []})
            with open(paths.MAIL_CONTACTS_PATH, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            result = []
            for email, info in stats.items():
                count = info.get('sent', 0) + info.get('received', 0)
                result.append({
                    'email': email,
                    'name': info.get('name', '') or email.split('@')[0],
                    'count': count,
                    'lastMailAt': None,
                })
            result.sort(key=lambda x: -x['count'])
            return jsonify({'ok': True, 'contacts': result[:max_results]})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    elif action == 'getMailHistory':
        email = (data.get('email') or '').strip()
        if not email:
            return jsonify({'ok': False, 'error': 'email이 비어있습니다.'}), 400
        try:
            if not os.path.exists(paths.MAIL_CONTACTS_PATH):
                return jsonify({'ok': True, 'sentCount': 0, 'receivedCount': 0})
            with open(paths.MAIL_CONTACTS_PATH, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            info = stats.get(email, {})
            return jsonify({
                'ok': True,
                'sentCount': info.get('sent', 0),
                'receivedCount': info.get('received', 0),
            })
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    return jsonify({'ok': False, 'error': f'unknown action: {action}'})

# 호스트/계정/비밀번호 받아서 로그인하여 실제 서버의 폴더 목록 반환
@app.route("/imap-list-folders", methods=["POST"])
def imap_list_folders():
    data = request.json or {}
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "").strip()
    password = data.get("password") or ""
    use_ssl = data.get("ssl", True)

    try:
        port = int(data.get("port") or 993)
    except (TypeError, ValueError):
        port = 993

    if not host:
        return jsonify({"ok": False, "error": "IMAP 호스트가 비어있습니다."}), 400
    if not user:
        return jsonify({"ok": False, "error": "이메일 주소가 비어있습니다."}), 400
    if not password:
        return jsonify({"ok": False, "error": "앱 비밀번호가 비어있습니다."}), 400

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
        conn.login(user, password)

        status, list_data = conn.list()
        if status != "OK":
            return jsonify({"ok": False, "error": "폴더 목록을 가져오지 못했습니다."}), 400

        folders = []
        for line in list_data or []:
            if not line:
                continue
            name = _imap_parse_list_line(line)
            if name and name not in folders:
                folders.append(name)

        return jsonify({"ok": True, "folders": folders})

    except imaplib.IMAP4.error as e:
        return jsonify({"ok": False, "error": f"IMAP 로그인/연결 오류: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"폴더 조회 중 오류: {e}"}), 500
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

# IMAP 호스트 → 실제 메일 플랫폼 이름 매핑 (mail_account.mail_platform에 저장)
_IMAP_HOST_PLATFORM_MAP = {
    "imap.gmail.com": "gmail",
    "imap.naver.com": "naver",
    "imap.daum.net": "daum",
    "imap.mail.me.com": "icloud",
    "outlook.office365.com": "outlook",
    "imap-mail.outlook.com": "outlook",
    "imap.mail.yahoo.com": "yahoo",
}

def _detect_imap_platform(host: str) -> str:
    host_lower = (host or "").strip().lower()
    if host_lower in _IMAP_HOST_PLATFORM_MAP:
        return _IMAP_HOST_PLATFORM_MAP[host_lower]
    # 매핑에 없는 커스텀 호스트는 도메인에서 서비스명을 추정 (예: imap.foo.co.kr -> foo)
    labels = [p for p in host_lower.split(".") if p not in ("imap", "mail", "www")]
    if len(labels) >= 2:
        return labels[-2]
    return host_lower or "imap"

# 메일 수집 요청
@app.route("/imap-collect", methods=["POST"])
def imap_collect():
    data = request.json or {}
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "").strip()
    password = data.get("password") or ""
    folders = data.get("folders") or []
    use_ssl = data.get("ssl", True)
    sync_mode = data.get("sync_mode") or "append"
    user_id = (data.get("user_id") or user or "").strip().lower()

    try:
        port = int(data.get("port") or 993)
    except (TypeError, ValueError):
        port = 993

    limit_raw = data.get("limit")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else 100
    except (TypeError, ValueError):
        limit = 100

    if not host:
        return jsonify({"ok": False, "error": "IMAP 호스트가 비어있습니다."}), 400
    if not user:
        return jsonify({"ok": False, "error": "이메일 주소가 비어있습니다."}), 400
    if not password:
        return jsonify({"ok": False, "error": "앱 비밀번호가 비어있습니다."}), 400
    if not folders:
        return jsonify({"ok": False, "error": "수집할 폴더가 비어있습니다."}), 400
    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="imap_collect")

    def _worker():
        print(f"[IMAP-COLLECT] host={host}:{port} ssl={use_ssl} user={user} folders={folders} limit={limit} mode={sync_mode}")
        update_job(job_id, status="running", message="IMAP 서버에서 메일 수집 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "IMAP 서버에서 메일 수집 중"})

        def _on_batch(folder, batch_num, total_batches, count):
            msg = f"{folder} 배치 {batch_num}/{total_batches} ({count}개)"
            update_job(job_id, message=msg)
            broadcast({"type": "progress", "job_id": job_id, "message": msg})

        fetch_started = time.perf_counter()
        try:
            content, attachments = _imap_fetch_content(
                host, port, use_ssl, user, password, folders, limit, user, on_batch=_on_batch
            )
        except imaplib.IMAP4.error as e:
            update_job(job_id, status="error", message="실패", error=f"IMAP 로그인/연결 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"IMAP 로그인/연결 오류: {e}"})
            return
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"IMAP 수집 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"IMAP 수집 중 오류: {e}"})
            return
        fetch_elapsed = time.perf_counter() - fetch_started
        print(f"[IMAP-COLLECT] 수집 완료: {fetch_elapsed:.2f}초 소요")

        if not content.strip():
            result = {"ok": True, "added_count": 0, "skipped_count": 0, "message": "수집된 메일이 없습니다."}
            update_job(job_id, status="done", message="완료", result=result)
            broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": result})
            return

        filename = f"imap_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
        update_job(job_id, message="수집한 메일 저장/인덱싱 준비 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "수집한 메일 저장/인덱싱 준비 중"})
        mail_platform = _detect_imap_platform(host)

        try:
            with app.test_request_context(
                "/upload", method="POST",
                json={
                    "filename": filename,
                    "content": content,
                    "attachment": attachments,
                    "syncmode": sync_mode,
                    "user_id": user_id,
                    "mail_platform": mail_platform,
                },
                content_type="application/json",
            ):
                result = upload()
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"업로드 처리 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"업로드 처리 중 오류: {e}"})
            return

        body, status_code = result if isinstance(result, tuple) else (result, 200)
        try:
            body_data = body.get_json()
        except Exception:
            body_data = None

        if status_code >= 400 or not body_data:
            error_msg = (body_data or {}).get("error", "업로드 처리 실패")
            update_job(job_id, status="error", message="실패", error=error_msg)
            broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
            return

        update_job(job_id, status="done", message="완료", result=body_data)
        broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": body_data})

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "jobId": job_id})

@app.route('/imap-collect-status/<job_id>', methods=['GET'])
def imap_collect_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    return jsonify({
        "status": job["status"],
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })

# 엔드포인트: POST /message-upload — 카카오톡 대화 내보내기(.txt)를 파싱해서 "message" 도메인으로 업로드/인덱싱.
# /imap-collect와 동일한 패턴: 백그라운드 스레드에서 처리 후 내부적으로 /upload를 호출해 저장/인덱싱을 위임함.
@app.route("/message-upload", methods=["POST"])
def message_upload():
    data = request.json or {}
    raw_text = data.get("content") or ""
    room_name_input = (data.get("room_name") or "").strip()
    sync_mode = data.get("sync_mode") or "append"
    filename_hint = (data.get("filename") or "").strip()

    if not raw_text.strip():
        return jsonify({"ok": False, "error": "대화 내용이 비어있습니다."}), 400

    room_name = room_name_input or guess_room_name(raw_text, filename_hint or "카카오톡 대화")
    room_id = build_room_id(room_name)

    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="message_upload")

    def _worker():
        update_job(job_id, status="running", message="카카오톡 대화 파싱 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "카카오톡 대화 파싱 중"})

        try:
            messages = parse_message_export(raw_text)
            blocks = build_message_blocks(messages, room_name)
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"파싱 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"파싱 중 오류: {e}"})
            return

        if not blocks:
            result = {"ok": True, "added_count": 0, "skipped_count": 0, "message": "파싱된 대화가 없습니다.", "room_id": room_id}
            update_job(job_id, status="done", message="완료", result=result)
            broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": result})
            return

        content = "\n\n".join(blocks).strip() + "\n"
        filename = f"message_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"

        update_job(job_id, message="파싱한 대화 저장/인덱싱 준비 중")
        broadcast({"type": "progress", "job_id": job_id, "message": "파싱한 대화 저장/인덱싱 준비 중"})

        try:
            with app.test_request_context(
                "/upload", method="POST",
                json={
                    "filename": filename,
                    "content": content,
                    "attachment": [],
                    "syncmode": sync_mode,
                    "user_id": room_id,
                    "mail_platform": "message",
                    "domain": "messenger",
                },
                content_type="application/json",
            ):
                result = upload()
        except Exception as e:
            traceback.print_exc()
            update_job(job_id, status="error", message="실패", error=f"업로드 처리 중 오류: {e}")
            broadcast({"type": "failed", "job_id": job_id, "message": f"업로드 처리 중 오류: {e}"})
            return

        body, status_code = result if isinstance(result, tuple) else (result, 200)
        try:
            body_data = body.get_json()
        except Exception:
            body_data = None

        if status_code >= 400 or not body_data:
            error_msg = (body_data or {}).get("error", "업로드 처리 실패")
            update_job(job_id, status="error", message="실패", error=error_msg)
            broadcast({"type": "failed", "job_id": job_id, "message": error_msg})
            return

        body_data["room_id"] = room_id
        body_data["room_name"] = room_name
        update_job(job_id, status="done", message="완료", result=body_data)
        broadcast({"type": "done", "job_id": job_id, "message": "완료", "result": body_data})

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "jobId": job_id, "room_id": room_id, "room_name": room_name})

@app.route('/message-upload-status/<job_id>', methods=['GET'])
def message_upload_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404

    return jsonify({
        "status": job["status"],
        "message": job.get("message", ""),
        "result": job.get("result"),
        "error": job.get("error"),
    })

# 지금까지 인덱싱된 유저(또는 카카오 대화방, ?domain=message) 반환
@app.route("/accounts", methods=["GET"])
def accounts_route():
    domain = (request.args.get("domain") or "mail").strip().lower()
    return jsonify({"accounts": list_accounts(BASE_DIR, domain)})

# 정적 파일을 vite 빌드 없이 소스에서 직접 서빙하는 라우트. 브라우저가 들어오면 flask+url을 localStorage에 저장 및 홈화면으로 리다이렉트
@app.route('/imap-start')
def imap_start():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'web', 'production'),
        'imap-start.html'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)