import json
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BOARDS = [
    {
        "id": "i-74",
        "name": "고객의 소리",
        "url": "https://www.2000fmc.or.kr/ic-kr/bbs/i-74/list.do",
    },
    {
        "id": "i-75",
        "name": "고객제안",
        "url": "https://www.2000fmc.or.kr/ic-kr/bbs/i-75/list.do",
    },
    {
        "id": "i-76",
        "name": "주민참여예산",
        "url": "https://www.2000fmc.or.kr/ic-kr/bbs/i-76/list.do",
    },
    {
        "id": "i-77",
        "name": "칭찬합시다",
        "url": "https://www.2000fmc.or.kr/ic-kr/bbs/i-77/list.do",
    },
    {
        "id": "i-78",
        "name": "안전신문고",
        "url": "https://www.2000fmc.or.kr/ic-kr/bbs/i-78/list.do",
    },
]
STATE_FILE = Path(os.getenv("STATE_FILE", ".board_state/last_seen.json"))
MAIL_TO = "ssk1024@2000fmc.or.kr"
MAIL_SUBJECT = "[게시판] 새 게시글 알림"
REQUEST_TIMEOUT = 20
REQUEST_RETRIES = 3


@dataclass(frozen=True)
class BoardPost:
    board_id: str
    board_name: str
    number: int
    title: str
    date: str
    link: str


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def detail_url_for(list_url: str) -> str:
    return list_url.replace("/list.do", "/detail.do")


def fetch_board_html(url: str) -> str:
    last_error: requests.RequestException | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "board-alert/1.0"},
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            log(f"게시판 접속 실패({attempt}/{REQUEST_RETRIES}): {url} ({exc})")
            if attempt < REQUEST_RETRIES:
                time.sleep(5 * attempt)
    else:
        raise RuntimeError(f"게시판 접속 실패: {url} ({last_error})") from last_error

    if not response.text.strip():
        raise RuntimeError(f"게시판 접속 실패: 응답 본문이 비어 있습니다. ({url})")

    return response.text


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_post_number(row) -> int | None:
    number_cell = row.select_one(".cell-no") or row.find("td")
    if not number_cell:
        return None

    match = re.search(r"\d+", number_cell.get_text(" ", strip=True))
    return int(match.group()) if match else None


def extract_detail_link(anchor, base_url: str) -> str:
    href = (anchor.get("href") or "").strip()
    if href and not href.lower().startswith("javascript:"):
        return urljoin(base_url, href)

    ntt_sn = anchor.get("data-ntt-sn") or anchor.get("data-ntt_sn")
    if not ntt_sn and href:
        parsed = parse_qs(urlparse(href).query)
        ntt_sn = (parsed.get("ntt_sn") or [""])[0]

    if ntt_sn:
        return f"{detail_url_for(base_url)}?ntt_sn={ntt_sn}"

    return urljoin(base_url, href or "./detail.do")


def extract_title(subject_cell) -> str:
    subject_copy = BeautifulSoup(str(subject_cell), "html.parser")
    for removable in subject_copy.select(".comment-number, .sr-only, .ico-new"):
        removable.decompose()
    return clean_text(subject_copy.get_text(" ", strip=True))


def parse_posts(board: dict[str, str], html: str) -> list[BoardPost]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.table.table-list tbody tr")
    if not rows:
        rows = soup.select("table tbody tr")

    posts: list[BoardPost] = []
    for row in rows:
        number = extract_post_number(row)
        subject_cell = row.select_one(".cell-subject")
        date_cell = row.select_one(".cell-date")
        anchor = subject_cell.find("a") if subject_cell else None

        if number is None or not subject_cell or not date_cell or not anchor:
            continue

        post = BoardPost(
            board_id=board["id"],
            board_name=board["name"],
            number=number,
            title=extract_title(subject_cell),
            date=clean_text(date_cell.get_text(" ", strip=True)),
            link=extract_detail_link(anchor, board["url"]),
        )
        if post.title:
            posts.append(post)

    if not posts:
        raise RuntimeError(
            f"게시글 파싱 실패: {board['name']} 목록에서 게시글 번호, 제목, 등록일, 링크를 찾지 못했습니다."
        )

    return sorted(posts, key=lambda item: item.number, reverse=True)


def load_state(path: Path = STATE_FILE) -> dict:
    if not path.exists():
        return {"boards": {}}

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"상태 파일 읽기 실패: {path} ({exc})") from exc

    if "boards" in data:
        return data

    # Backward compatibility for the old single-board state file.
    last_seen = data.get("last_seen_number")
    migrated = {"boards": {}}
    if last_seen is not None:
        migrated["boards"]["i-74"] = {
            "last_seen_number": int(last_seen),
            "updated_at": data.get("updated_at"),
            "board_url": data.get("board_url", BOARDS[0]["url"]),
        }
    return migrated


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with path.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write("\n")
    except OSError as exc:
        raise RuntimeError(f"상태 파일 저장 실패: {path} ({exc})") from exc


