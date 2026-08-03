# MailGrapher

메일 데이터를 분석해 지식 그래프를 만들고, 사람/시간 통계와 자연어 검색을 제공

# 실행 방법

## 1. 사전 준비
- Python 3.11
- Node.js
- MySQL 서버

## 2. 파이썬 가상환경 & 모듈 설치
```bash
python -m venv mailgrapher-venv
mailgrapher-venv\Scripts\activate
```

가상환경 실행
```bash
source mailgrapher-venv/Scripts/activate
```

모듈 설치
```bash
pip install -r requirements.txt
```

## 3. 환경변수 설정
`src/parquet/.env` : GmailWeaver에서 복붙하세요

## 4. MySQL 데이터베이스 생성
기존에 있는거 쓰세요

## 5. 백엔드 실행 (프로젝트 루트에서)
```bash
python src/app.py
```
→ `http://localhost/dashboard/` 에서 실행됨

## 6. 프론트엔드 실행 (`src/web`에서)
```bash
npm install
npm run build
```
→ 빌드 후 백엔드(80번)만 켜면 `http://localhost` 로 바로 접속 가능

개발 중이라 화면을 수정하며 바로 확인하고 싶다면:
```bash
npm run dev
```
→ `http://localhost:3000` (단, 백엔드(80)도 같이 켜져 있어야 API가 동작함)


