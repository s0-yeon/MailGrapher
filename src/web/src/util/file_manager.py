import os
import re
import shutil
import datetime
import json

# 파일명에서 경로/위험 문자 제거
def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "attachment.bin").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "attachment.bin"

# 업데이트 시 생기는 update_output 폴더 속 새로운 결과 파일 삭제
def _delete_old_update_files(paths):
    update_output_dir = paths.UPDATE_DIR
    if not os.path.exists(update_output_dir):
        return

    folders = sorted([
        f for f in os.listdir(update_output_dir)
        if os.path.isdir(os.path.join(update_output_dir, f))
    ])

    for folder in folders[:-1]:
        folder_path = os.path.join(update_output_dir, folder)
        try:
            shutil.rmtree(folder_path)
            print(f"[CLEANUP] 삭제: {folder_path}")
        except Exception as e:
            print(f"[CLEANUP] 삭제 실패 (무시): {e}")

# 업데이트 시 생기는 input 폴더 속 새로운 메일 증분 파일 삭제
def _delete_incremental_files(paths):
    os.makedirs(paths.MAIL_DIR, exist_ok=True)

    for name in os.listdir(paths.MAIL_DIR):
        is_inc_txt = name.startswith("inc_") and name.endswith(".txt")
        is_inc_csv = name.startswith("inc_") and name.endswith(".csv")
        is_att_txt = name == "attachment_latest.txt"

        if is_inc_txt or is_inc_csv or is_att_txt:
            path = os.path.join(paths.MAIL_DIR, name)
            try:
                os.remove(path)
            except Exception as e:
                print(f"[UPLOAD] failed to remove incremental file: {path} / {e}")

# 증분 파일 저장경로 생성
def _build_incremental_path(filename: str, paths) -> str:
    safe_name = _sanitize_filename(filename or "")
    if not safe_name.startswith("inc_"):
        safe_name = f"inc_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    return os.path.join(paths.MAIL_DIR, safe_name)

# json 파일 읽어서 dict로 파싱 후 반환
def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)