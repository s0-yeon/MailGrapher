import os
import time 
import traceback
import re
import subprocess

from util.jobs.job_store import update_job
from util.jobs.job_run import build_graph_json,build_graphrag_index,build_graphrag_update
from util.database.db_writer import save_query_to_db
from util.file_manager import _read_json_file

# GraphRAG CLI 실행
def _run_graphrag(message, resMethod, raw_message, paths, resType):

    def decode_output(b: bytes) -> str:
        if not b:
            return ""
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                pass
        return b.decode("utf-8", errors="replace")

    python_command = [
        'graphrag', 'query',
        '--root', paths.GRAPHRAG_ROOT,
        '--response-type', resType,
        '--method', resMethod,
        '--query', message
    ]

    start_time = time.time()

    result = subprocess.run(
        python_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
        text=False
    )
    elapsed = time.time() - start_time
    print(f'execution_time : {elapsed}')
    try:
        save_query_to_db(paths.GMAIL_ID, raw_message, elapsed, resMethod)
    except Exception as e:
        print(f"[WARN] query DB 저장 실패 (무시): {e}")

    stdout_text = decode_output(result.stdout)
    stderr_text = decode_output(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(stderr_text or stdout_text or 'GraphRAG 실행 오류')

    print(stdout_text)

    match = re.search(r'SUCCESS: (?:Local|Global) Search Response:\s*(.*)', stdout_text, re.DOTALL)
    answer = match.group(1).strip() if match else stdout_text.strip()

    answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', answer)
    answer = re.sub(r'\*+|#+', '', answer)
    answer = answer.strip()
    print(answer)
    return answer.strip()

# 메일데이터 그래프 데이터 JSON, GraphRAG 인덱싱을 수행하는 파이프라인 
def run_graph_pipeline(job_id):
    print(f"[PIPELINE] start job_id={job_id}")

    try:
        # 작업 상태를 running으로 변경
        update_job(job_id, status="running", progress=1, message="그래프 파이프라인 시작")
        print(f"[PIPELINE] job updated to running job_id={job_id}")

        env = os.environ.copy() # 현재 프로세스의 환경변수를 복사
        env["PYTHONUTF8"] = "1" # Python이 UTF-8 모드로 동작하도록 설정, 한글/특수문자 깨짐 방지 목적
        env["PYTHONIOENCODING"] = "utf-8" # 표준입출력 인코딩을 utf-8로 강제
        env["RICH_DISABLE"] = "1" # rich 라이브러리의 컬러/장식 출력 비활성화, 로그 파일이나 콘솔에서 ANSI escape 문자 깨짐 방지

        print(f"[PIPELINE][INDEX] env prepared job_id={job_id}")
        print(f"[PIPELINE][INDEX] cwd={os.getcwd()} job_id={job_id}")

        # GraphRAG 전체 인덱싱 시작
        print(f"[PIPELINE][INDEX] calling build_graphrag_index job_id={job_id}")
        build_graphrag_index(job_id, env)
        print(f"[PIPELINE][INDEX] build_graphrag_index DONE job_id={job_id}")

        # 인덱싱이 끝난 후 그래프 시각화용 JSON 생성
        print(f"[PIPELINE][INDEX] calling build_graph_json job_id={job_id}")
        build_graph_json(job_id, env)
        print(f"[PIPELINE][INDEX] build_graph_json DONE job_id={job_id}")

        # 모든 작업이 성공적으로 끝났으면 상태를 done으로 변경
        update_job(
            job_id,
            status="done",
            progress=100,
            message="JSON 변환, GraphRAG 인덱싱 완료",
            finished_at=time.time(),                    # 완료 시각 기록
        )
        print(f"[PIPELINE][INDEX] finished job_id={job_id}")

    except Exception as e:
        # 파이프라인 실행 중 예외 발생 시 로그 출력
        print(f"[PIPELINE][INDEX][ERROR] job_id={job_id} error={e}")
        traceback.print_exc()   # 자세한 에러 스택 출력

        try:
            # 작업 상태를 failed로 저장
            update_job(
                job_id,
                status="failed",
                progress=100,                   # 실패했더라도 작업 종료이므로 100
                message="그래프 파이프라인 실패",
                error=str(e),                   # 실제 에러 문자열 저장
                finished_at=time.time(),        # 실패 시각 기록
            )
        except Exception as inner_e:
            # 실패 상태 저장을 실패한 경우
            print(f"[PIPELINE][INDEX][ERROR] failed to save failed status job_id={job_id} error={inner_e}")
            traceback.print_exc()

# 메일데이터 그래프 데이터 JSON, GraphRAG 업데이트를 수행하는 파이프라인 
def run_graph_update_pipeline(job_id):
    print(f"[PIPELINE][UPDATE] start job_id={job_id}")

    try:
        # 작업 상태 running로 변경
        update_job(job_id, status="running", progress=1, message="그래프 업데이트 파이프라인 시작")
        print(f"[PIPELINE][UPDATE] job updated to running job_id={job_id}")

        env = os.environ.copy() # 현재 프로세스의 환경변수를 복사
        env["PYTHONUTF8"] = "1" # Python이 UTF-8 모드로 동작하도록 설정, 한글/특수문자 깨짐 방지 목적
        env["PYTHONIOENCODING"] = "utf-8" # 표준입출력 인코딩을 utf-8로 강제
        env["RICH_DISABLE"] = "1" # rich 라이브러리의 컬러/장식 출력 비활성화, 로그 파일이나 콘솔에서 ANSI escape 문자 깨짐 방지

        print(f"[PIPELINE][UPDATE] env prepared job_id={job_id}")
        print(f"[PIPELINE][UPDATE] cwd={os.getcwd()} job_id={job_id}")

        # 인덱싱이 끝난 후 그래프 시각화용 JSON 생성
        print(f"[PIPELINE][UPDATE] calling build_graph_json job_id={job_id}")
        build_graphrag_update(job_id, env) 
        print(f"[PIPELINE][UPDATE] build_graph_json DONE job_id={job_id}")
        # 그래프라그 업데이트 시작
        print(f"[PIPELINE][UPDATE] calling build_graphrag_update job_id={job_id}")
        build_graph_json(job_id, env)
        print(f"[PIPELINE][UPDATE] build_graphrag_update DONE job_id={job_id}")

        # 모든 작업이 성공적으로 끝났으면 상태를 done으로 변경
        update_job(
            job_id,
            status="done",
            progress=100,
            message="JSON 변환, GraphRAG 업데이트 완료",
            finished_at=time.time(), # 완료 시각 기록
        )
        print(f"[PIPELINE][UPDATE] finished job_id={job_id}")

    except Exception as e:
        # 파이프라인 실행 중 예외 발생 시 로그 출력
        print(f"[PIPELINE][UPDATE][ERROR] job_id={job_id} error={e}")
        traceback.print_exc() # 자세한 에러 스택 출력

        try:
            # 작업 상태를 failed로 저장
            update_job(
                job_id,
                status="failed",
                progress=100, # 실패했더라도 작업 종료이므로 100
                message="그래프 업데이트 파이프라인 실패",
                error=str(e), # 실제 에러 문자열 저장
                finished_at=time.time(), # 실패 시각 기록
            )
        except Exception as inner_e:
            # 실패 상태 저장을 실패한 경우
            print(f"[PIPELINE][UPDATE][ERROR] failed to save failed status job_id={job_id} error={inner_e}")
            traceback.print_exc()



# 인덱싱 여부 확인
def _is_index_ready(paths):
    stats_path = os.path.join(paths.GRAPHRAG_ROOT, "output", "stats.json")

    try:
        required_paths = [paths.MAIL_LATEST_PATH, stats_path]

        for path in required_paths:
            if not os.path.exists(path):
                print(f"[INDEX READY] missing: {path}")
                return False
            if os.path.getsize(path) == 0:
                print(f"[INDEX READY] empty file: {path}")
                return False

        _read_json_file(stats_path)
        return True

    except Exception as e:
        print(f"[INDEX READY] invalid index state: {e}")
        return False