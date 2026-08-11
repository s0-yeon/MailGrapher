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
`src/parquet/.env` : 노션에서 복붙하세요(mail grapher용 .env)

## 4. MySQL 데이터베이스 생성
mail_grapher_db 를 사용. (노션 참고)

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

---

# LightRAG 설치 (Windows / Git Bash 기준)

MailGrapher 프로젝트에서 LightRAG를 서버로 띄우기 위해 진행한 과정 정리.
가상환경 이름: `mailgrapher-venv`

## 1. 저장소 클론

```bash
git clone https://github.com/HKUDS/LightRAG.git
cd LightRAG
```

## 2. uv 설치

Windows에는 `make` 명령어가 기본으로 없어서, LightRAG 공식 가이드의 `make dev` 대신
`uv`(파이썬 의존성 관리 도구)를 직접 설치해서 사용.

PowerShell에서 실행, 설치 후 Git Bash 재시작

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

- 설치 위치: `C:\Users\2471369\.local\bin`

## 3. Git Bash에서 uv 인식 안 되는 문제 (PATH)

설치 직후 Git Bash를 새로 열어도 `uv: command not found` 발생.
PowerShell/cmd용 PATH 등록 방법은 Git Bash(MINGW64)에는 적용되지 않기 때문.

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

영구 등록 (한 번만 실행, 완료):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

## 4. 가상환경 이름 지정 (mailgrapher-venv) + 의존성 설치

```bash
export UV_PROJECT_ENVIRONMENT=mailgrapher-venv
uv venv mailgrapher-venv
uv sync --extra test --extra offline
```

영구 등록 (한 번만 실행, 완료):

```bash
echo 'export UV_PROJECT_ENVIRONMENT=mailgrapher-venv' >> ~/.bashrc
```

## 5. 가상환경 활성화

```bash
source mailgrapher-venv/Scripts/activate
```

## 6. 웹 UI 빌드

PowerShell에서 실행, 설치 후 Git Bash 재시작

```powershell
powershell -c "irm bun.sh/install.ps1|iex"
```

```bash
cd lightrag_webui
bun install --frozen-lockfile
bun run build
cd ..
```

## 7. 설정 파일(.env) 생성

```bash
cp env.example .env
```

## 8. 서버 실행

```bash
lightrag-server
```

브라우저에서 `http://localhost:9621` 접속 → 확인


