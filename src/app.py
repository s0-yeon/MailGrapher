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
from util.date_query import run_date_range_query
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
from util.jobs.job_run import (
    start_graph_pipeline_background,
    start_graph_update_pipeline_background
)
from config.settings import *
from util.user_path import UserPaths
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
    _sanitize_filename,
    _delete_old_update_files
)
from util.attachment_manager import _run_attachment_pipeline
from util.database.db_writer import (
    save_query_to_db,
    init_processed_attachments_table,
    init_keyword_mail_table,
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
    unsubscribe
)
from config.db import get_db_connection
from util.graphrag import (
    _run_graphrag,
    _is_index_ready
)
from util.graphrag_query import _classify_query_method
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
# 환경변수 로드
load_dotenv("src/parquet/.env")

# Flask 앱 초기화
app = Flask(__name__)
CORS(app)

# 서버 시작 시 테이블 초기화 실행
init_processed_attachments_table()
init_keyword_mail_table()

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
        from util.graphrag_query import run_graphrag_query
        try:
            paths = UserPaths(BASE_DIR, user_id)
            env = os.environ.copy()
            env["USER_ID"] = user_id

            # 날짜 범위 쿼리일 시 parquet 직접 필터링해서 LLM에게 넘기기, 아니면 GraphRAG로 처리
            answer = run_date_range_query(message, paths) # 이게 None이면 GraphRAG로 
            source_ids = []  # 초기화
            if answer is None:
                full_message = message + " 영어 말고 한국어로 답변해줘."

                resMethod = _classify_query_method(message)
                try: # 엔진 객체 직접 호출 방식
                    answer, source_ids = run_graphrag_query(full_message,message, paths, method=resMethod)
                except Exception as e:
                    # API 방식 실패 시 기존 CLI 방식으로 자동 fallback
                    print(f"[ENGINE] API 실패, CLI fallback: {e}")
                    answer = _run_graphrag(full_message,message, resMethod, paths, resType)
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

    paths = UserPaths(BASE_DIR, user_id)
    message += " 영어 말고 한국어로 답변해줘."

    try:
        answer = _run_graphrag(message, resMethod, paths, resType)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'result': answer})

