import os
import re
import openai  
import zlib
import uuid
import base64
import traceback   

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import fitz  # PyMuPDF
from docx import Document
import olefile
import csv
from pptx import Presentation
from openpyxl import load_workbook
from flask import send_from_directory

from config.settings import *
from util.file_manager import _sanitize_filename, _delete_old_update_files
from util.jobs.job_store import update_job
from util.database.db_writer import mark_attachments_as_processed
from util.jobs.job_run import build_graphrag_update, build_graph_json

# 첨부파일 텍스트 요약
def _summarize_attachment(text: str, filename: str) -> str:
    pure_len = len(text.replace(" ", "").replace("\n", ""))
    if pure_len < 500:
        return text

    prompt_path = os.path.join("parquet_template", "prompts", "summarize_attachment.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    client = openai.OpenAI(api_key=os.environ.get("GRAPHRAG_API_KEY"))
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"파일명: {filename}\n\n{text}"}
            ],
            max_tokens=150
        )
        result = response.choices[0].message.content.strip()
        REFUSAL_PREFIXES = ("죄송", "I'm sorry", "I'm unable", "I cannot", "Sorry")
        if result.startswith(REFUSAL_PREFIXES):
            print(f"[summarize_attachment] LLM 거부 응답 감지: {filename}")
            return ""
        return result
    except Exception as e:
        print(f"[summarize_attachment error] {e}")
        return ""

# PDF 파일에서 텍스트 추출
def _extract_text_from_pdf(file_path):
    text = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception as e:
        print(f"[PDF Extract Error] {e}")
    return text

# Word 파일에서 텍스트 추출
def _extract_text_from_docx(file_path):
    text = ""
    try:
        doc = Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"[Docx Extract Error] {e}")
    return text

# HWP 파일에서 텍스트 추출
def _extract_text_from_hwp(file_path):
    text = ""
    try:
        f = olefile.OleFileIO(file_path)
        dirs = f.listdir()
        sections = [d for d in dirs if "BodyText/Section" in "/".join(d)]
        for section in sections:
            stream = f.openstream("/".join(section))
            data = stream.read()
            try:
                decompressed = zlib.decompress(data, -15)
                decoded_text = decompressed.decode("utf-16-le", errors="ignore")
                clean_text = "".join(c for c in decoded_text if c.isalnum() or c in " \n\t.,()[]")
                text += clean_text + "\n"
            except Exception as e:
                print(f"[HWP Decode Error in {section}] {e}")
        f.close()
    except Exception as e:
        print(f"[HWP Extract Error] {e}")
    return text

# TXT 파일에서 텍스트 추출
def _extract_text_from_txt(file_path):
    text = ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="cp949") as f:
                text = f.read()
        except Exception as e:
            print(f"[TXT Extract Error] {e}")
    except Exception as e:
        print(f"[TXT Extract Error] {e}")
    return text

# PPTX 파일에서 텍스트 추출
def _extract_text_from_pptx(file_path):
    text = ""
    try:
        prs = Presentation(file_path)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    text += shape.text + "\n"
    except Exception as e:
        print(f"[PPTX Extract Error] {e}")
    return text

# XLSX 파일에서 텍스트 추출
def _extract_text_from_xlsx(file_path):
    text = ""
    try:
        wb = load_workbook(file_path, data_only=True)
        for ws in wb.worksheets:
            text += f"[Sheet] {ws.title}\n"
            for row in ws.iter_rows(values_only=True):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                if any(v.strip() for v in row_values):
                    text += " | ".join(row_values) + "\n"
            text += "\n"
    except Exception as e:
        print(f"[XLSX Extract Error] {e}")
    return text

# CSV 파일에서 텍스트 추출
def _extract_text_from_csv(file_path):
    text = ""
    try:
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                row_values = [str(cell) if cell is not None else "" for cell in row]
                text += " | ".join(row_values) + "\n"
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="cp949", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    row_values = [str(cell) if cell is not None else "" for cell in row]
                    text += " | ".join(row_values) + "\n"
        except Exception as e:
            print(f"[CSV Extract Error] {e}")
    except Exception as e:
        print(f"[CSV Extract Error] {e}")
    return text

# attachment payload에서 base64를 받아 서버 로컬에 파일 저장
def _save_attachment_from_base64(file_info: dict, save_dir: str) -> tuple[str, str]:
    original_name = file_info.get("name") or "attachment.bin"
    safe_name = _sanitize_filename(original_name)
    mail_id = str(file_info.get("mail_id") or "no_mail_id")
    data_base64 = file_info.get("data_base64") or ""

    if not data_base64:
        raise ValueError(f"attachment data_base64 missing: {original_name}")

    os.makedirs(save_dir, exist_ok=True)

    ext = os.path.splitext(safe_name)[1].lower()
    unique_name = f"{mail_id}_{uuid.uuid4().hex[:8]}{ext or '.bin'}"
    saved_path = os.path.join(save_dir, unique_name)

    if "," in data_base64 and "base64" in data_base64[:100]:
        data_base64 = data_base64.split(",", 1)[1]

    file_bytes = base64.b64decode(data_base64)

    with open(saved_path, "wb") as f:
        f.write(file_bytes)

    return saved_path, original_name

