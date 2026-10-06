# 게시판 새 글 알림

이 저장소는 이천시설관리공단 게시판들을 확인하고, 새 게시글이 있으면 `ssk1024@2000fmc.or.kr`로 이메일을 보내는 Python 스크립트입니다.

## 모니터링 대상

- 고객의 소리: <https://www.2000fmc.or.kr/ic-kr/bbs/i-74/list.do>
- 고객제안: <https://www.2000fmc.or.kr/ic-kr/bbs/i-75/list.do>
- 주민참여예산: <https://www.2000fmc.or.kr/ic-kr/bbs/i-76/list.do>
- 칭찬합시다: <https://www.2000fmc.or.kr/ic-kr/bbs/i-77/list.do>
- 안전신문고: <https://www.2000fmc.or.kr/ic-kr/bbs/i-78/list.do>

## 동작 방식

- 각 게시판 목록 페이지에서 최신 게시글의 번호, 제목, 등록일, 상세 링크를 추출합니다.
- 마지막으로 확인한 게시글 번호는 게시판별로 `data/board_state.json`에 저장합니다.
- 첫 확인 게시판은 기존 게시글을 이메일로 보내지 않고 현재 최신 게시글 번호만 저장합니다.
- 이후 실행부터 저장된 번호보다 큰 게시글이 있으면 모두 이메일 본문에 포함해 발송합니다.
- 상세 링크가 상대경로이거나 JavaScript 이동 방식이면 절대 URL로 변환합니다.
- 게시판 접속이 일시적으로 실패하면 최대 3번 재시도합니다.

## 로컬 실행

```bash
pip install -r requirements.txt

export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USER="smtp-user"
export SMTP_PASS="smtp-password"
export MAIL_FROM="alert@example.com"

python check_board.py
```

Windows PowerShell에서는 아래처럼 환경변수를 설정합니다.

```powershell
$env:SMTP_HOST = "smtp.example.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "smtp-user"
$env:SMTP_PASS = "smtp-password"
$env:MAIL_FROM = "alert@example.com"

python check_board.py
```

상태 파일 경로를 바꾸려면 `STATE_FILE` 환경변수를 추가로 설정하면 됩니다.

```bash
export STATE_FILE="data/board_state.json"
```

## GitHub Actions 설정

`.github/workflows/board-alert.yml`은 한국시간 09:17부터 17:17까지 1시간마다 자동 실행되며, 수동 실행도 가능합니다.

GitHub 저장소의 `Settings > Secrets and variables > Actions > Repository secrets`에 아래 secrets를 등록하세요.

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `MAIL_FROM`

GitHub Actions는 `data/board_state.json`을 읽고 실행 후 상태를 저장소에 커밋합니다. 캐시 만료로 상태가 초기화되지 않으며, 상태 커밋이 지속적으로 생성되어 예약 워크플로 자동 비활성화도 방지합니다. 첫 확인 게시판에서는 현재 최신 번호만 저장하고 이메일은 보내지 않습니다.

## 파일 구성

- `check_board.py`: 게시판 확인 및 이메일 발송 로직
- `requirements.txt`: 필요한 Python 패키지
- `.github/workflows/board-alert.yml`: GitHub Actions 자동 실행 설정
- `README.md`: 환경변수 설정 및 실행 방법