# 엔드포인트: POST /upload
# 배치 시스템 지원
# is_last 플래그 수신: 마지막 배치일 때만 GraphRAG 파이프라인 실행
# 중간 배치: mail_latest.txt에 누적만 하고 GraphRAG 실행 안 함
# mail_id 기반 중복 블록 체크: rewrite/append 관계없이 항상 적용
@app.route("/upload", methods=["POST"])
def upload():
    # 1) 데이터 수신
    data = request.json or {}
    filename = data.get("filename") or f"mail_{int(time.time())}.txt"
    content = data.get("content") or ""
    attachments = data.get("attachment") or []
    requested_mode = data.get("syncmode", "append")
    user_id = (data.get("user_id") or "").strip().lower()
    is_last = data.get("is_last", True)
    batch_offset = data.get("batch_offset", 0)

    paths = UserPaths(BASE_DIR, user_id)

    if not str(content).strip():
        return jsonify({"ok": False, "error": "content가 비어있습니다."}), 400
    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    print("user gmail id =", user_id)
    print(f"[UPLOAD] is_last={is_last}, batch_offset={batch_offset}")

    # append인데 기존 인덱스가 없으면 rewrite로 전환
    fallback_to_rewrite = False
    sync_mode = requested_mode

    if requested_mode == "append" and not _is_index_ready(paths):
        print("[UPLOAD] index not ready -> fallback to rewrite")
        sync_mode = "rewrite"
        fallback_to_rewrite = True

    # 2) 저장 디렉토리 준비
    os.makedirs(paths.MAIL_DIR, exist_ok=True)

    # rewrite 첫 배치(offset=0)에서만 기존 첨부파일 폴더 초기화
    # batch_offset=0(첫 배치)일 때만 삭제
    if sync_mode == "rewrite" and batch_offset == 0:
        # rewrite 첫 배치: input 폴더 내 기존 메일 파일 전체 초기화
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

            print(f"[CLEAN] input 폴더 초기화 완료 (첫 배치): {paths.MAIL_DIR}")
        if os.path.exists(paths.ATTACHMENT_DIR):
            shutil.rmtree(paths.ATTACHMENT_DIR)
            print(f"[CLEAN] attachment 폴더 초기화 완료 (첫 배치): {paths.ATTACHMENT_DIR}")

        # [추가] stats.json 삭제 → 첨부파일 트리거가 인덱스 없음으로 판단해 거절됨
        # rewrite 완료 전에 첨부파일이 먼저 처리되는 문제 방지
        stats_path = os.path.join(paths.GRAPHRAG_ROOT, "output", "stats.json")
        if os.path.exists(stats_path):
            try:
                os.remove(stats_path)
                print(f"[CLEAN] stats.json 삭제 완료 (rewrite 시작)")
            except Exception as e:
                print(f"[CLEAN] stats.json 삭제 실패 (무시): {e}")

        try:
            from util.database.db_writer import get_latest_user_record
            latest_user = get_latest_user_record(user_id)
            if latest_user:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM processed_attachments WHERE user_account_id = %s AND update_date = %s",
                    (latest_user["user_account_id"], latest_user["update_date"])
                )
                conn.commit()
                cursor.close()
                conn.close()
            print(f"[CLEAN] processed_attachments DB 초기화 완료 (user_id={user_id})")
        except Exception as e:
            print(f"[CLEAN] processed_attachments DB 초기화 실패 (무시): {e}")

    # 3) 원본 메일 텍스트 저장
    # rewrite 중간 배치는 "mail_latest.txt"에 "a" 모드로 이어붙임
    # 첫 배치(batch_offset=0)일 때만 파일을 비우고 시작
    # append 모드는 기존 방식 유지 (inc_*.txt로 별도 저장)
    if sync_mode != "rewrite":  # rewrite는 여기서 파일 안 씀
        file_path = os.path.join(paths.MAIL_DIR, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    extracted_count = 0
    failed_attachments = []

    # 4) 첨부파일 메타데이터 카운트 (원본은 트리거가 별도 전송)
    for file_info in attachments:
        f_name = file_info.get("name") or "attachment.bin"
        mail_id = str(file_info.get("mail_id") or "").strip()
        if f_name and mail_id:
            extracted_count += 1

    # 5) 로그
    print(f"[UPLOAD] Received filename: {filename}")
    print(f"[UPLOAD] Content length: {len(content)}")
    print(f"[UPLOAD] Attachment count received: {len(attachments)}")
    print(f"[UPLOAD] Attachment extracted count: {extracted_count}")
    print(f"[UPLOAD] Requested mode: {requested_mode}")
    print(f"[UPLOAD] Actual mode: {sync_mode}")
    print(f"[UPLOAD] is_last: {is_last}")
    print("[UPLOAD] cwd:", os.getcwd())

    added_count  = 0
    skipped_count = 0
    saved_mail_path = ""

    # 메일 텍스트 누적 로직
    # rewrite: 파일에 직접 이어붙이므로 중복 체크만 수행 (mail_latest.txt 재작성 불필요)
    # append: 기존 방식 유지 (existing_text 읽어서 합친 후 mail_latest.txt 저장)
    # 공통: mail_id 기반 중복 체크 → 배치 재시도 시 중복 삽입 방지
    # 기존 mail_latest.txt에서 이미 저장된 mail_id 추출 (중복 방지용)
    # rewrite 첫 배치: 파일을 새로 쓰는 시점이므로 기존 내용 무시
    # 기존 파일의 mail_id를 읽으면 전부 중복으로 판단해서 스킵되는 버그 방지
    if sync_mode == "rewrite" and batch_offset == 0:
        existing_text = ""
        existing_ids  = set()
    else:
        existing_text = _read_latest_text(paths)
        existing_ids  = _extract_message_ids(existing_text)

    new_blocks    = _split_mail_blocks(content)
    append_blocks = []

    for block in new_blocks:
        msg_id = _extract_mail_id_from_block(block)
        if not msg_id:
            skipped_count += 1
            continue
        if msg_id in existing_ids:
            skipped_count += 1
            continue
        append_blocks.append(block.strip())
        existing_ids.add(msg_id)

    added_count = len(append_blocks)

    # rewrite 첫 배치: 증분 파일 초기화
    if sync_mode == "rewrite" and batch_offset == 0:
        _delete_incremental_files(paths)

    if batch_offset == 0:  # rewrite/append 공통으로 밖으로 꺼냄
        batch_job_id = "batch_" + user_id
        create_job(batch_job_id, job_type="batch")
        update_job(batch_job_id, status="running", message="배치 진행 중")
        print(f"[UPLOAD] 배치 시작 job 생성: {batch_job_id}")

    if append_blocks:
        append_blocks.sort(key=_extract_block_for_sort, reverse=True)
        inc_content = "\n\n".join(append_blocks).strip() + "\n"
        # 파일에 직접 이어붙이는 방식
        # _renumber_mail_blocks 적용해서 최종 정리
        # 마지막 배치일 때만 번호 재정렬 (중간 배치는 불완전한 상태)
        if sync_mode == "rewrite":
            with open(paths.MAIL_LATEST_PATH, "a", encoding="utf-8") as f:
                f.write(inc_content)  # 정제된 블록만 이어붙임
            if is_last:
                final_text = _read_latest_text(paths)
                all_blocks = _split_mail_blocks(final_text)
                all_blocks.sort(key=_extract_block_for_sort, reverse=True)  # 날짜 정렬
                sorted_text = "\n\n".join(b.strip() for b in all_blocks).strip() + "\n"
                with open(paths.MAIL_LATEST_PATH, "w", encoding="utf-8") as f:
                    f.write(_renumber_mail_blocks(sorted_text))
        else:
            # append: 기존 내용 앞에 새 메일 추가 후 mail_latest.txt 저장
            existing_lines = existing_text.splitlines()
            existing_clean = "\n".join(existing_lines).lstrip("\n")
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

        # statics 파이프라인
        statics_job_id = str(uuid.uuid4())[:8]
        create_job(statics_job_id, job_type="statics")
        
        if is_last and sync_mode == "rewrite":
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

    # GraphRAG 파이프라인 실행 조건
    # is_last=True 일 때만 실행
    # 중간 배치(is_last=False): mail_latest.txt 누적만, GraphRAG 실행 안 함
    # 마지막 배치(is_last=True): 전체 누적 텍스트로 GraphRAG 실행
    # 배치 시스템 없는 기존 단일 호출: is_last 기본값 True → 기존 동작 유지
    graph_job_id = str(uuid.uuid4())[:8]

    if not is_last:
        # 중간 배치: GraphRAG 실행 안 함, 누적만
        print(f"[UPLOAD] 중간 배치 (is_last=False) → GraphRAG 실행 생략, 누적 중")
        return jsonify({
            "ok": True,
            "requested_mode": requested_mode,
            "actual_mode": sync_mode,
            "is_last": is_last,
            "fallback_to_rewrite": fallback_to_rewrite,
            "added_count": added_count,
            "skipped_count": skipped_count,
            "attachment_received_count": len(attachments),
            "attachment_extracted_count": extracted_count,
        })

    # 마지막 배치: GraphRAG 파이프라인 실행
    batch_job_id = "batch_" + user_id
    update_job(batch_job_id, status="done", message="배치 완료")
    print(f"[UPLOAD] 배치 완료 job 닫기: {batch_job_id}")

    # 마지막 배치: GraphRAG 파이프라인 실행
    if sync_mode == "rewrite":
        create_job(graph_job_id, job_type="index")
        update_job(graph_job_id, message="업로드 완료, 그래프 파이프라인 시작")
    else:
        create_job(graph_job_id, job_type="update")
        update_job(graph_job_id, message="업로드 완료, 그래프 업데이트 파이프라인 시작")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if sync_mode == "rewrite":
        update_dir = os.path.join(paths.GRAPHRAG_ROOT, "update_output")
        if os.path.exists(update_dir):
            shutil.rmtree(update_dir)
            print(f"[CLEAN] update_output 삭제 완료: {update_dir}")

        # _build_mail_csv는 동기 실행 후 GraphRAG 스레드 시작
        # CSV 파일이 완전히 쓰인 뒤 GraphRAG가 읽도록 순서 보장
        _build_mail_csv(paths)
        # rewrite 배치 완료 시 총 누적 메일 수로 기록 (마지막 배치 added_count만 넘기면 일부만 저장되는 버그 방지)
        final_text = _read_latest_text(paths)
        total_mail_count = len([b for b in _split_mail_blocks(final_text) if _extract_mail_id_from_block(b)])
        start_graph_pipeline_background(graph_job_id, paths, env, added_count=total_mail_count, max_mails=paths.MAX_MAILS)

    else:  # append
        if new_ids:
            # _build_mail_csv 반환값 None 체크 추가
            # new_ids 없을 때 None 반환하도록 수정했으므로 None이면 update 생략
            csv_path = _build_mail_csv(paths, mode="append", new_ids=new_ids)
            if csv_path:
                start_graph_update_pipeline_background(graph_job_id, paths, env)
            else:
                update_job(graph_job_id, status="done", message="CSV 없음, 업데이트 생략")
                print("[UPLOAD] CSV 생성 실패 → graphrag update 생략")
        else:
            update_job(graph_job_id, status="done", message="추가된 새 메일 없음, 업데이트 생략")
            print("[UPLOAD] new_ids 없음 → graphrag update 생략")

    return jsonify({
        "ok": True,
        "requested_mode": requested_mode,
        "job_id": graph_job_id,
        "actual_mode": sync_mode,
        "fallback_to_rewrite": fallback_to_rewrite,
        "is_last": is_last,
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

    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400

    paths = UserPaths(BASE_DIR, user_id)

    if not os.path.exists(paths.GRAPH_JSON_PATH):
        return jsonify({"nodes": [], "edges": [], "error": "graph json not found"}), 200

    try:
        with open(paths.GRAPH_JSON_PATH, "rb") as f:
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
    paths = UserPaths(BASE_DIR, user_id)
    return jsonify({"indexed": _is_index_ready(paths)})

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

# 엔드포인트: POST /upload-attachments
# 중복 처리 방지 로직 추가
# 기존: 10분마다 전체 첨부파일을 무조건 처리
# 변경: DB 조회로 이미 처리된 (user_id, mail_id, filename) 조합 필터링 후 처리
# 처리 완료 후 DB에 기록 → 다음 트리거에서 중복 처리 방지
@app.route("/upload-attachments", methods=["POST"])
def upload_attachments():
    # 1) 데이터 수신
    data = request.json or {}
    user_id = (data.get("user_id") or "").strip().lower()
    attachments = data.get("attachments") or []

    if not user_id:
        return jsonify({"ok": False, "error": "user_id가 비어있습니다."}), 400
    
    if not attachments:
        # attachments 없이 is_last=true만 온 경우 → GraphRAG update 트리거
        is_last = data.get("is_last", False)
        if is_last:
            # 이미 누적된 attachment_latest.csv로 GraphRAG update 실행
            paths = UserPaths(BASE_DIR, user_id)
            if os.path.exists(os.path.join(paths.MAIL_DIR, "attachment_latest.csv")):
                job_id = str(uuid.uuid4())[:8]
                create_job(job_id, job_type="attachment")
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                from util.jobs.job_run import build_graphrag_update, build_graph_json
                def _finish():
                    build_graphrag_update(job_id, paths, env)
                    build_graph_json(job_id, paths, env)
                    _delete_old_update_files(paths)
                    update_job(job_id, status="done", message="첨부파일 인덱싱 완료")
                    print(f"[JOB][attachment] SUCCESS job_id={job_id}")
                threading.Thread(target=_finish, daemon=True).start()
                return jsonify({"ok": True, "message": "finish signal received"})
        return jsonify({"ok": False, "error": "attachments가 비어있습니다."}), 400
    
    paths = UserPaths(BASE_DIR, user_id)

    # 2) 메일 인덱스가 준비되지 않았으면 거절
    # 메일 본문 인덱싱 완료 전에 첨부파일 처리하면 불완전한 그래프에 update가 붙는 문제 방지
    # 10분 트리거가 다음번에 재시도함
    if not _is_index_ready(paths):
        print(f"[upload-attachments] 메일 인덱스 미준비 → 요청 거절, 다음 트리거에서 재시도")
        return jsonify({"ok": False, "error": "메일 인덱스 미준비, 다음 트리거에서 재시도됩니다."}), 409

    # 3) 인덱싱/업데이트 중이면 거절 (graphrag 동시 실행 방지)
    running_jobs = [j for j in get_all_jobs().values()
                if j.get("status") == "running"
                and j.get("job_type") in ("index", "update", "batch")]
    
    if running_jobs:
        print(f"[upload-attachments] 인덱싱 진행 중 → 요청 거절, 다음 트리거에서 재시도")
        return jsonify({"ok": False, "error": "인덱싱 진행 중, 다음 트리거에서 재시도됩니다."}), 409

    # 4) 이미 처리된 첨부파일 필터링
    is_last = data.get("is_last", True)
    unprocessed = filter_unprocessed_attachments(user_id, attachments)

    if not unprocessed:
        print(f"[upload-attachments] 모두 이미 처리된 첨부파일 → 스킵")
        if is_last and os.path.exists(os.path.join(paths.MAIL_DIR, "attachment_latest.csv")):
            job_id = str(uuid.uuid4())[:8]
            create_job(job_id, job_type="attachment")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            from util.jobs.job_run import build_graphrag_update, build_graph_json
            def _finish():
                build_graphrag_update(job_id, paths, env)
                build_graph_json(job_id, paths, env)
                _delete_old_update_files(paths)
                update_job(job_id, status="done", message="첨부파일 인덱싱 완료")
                print(f"[JOB][attachment] SUCCESS job_id={job_id}")
            threading.Thread(target=_finish, daemon=True).start()
            return jsonify({"ok": True, "message": "모두 처리됨, finish 실행"})
        return jsonify({"ok": True, "skipped": len(attachments), "message": "모두 이미 처리된 첨부파일"})

    # 5) 즉시 200 응답 (Apps Script 타임아웃 방지)
    job_id = str(uuid.uuid4())[:8]
    create_job(job_id, job_type="attachment")
    update_job(job_id, message="첨부파일 수신 완료, 백그라운드 처리 시작")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    # 6) 백그라운드에서 처리 (미처리 첨부파일만 전달)
    t = threading.Thread(
        target=_run_attachment_pipeline,
        args=(job_id, paths, unprocessed, env, is_last),
        daemon=True
    )
    t.start()

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "attachment_count": len(unprocessed),
        "skipped_count": len(attachments) - len(unprocessed),
    })

# 웹앱용 통계 라우트
@app.route("/mail-stats", methods=["POST"])
def send_mail_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
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
    paths = UserPaths(BASE_DIR, user_id)
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
    paths = UserPaths(BASE_DIR, user_id)
    try:
        rebuild_keyword_mail(paths)
        return jsonify({"ok": True, "message": "keyword_mail 테이블 재구성 완료"})
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
    paths = UserPaths(BASE_DIR, user_id)
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
    paths = UserPaths(BASE_DIR, user_id)
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
    paths = UserPaths(BASE_DIR, user_id)
    return jsonify(get_cached_person_avatars(paths))

@app.route("/generate-person-avatars", methods=["POST"])
def generate_person_avatars():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    people = data.get("people", [])
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
    result = generate_person_avatars_batch(paths, people)
    return jsonify({"user_id": user_id, "data": result})

@app.route("/person-avatar-image/<user_id>/<filename>")
def person_avatar_image(user_id, filename):
    paths = UserPaths(BASE_DIR, user_id)
    return send_from_directory(paths.AVATAR_IMAGES_DIR, filename)

@app.route("/self-avatar", methods=["POST"])
def get_self_avatar():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({}), 200
    paths = UserPaths(BASE_DIR, user_id)
    return jsonify({"url": get_cached_self_avatar(paths)})

@app.route("/generate-self-avatar", methods=["POST"])
def generate_self_avatar_route():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    name = data.get("name", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
    url = generate_self_avatar(paths, name)
    return jsonify({"url": url})

@app.route("/high_affinity_person_stats", methods=["POST"])
def send_high_affinity_person_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
    return jsonify({"user_id": user_id, "data": get_high_affinity_person_stats(paths)})

@app.route("/user_rating_stats", methods=["POST"])
def send_user_rating_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
    return jsonify({"user_id": user_id, "data": get_user_rating_stats()})

@app.route("/mail_sync_stats", methods=["POST"])
def send_mail_sync_stats():
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    paths = UserPaths(BASE_DIR, user_id)
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
    paths = UserPaths(BASE_DIR, user_id)
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
        user_account_id=user_id,
        person_account_id=person_user_id,
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

    paths = UserPaths(BASE_DIR, user_id)
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

    paths = UserPaths(BASE_DIR, user_id)

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
    # limit=0은 "전체 수집"을 의미하므로 `or` 단락 평가로 100에 덮어써지지 않도록 None만 걸러낸다
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

    print(f"[IMAP-COLLECT] host={host}:{port} ssl={use_ssl} user={user} folders={folders} limit={limit} mode={sync_mode}")

    try:
        content, attachments = _imap_fetch_content(host, port, use_ssl, user, password, folders, limit, user)
    except imaplib.IMAP4.error as e:
        return jsonify({"ok": False, "error": f"IMAP 로그인/연결 오류: {e}"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"IMAP 수집 중 오류: {e}"}), 500

    if not content.strip():
        return jsonify({"ok": True, "added_count": 0, "skipped_count": 0, "message": "수집된 메일이 없습니다."})

    filename = f"imap_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"

    # 변환된 텍스트/첨부파일을 기존 /upload 엔드포인트 로직에 그대로 위임 (label-route와 동일한 패턴)
    with app.test_request_context(
        "/upload", method="POST",
        json={
            "filename": filename,
            "content": content,
            "attachment": attachments,
            "syncmode": sync_mode,
            "user_id": user_id,
            "is_last": True,
            "batch_offset": 0,
        },
        content_type="application/json",
    ):
        result = upload()

    if isinstance(result, tuple):
        body, status_code = result[0], result[1]
    else:
        body, status_code = result, 200

    return body, status_code

# 지금까지 인덱싱된 유저 반환
@app.route("/accounts", methods=["GET"])
def list_accounts():
    user_data_dir = os.path.join(BASE_DIR, "user_data")
    accounts = []

    if os.path.isdir(user_data_dir):
        for dir_name in sorted(os.listdir(user_data_dir)):
            dir_path = os.path.join(user_data_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue

            meta_path = os.path.join(dir_path, "account.json")
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
                # (진짜 user_id는 다른 엔드포인트가 실제 값으로 호출되는 순간
                #  UserPaths가 자동으로 account.json을 채워넣는다.)
                user_id = dir_name.replace("_at_", "@", 1).replace("_", ".")

            paths = UserPaths(BASE_DIR, user_id)
            accounts.append({
                "user_id": user_id,
                "indexed": _is_index_ready(paths),
            })

    return jsonify({"accounts": accounts})

# 정적 파일을 vite 빌드 없이 소스에서 직접 서빙하는 라우트. 브라우저가 들어오면 flask+url을 localStorage에 저장 및 홈화면으로 리다이렉트
@app.route('/imap-start')
def imap_start():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), 'web', 'production'),
        'imap-start.html'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)