# 백그라운드: 첨부파일 텍스트 추출 → 요약 → attachment_latest.txt 저장 → graphrag update
def _run_attachment_pipeline(job_id: str, paths, attachments: list, env: dict, is_last):
    print(f"[JOB][attachment] START job_id={job_id}")
    update_job(job_id, status="running", progress=0, message="첨부파일 텍스트 추출 중")

    try:
        attachment_texts_by_mail: dict[str, list[dict]] = {}

        # 1) 첨부파일 저장 + 텍스트 추출
        for file_info in attachments:
            f_name = file_info.get("name") or "attachment.bin"
            mime = (file_info.get("mime") or "").lower()
            mail_id = str(file_info.get("mail_id") or "").strip()

            if not mail_id:
                continue

            try:
                saved_path, original_name = _save_attachment_from_base64(file_info, paths.ATTACHMENT_DIR)
                ext = os.path.splitext(original_name)[-1].lower()
                file_text = ""

                if ext == ".pdf" or "pdf" in mime:     file_text = _extract_text_from_pdf(saved_path)
                elif ext == ".docx":                    file_text = _extract_text_from_docx(saved_path)
                elif ext == ".hwp":                     file_text = _extract_text_from_hwp(saved_path)
                elif ext == ".txt" or "plain" in mime:  file_text = _extract_text_from_txt(saved_path)
                elif ext == ".pptx":                    file_text = _extract_text_from_pptx(saved_path)
                elif ext == ".xlsx":                    file_text = _extract_text_from_xlsx(saved_path)
                elif ext == ".csv":                     file_text = _extract_text_from_csv(saved_path)

                if file_text and file_text.strip():
                    attachment_texts_by_mail.setdefault(mail_id, []).append({
                        "name": original_name,
                        "text": file_text.strip()
                    })

            except Exception as e:
                print(f"[JOB][attachment] extract error {f_name}: {e}")

        update_job(job_id, progress=30, message="첨부파일 요약 중")

        # 2) 요약
        summarized_by_mail: dict[str, list[dict]] = {}
        for mail_id, items in attachment_texts_by_mail.items():
            summarized_by_mail[mail_id] = [
                {
                    "name": item["name"],
                    "text": _summarize_attachment(item["text"], item["name"])
                }
                for item in items
            ]

        update_job(job_id, progress=50, message="attachment_latest.txt 저장 중")

        # 3) 기록용 attachment_latest.txt 저장
        _write_attachment_file(paths, summarized_by_mail)

        # 기존 본문과 합친 '증분 전용 CSV' 생성
        merged_csv_path = _build_merged_attachment_csv(paths, summarized_by_mail)

        if not merged_csv_path:
            print("[JOB][attachment] 업데이트할 병합 데이터가 없습니다. 종료합니다.")
            update_job(job_id, status="done", message="업데이트할 내용 없음")
            return

        update_job(job_id, progress=60, message="GraphRAG Update 실행 중")

        # 4) graphrag update → json 생성 (마지막 배치일 때만)
        print(f"[JOB][attachment] is_last={is_last}, job_id={job_id}")
        if is_last:
            build_graphrag_update(job_id, paths, env)
            build_graph_json(job_id, paths, env)
        else:
            print(f"[JOB][attachment] 중간 배치 → GraphRAG update 생략, 누적 중")
            _delete_old_update_files(paths)
            mark_attachments_as_processed(paths.GMAIL_ID, attachments)
            update_job(job_id, status="done", message="첨부파일 누적 완료 (중간 배치)")
            return

        # 6) 처리 완료된 이전 update_output 폴더 삭제
        _delete_old_update_files(paths)

        # [추가] 7) 처리 완료된 첨부파일 DB에 기록 (다음 트리거에서 중복 방지)
        mark_attachments_as_processed(paths.GMAIL_ID, attachments)

        update_job(job_id, progress=100, status="done", message="첨부파일 인덱싱 완료")
        print(f"[JOB][attachment] SUCCESS job_id={job_id}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        update_job(job_id, status="failed", message=error_msg)
        print(f"[JOB][attachment][ERROR] job_id={job_id} error={error_msg}")
        traceback.print_exc()

# 기존 mail_latest.csv에서 원본 본문을 읽어와 첨부파일 요약본을 뒤에 붙인 '증분 전용 CSV'를 생성
def _build_merged_attachment_csv(paths, summarized_by_mail: dict[str, list[dict]]):
    # mail_latest.csv + inc_*.csv 전부 읽기 (append 모드에서 새 메일도 포함)
    original_mails = {}
    if not os.path.exists(paths.MAIL_DIR):
        print(f"[AttachmentFile] MAIL_DIR가 없습니다: {paths.MAIL_DIR}")
        return None
    for fname in os.listdir(paths.MAIL_DIR):
        if fname == "mail_latest.csv" or (fname.startswith("inc_") and fname.endswith(".csv") and not fname.startswith("inc_att")):
            csv_path = os.path.join(paths.MAIL_DIR, fname)
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        original_mails[row['id']] = row['text']
            except Exception as e:
                print(f"[AttachmentFile] CSV 읽기 실패: {csv_path} / {e}")

    if not original_mails:
        print(f"[AttachmentFile] 읽을 수 있는 메일 CSV가 없습니다.")
        return None

    csv_rows = []
    for m_id, items in summarized_by_mail.items():
        if m_id in original_mails:
            att_summaries = []
            for item in items:
                att_summaries.append(f"File name: {item['name']}\nSummary: {item['text']}")
            combined_att_text = "\n\n".join(att_summaries)
            combined_text = (
                f"{original_mails[m_id]}\n\n"
                f"[첨부파일 요약]\n"
                f"{combined_att_text}"
            )
            csv_rows.append({"id": m_id, "text": combined_text})
        else:
            print(f"[AttachmentFile] 메일 ID {m_id}를 원본 CSV에서 찾을 수 없습니다.")

    if not csv_rows:
        return None

    new_csv_path = os.path.join(paths.MAIL_DIR, "attachment_latest.csv")
    try:
        # 기존 CSV 읽어서 누적 (중간 배치 내용 보존)
        existing_rows = {}
        if os.path.exists(new_csv_path):
            with open(new_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_rows[row["id"]] = row["text"]
        # 새 배치로 갱신 (같은 mail_id면 최신 요약으로 덮어씀)
        for row in csv_rows:
            existing_rows[row["id"]] = row["text"]

        with open(new_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "text"])
            writer.writeheader()
            writer.writerows([{"id": k, "text": v} for k, v in existing_rows.items()])
        print(f"[AttachmentFile] 증분 병합 CSV 생성 완료: {new_csv_path} ({len(existing_rows)}개)")
        return new_csv_path
    except Exception as e:
        print(f"[AttachmentFile] 증분 CSV 생성 중 오류: {e}")
        return None
    
# attachment_latest.txt 저장
def _write_attachment_file(paths, summarized_by_mail: dict[str, list[dict]]):
    att_path = os.path.join(paths.MAIL_DIR, "attachment_latest.txt")

    existing: dict[str, list[dict]] = {}
    if os.path.exists(att_path):
        try:
            with open(att_path, "r", encoding="utf-8") as f:
                raw = f.read()
            existing = _parse_attachment_file(raw)
        except Exception as e:
            print(f"[AttachmentFile] 기존 파일 파싱 실패, 덮어씀: {e}")

    existing.update(summarized_by_mail)

    subjects: dict[str, str] = {}
    if os.path.exists(paths.MAIL_LATEST_PATH):
        with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
            mail_content = f.read()
        for block in mail_content.split(MAIL_BLOCK_SEP):
            id_m = re.search(r"^ID:\s*(.+?)$", block, re.MULTILINE)
            sub_m = re.search(r"제목:\s*(.+?)$", block, re.MULTILINE)
            if id_m and sub_m:
                subjects[id_m.group(1).strip()] = sub_m.group(1).strip()

    lines = []
    for mail_id, items in existing.items():
        for item in items:
            lines.append("[첨부파일 요약]")
            lines.append(f"ID: {mail_id}")
            subject = subjects.get(mail_id, "")
            if subject:
                lines.append(f"제목: {subject}")
            lines.append(f"[File name] {item['name']}")
            lines.append(item['text'])
            lines.append(MAIL_BLOCK_SEP)

    with open(att_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[AttachmentFile] 저장 완료 → {att_path} ({len(existing)}개 메일)")

# attachment_latest.txt 파싱 → {mail_id: [{name, text}]} 형태로 반환
def _parse_attachment_file(raw: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    blocks = raw.split(MAIL_BLOCK_SEP)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        m = re.search(r"^ID:\s*(.+?)$", block, re.MULTILINE)
        if not m:
            continue
        mail_id = m.group(1).strip()

        items = []
        file_blocks = re.split(r"^\[File name\]", block, flags=re.MULTILINE)
        for fb in file_blocks[1:]:
            fb_lines = fb.strip().splitlines()
            if not fb_lines:
                continue
            name = fb_lines[0].strip()
            text = "\n".join(fb_lines[1:]).strip()
            items.append({"name": name, "text": text})

        if items:
            result.setdefault(mail_id, []).extend(items)

    return result

