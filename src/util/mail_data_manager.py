import re
import datetime
import os
import csv

from config.settings import *

# 메일 블록에서 'ID: ...' 값을 추출
def _extract_mail_id_from_block(block: str) -> str | None:
    m = re.search(r"^\s*ID:\s*(.+?)\s*$", block, re.MULTILINE)
    return m.group(1).strip() if m else None

# mail_id 기준으로 첨부 텍스트를 각 메일 블록 하단에 삽입한 후 다시 append
def _merge_attachments_into_mail_blocks(content: str, attachment_texts_by_mail: dict[str, list[dict]]) -> str:
    parts = content.split(MAIL_BLOCK_SEP)
    merged_blocks = []

    for part in parts:
        block = part.strip()
        if not block:
            continue

        block_text = f"{MAIL_BLOCK_SEP}\n{block}\n{MAIL_BLOCK_SEP}"

        mail_id = _extract_mail_id_from_block(block_text)
        if not mail_id:
            merged_blocks.append(block_text)
            continue

        attachment_entries = attachment_texts_by_mail.get(mail_id, [])
        if not attachment_entries:
            merged_blocks.append(block_text)
            continue

        attachment_section = "\n[첨부 추출 내용]\n"
        for item in attachment_entries:
            attachment_section += f"[File name] {item['name']}\n{item['text']}\n"

        insert_pos = block_text.rfind(MAIL_BLOCK_SEP)
        if insert_pos == -1:
            merged_blocks.append(block_text + attachment_section)
        else:
            merged_blocks.append(
                block_text[:insert_pos].rstrip() + "\n\n" +
                attachment_section.rstrip() + "\n" +
                MAIL_BLOCK_SEP
            )

    return "\n".join(merged_blocks) + "\n"

# 텍스트에서 메일별로 구분
def _split_mail_blocks(text):
    parts = text.split(MAIL_BLOCK_SEP)
    blocks = []

    for p in parts:
        p = p.strip()
        if not p:
            continue
        block = MAIL_BLOCK_SEP + "\n" + p
        if not block.endswith(MAIL_BLOCK_SEP):
            block += "\n" + MAIL_BLOCK_SEP
        blocks.append(block)

    return blocks

# 메일 번호 재정렬
def _renumber_mail_blocks(text: str) -> str:
    blocks = _split_mail_blocks(text)
    result = []
    for i, block in enumerate(blocks, start=1):
        renumbered = re.sub(r'\[메일 \d+\]', f'[메일 {i}]', block)
        result.append(renumbered)
    return "\n".join(result) + "\n"

# 메일 id들 추출해서 집합으로 반환
def _extract_message_ids(text):
    return set(re.findall(r"^\s*ID:\s*(.+?)\s*$", text, flags=re.MULTILINE))

# 메일 블록에서 "날짜:" 부분 파싱해서 datetime 객체로 반환
def _extract_block_for_sort(block):
    for line in block.splitlines():
        if line.startswith("날짜:"):
            raw = line.replace("날짜:", "").strip()
            try:
                return datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.datetime.min
    return datetime.datetime.min

# 현재 mail_latest.txt 파일 전체 문자열로 읽어서 반환
def _read_latest_text(paths):
    if not os.path.exists(paths.MAIL_LATEST_PATH):
        return ""
    with open(paths.MAIL_LATEST_PATH, "r", encoding="utf-8") as f:
        return f.read()

# 메일 데이터 txt를 csv로 파싱
def _build_mail_csv(paths, mode="rewrite", new_ids=None) -> str | None:
    # 1) mail_latest.txt 파싱 → {mail_id: block_text}
    mail_text = _read_latest_text(paths)
    mail_blocks: dict[str, str] = {}

    for block in _split_mail_blocks(mail_text):
        mail_id = _extract_mail_id_from_block(block)
        if mail_id:
            mail_blocks[mail_id] = block.strip()

    # 2) CSV row 생성
    rows = []
    for mail_id, block_text in mail_blocks.items():
        clean_text = block_text.replace(MAIL_BLOCK_SEP, "").strip()
        rows.append({"id": mail_id, "text": clean_text})

    # 3) mode에 따라 저장 대상 결정
    if mode == "append" and new_ids:
        # append + 새 메일 있음: 새 메일만 필터링해서 증분 CSV 생성
        rows = [r for r in rows if r["id"] in new_ids]
        csv_name = f"inc_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.csv"

    elif mode == "append" and not new_ids:
        # [수정] append + 새 메일 없음: CSV 생성 불필요 → None 반환
        # 기존에는 else로 떨어져 mail_latest.csv 전체를 덮어쓰는 버그가 있었음
        print("[CSV] append 모드이나 new_ids 없음 → CSV 생성 생략")
        return None

    else:
        # rewrite: 전체를 mail_latest.csv로 저장
        csv_name = "mail_latest.csv"

    csv_path = os.path.join(paths.MAIL_DIR, csv_name)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "text"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"[CSV] 생성 완료 → {csv_path} ({len(rows)}개 메일)")
    return csv_path
