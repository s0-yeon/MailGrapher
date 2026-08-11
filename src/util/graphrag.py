import os
import time 
import traceback
import re
import subprocess

from util.jobs.job_store import update_job
from util.jobs.job_run import build_graph_json,build_graphrag_index,build_graphrag_update
from util.database.db_writer import save_query_to_db
from util.file_manager import _read_json_file
from util.graphrag_query import strip_ids_for_display

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

    stdout_text = decode_output(result.stdout)
    stderr_text = decode_output(result.stderr)

    answer = None
    if result.returncode == 0:
        match = re.search(r'SUCCESS: (?:Local|Global) Search Response:\s*(.*)', stdout_text, re.DOTALL)
        answer = match.group(1).strip() if match else stdout_text.strip()
        answer = re.sub(r'\[Data:.*?\]|\[데이터:.*?\]', '', answer)
        answer = re.sub(r'\*+|#+', '', answer)
        answer = strip_ids_for_display(answer)

    try:
        save_query_to_db(paths.USER_ID, raw_message, elapsed, resMethod, answer=answer)
    except Exception as e:
        print(f"[WARN] query DB 저장 실패 (무시): {e}")

    if result.returncode != 0:
        raise RuntimeError(stderr_text or stdout_text or 'GraphRAG 실행 오류')

    print(stdout_text)
    print(answer)
    return answer.strip()

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