def get_last_seen_number(state: dict, board_id: str) -> int | None:
    board_state = state.get("boards", {}).get(board_id, {})
    value = board_state.get("last_seen_number")
    return int(value) if value is not None else None


def set_last_seen_number(state: dict, board: dict[str, str], number: int) -> None:
    state.setdefault("boards", {})[board["id"]] = {
        "name": board["name"],
        "last_seen_number": number,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "board_url": board["url"],
    }


def find_new_posts(posts: Iterable[BoardPost], last_seen_number: int) -> list[BoardPost]:
    return sorted(
        [post for post in posts if post.number > last_seen_number],
        key=lambda item: (item.board_name, item.number),
    )


def build_email_body(posts: list[BoardPost]) -> str:
    lines = [
        "모니터링 중인 게시판에 새 게시글이 등록되었습니다.",
        "",
    ]
    current_board = None
    for post in posts:
        if current_board != post.board_name:
            current_board = post.board_name
            lines.extend([f"[{current_board}]", ""])
        lines.extend(
            [
                f"- 번호: {post.number}",
                f"  제목: {post.title}",
                f"  등록일: {post.date}",
                f"  상세 링크: {post.link}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"메일 발송 실패: 환경변수 {name}이(가) 설정되지 않았습니다.")
    return value


def send_email(posts: list[BoardPost]) -> None:
    smtp_host = get_required_env("SMTP_HOST")
    smtp_port_text = get_required_env("SMTP_PORT")
    smtp_user = get_required_env("SMTP_USER")
    smtp_pass = get_required_env("SMTP_PASS")
    mail_from = get_required_env("MAIL_FROM")

    try:
        smtp_port = int(smtp_port_text)
    except ValueError as exc:
        raise RuntimeError(f"메일 발송 실패: SMTP_PORT는 숫자여야 합니다. 현재 값: {smtp_port_text}") from exc

    message = EmailMessage()
    message["Subject"] = MAIL_SUBJECT
    message["From"] = mail_from
    message["To"] = MAIL_TO
    message.set_content(build_email_body(posts))

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=REQUEST_TIMEOUT) as smtp:
                smtp.login(smtp_user, smtp_pass)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=REQUEST_TIMEOUT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(smtp_user, smtp_pass)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError(f"메일 발송 실패: {exc}") from exc


def main() -> int:
    state = load_state()
    all_new_posts: list[BoardPost] = []
    latest_by_board: dict[str, int] = {}
    errors: list[str] = []

    for board in BOARDS:
        try:
            log(f"게시판 확인 시작: {board['name']} ({board['url']})")
            html = fetch_board_html(board["url"])
            posts = parse_posts(board, html)
            latest = posts[0]
            latest_by_board[board["id"]] = latest.number
            log(
                f"최신 게시글: {board['name']} 번호={latest.number}, 제목={latest.title}, 등록일={latest.date}"
            )

            last_seen_number = get_last_seen_number(state, board["id"])
            if last_seen_number is None:
                set_last_seen_number(state, board, latest.number)
                log(
                    f"첫 확인 게시판입니다. 알림 없이 {board['name']} 최신 번호 {latest.number}만 저장합니다."
                )
                continue

            log(f"마지막 확인 번호: {board['name']} {last_seen_number}")
            new_posts = find_new_posts(posts, last_seen_number)
            if not new_posts:
                log(f"새 게시글이 없습니다: {board['name']}")
                set_last_seen_number(state, board, max(latest.number, last_seen_number))
                continue

            log(f"새 게시글 {len(new_posts)}건 발견: {board['name']}")
            for post in new_posts:
                log(f"  - {post.number} | {post.date} | {post.title} | {post.link}")
            all_new_posts.extend(new_posts)
        except RuntimeError as exc:
            errors.append(str(exc))
            log(f"ERROR: {exc}")

    if all_new_posts:
        send_email(all_new_posts)
        for board in BOARDS:
            latest_number = latest_by_board.get(board["id"])
            if latest_number is not None:
                set_last_seen_number(state, board, latest_number)
        log(f"이메일 발송 완료: {MAIL_TO}")

    save_state(state)

    if errors:
        log("일부 게시판 확인에 실패했습니다.")
        return 1

    log("게시판 확인 완료")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
    except Exception as exc:
        log(f"ERROR: 예상하지 못한 오류가 발생했습니다: {exc}")
        sys.exit(1)
