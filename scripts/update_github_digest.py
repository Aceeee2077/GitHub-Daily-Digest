from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo

    BEIJING = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - fallback for Python without tzdata
    BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "github-history.json"
REPORT_PATH = ROOT / "report.html"
DOCS_PATH = ROOT / "docs" / "index.html"
API_BASE = "https://api.github.com"

DEFAULT_USER = "Aceeee2077"
USER = (os.environ.get("GH_USER") or "").strip() or DEFAULT_USER
TOKEN = (os.environ.get("GH_TOKEN") or "").strip()


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def bj_time(value: str | None) -> str:
    dt = parse_iso(value)
    if not dt:
        return "时间未知"
    return dt.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")


def api_get(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-daily-digest/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = Request(API_BASE + path, headers=headers)
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else None


def github_repo_url(name: str) -> str:
    return f"https://github.com/{name}"


def fetch_profile() -> dict[str, Any]:
    try:
        data = api_get(f"/users/{quote(USER)}")
        return data if isinstance(data, dict) else {}
    except (HTTPError, URLError, ValueError) as exc:
        print(f"Warning: cannot fetch profile for {USER}: {exc}", file=sys.stderr)
        return {}


def fetch_events(since: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for page in range(1, 11):
        try:
            page_data = api_get(f"/users/{quote(USER)}/events?per_page=100&page={page}")
        except (HTTPError, URLError, ValueError) as exc:
            print(f"Error: cannot fetch GitHub events: {exc}", file=sys.stderr)
            raise
        if not isinstance(page_data, list) or not page_data:
            break
        events.extend(page_data)
        if len(page_data) < 100:
            break
        last_time = parse_iso(page_data[-1].get("created_at"))
        if last_time is None or last_time < since:
            break
    return events


def fetch_repo_details(name: str) -> dict[str, Any]:
    if not name or "/" not in name:
        return {}
    try:
        data = api_get(f"/repos/{quote(name, safe='/')}")
        return data if isinstance(data, dict) else {}
    except (HTTPError, URLError, ValueError):
        return {}


def fetch_push_stats(
    repo_name: str, before: str | None, head: str | None
) -> tuple[int, str]:
    if (
        not repo_name
        or "/" not in repo_name
        or not before
        or not head
        or before == head
        or set(before) == {"0"}
        or set(head) == {"0"}
    ):
        return 1, ""

    try:
        data = api_get(
            f"/repos/{quote(repo_name, safe='/')}/compare/{before}...{head}"
        )
    except (HTTPError, URLError, ValueError):
        return 1, ""

    if not isinstance(data, dict):
        return 1, ""

    commits = data.get("commits")
    if not isinstance(commits, list):
        commits = []
    try:
        total = int(data.get("total_commits") or len(commits) or 1)
    except (TypeError, ValueError):
        total = len(commits) or 1

    authored = [
        item
        for item in commits
        if (
            str(((item.get("author") or {}).get("login") or "")).lower()
            == USER.lower()
            or str(((item.get("committer") or {}).get("login") or "")).lower()
            == USER.lower()
        )
    ]
    count = len(authored) if authored else total
    message = (
        first_line(commits[0].get("commit", {}).get("message"))
        if commits
        else ""
    )
    return max(count, 1), message


def first_line(text: Any, limit: int = 120) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    line = cleaned.splitlines()[0].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def action_verb(action: str | None) -> str:
    labels = {
        "opened": "创建",
        "closed": "关闭",
        "reopened": "重新打开",
        "merged": "合并",
        "created": "创建",
        "deleted": "删除",
        "edited": "编辑",
        "assigned": "指派",
        "unassigned": "取消指派",
        "labeled": "添加标签",
        "unlabeled": "移除标签",
        "milestoned": "设置里程碑",
        "demilestoned": "移除里程碑",
        "renamed": "重命名",
        "transferred": "转移",
        "synchronize": "同步",
        "review_requested": "请求评审",
        "review_request_removed": "取消评审请求",
        "published": "发布",
        "unpublished": "取消发布",
    }
    return labels.get(action or "", action or "动态")


def classify_events(
    events: list[dict[str, Any]], since: datetime
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    watched: list[dict[str, Any]] = []
    pushes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    pull_requests: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []

    for event in events:
        created = parse_iso(event.get("created_at"))
        if created is None or created < since:
            continue

        event_type = event.get("type") or ""
        payload = event.get("payload") or {}
        repo = event.get("repo") or {}
        repo_name = repo.get("name") or ""

        if event_type == "WatchEvent":
            detail = fetch_repo_details(repo_name)
            watched.append(
                {
                    "repo": repo_name,
                    "name": repo_name,
                    "html_url": detail.get("html_url") or github_repo_url(repo_name),
                    "description": first_line(detail.get("description"), 160),
                    "language": detail.get("language") or "",
                    "starred_at": event.get("created_at"),
                }
            )

        elif event_type == "PushEvent":
            commit_count, message = fetch_push_stats(
                repo_name,
                payload.get("before"),
                payload.get("head"),
            )
            pushes.append(
                {
                    "repo": repo_name,
                    "html_url": github_repo_url(repo_name),
                    "message": message or "推送了代码",
                    "commit_count": commit_count,
                    "created_at": event.get("created_at"),
                }
            )

        elif event_type == "IssuesEvent":
            issue = payload.get("issue") or {}
            issues.append(
                {
                    "repo": repo_name,
                    "html_url": issue.get("html_url") or "",
                    "number": issue.get("number"),
                    "title": first_line(issue.get("title"), 120),
                    "action": payload.get("action") or "",
                    "created_at": event.get("created_at"),
                }
            )

        elif event_type == "PullRequestEvent":
            pr = payload.get("pull_request") or {}
            action = payload.get("action") or ""
            if action == "closed" and pr.get("merged"):
                action = "merged"
            pull_requests.append(
                {
                    "repo": repo_name,
                    "html_url": pr.get("html_url") or "",
                    "number": pr.get("number"),
                    "title": first_line(pr.get("title"), 120),
                    "action": action,
                    "created_at": event.get("created_at"),
                }
            )

        elif event_type == "IssueCommentEvent":
            issue = payload.get("issue") or {}
            comment = payload.get("comment") or {}
            is_pull = bool(issue.get("pull_request"))
            comments.append(
                {
                    "repo": repo_name,
                    "html_url": comment.get("html_url") or issue.get("html_url") or "",
                    "number": issue.get("number"),
                    "title": first_line(issue.get("title"), 100),
                    "kind": "PR" if is_pull else "Issue",
                    "action": payload.get("action") or "created",
                    "created_at": event.get("created_at"),
                }
            )

        elif event_type in {"CreateEvent", "DeleteEvent", "ReleaseEvent", "ForkEvent"}:
            action = payload.get("action") or ""
            title = ""
            link = ""
            if event_type == "CreateEvent":
                ref_type = payload.get("ref_type") or ""
                ref = payload.get("ref") or ""
                title = f"创建了{ref_type} {ref}".strip()
                link = github_repo_url(repo_name)
            elif event_type == "DeleteEvent":
                ref_type = payload.get("ref_type") or ""
                ref = payload.get("ref") or ""
                title = f"删除了{ref_type} {ref}".strip()
                link = github_repo_url(repo_name)
            elif event_type == "ReleaseEvent":
                release = payload.get("release") or {}
                title = "发布了版本 " + first_line(
                    release.get("tag_name") or release.get("name") or "", 80
                )
                link = release.get("html_url") or github_repo_url(repo_name)
            elif event_type == "ForkEvent":
                forkee = payload.get("forkee") or {}
                title = "Fork 了仓库"
                link = forkee.get("html_url") or github_repo_url(repo_name)
            if title:
                others.append(
                    {
                        "repo": repo_name,
                        "html_url": link,
                        "title": title,
                        "action": action_verb(action or event_type.replace("Event", "")),
                        "created_at": event.get("created_at"),
                    }
                )

    return watched, pushes, issues, pull_requests, comments, others


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history: list[dict[str, Any]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_history_table(history: list[dict[str, Any]]) -> str:
    if not history:
        return '<p class="empty">暂无历史记录。</p>'

    rows = []
    for day in reversed(history[-30:]):
        rows.append(
            "<tr>"
            f"<td>{esc(day.get('date', ''))}</td>"
            f"<td>{esc(day.get('stars', 0))}</td>"
            f"<td>{esc(day.get('commits_pushed', 0))}</td>"
            f"<td>{esc(day.get('issues', 0))}</td>"
            f"<td>{esc(day.get('pull_requests', 0))}</td>"
            f"<td>{esc(day.get('comments', 0))}</td>"
            f"<td>{esc(day.get('other', 0))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table>'
        "<thead><tr><th>日期</th><th>Star</th><th>推送提交</th>"
        "<th>Issue</th><th>PR</th><th>评论</th><th>其他</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_section(
    title: str, subtitle: str, items: list[dict[str, Any]], empty_text: str
) -> str:
    if not items:
        return (
            f'<section class="day"><div class="day-title"><h2>{esc(title)}</h2>'
            f"<p>{esc(subtitle)}</p></div><p class=\"empty\">{esc(empty_text)}</p></section>"
        )

    rows = []
    for item in items:
        kind = item.get("kind", "")
        number = item.get("number")
        number_text = f" #{number}" if number is not None else ""
        title_text = item.get("title") or item.get("message") or ""
        repo_label = item.get("repo") or item.get("name") or ""
        meta_parts: list[str] = []
        if item.get("action"):
            meta_parts.append(action_verb(item.get("action")))
        if kind:
            meta_parts.append(kind)
        if item.get("language"):
            meta_parts.append(item.get("language"))
        if item.get("commit_count"):
            meta_parts.append(f"{item['commit_count']} 次提交")

        meta = ""
        if meta_parts:
            meta = (
                '<span class="event-meta">'
                + " · ".join(esc(part) for part in meta_parts)
                + "</span>"
            )

        desc = ""
        if item.get("description"):
            desc = f'<p class="desc">{esc(item["description"])}</p>'

        title_html = f'<p class="title">{esc(title_text)}</p>' if title_text else ""
        rows.append(
            '<li class="event">'
            '<div class="event-top">'
            f'<a href="{esc(item.get("html_url") or github_repo_url(repo_label))}" rel="noreferrer">'
            f"{esc(repo_label)}{esc(number_text)}{meta}</a>"
            f'<time>{esc(bj_time(item.get("created_at") or item.get("starred_at")))}</time>'
            "</div>"
            + title_html
            + desc
            + "</li>"
        )

    return (
        f'<section class="day"><div class="day-title"><h2>{esc(title)}</h2>'
        f"<p>{esc(subtitle)}</p></div><ul class=\"event-list\">{''.join(rows)}</ul></section>"
    )


def render_report(
    login: str,
    display_name: str,
    start: datetime,
    since: datetime,
    counts: dict[str, int],
    watched: list[dict[str, Any]],
    pushes: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    pull_requests: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    others: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> str:
    window_label = (
        f"{since.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M')} 至 "
        f"{start.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M')}（北京时间）"
    )
    generated = start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    profile_label = display_name or login

    issue_pr_total = counts["issues"] + counts["pull_requests"] + counts["comments"]

    cards = (
        f"<article><span>新增 Star</span><strong>{counts['stars']}</strong>"
        f"<small>过去 24 小时</small></article>"
        f"<article><span>推送提交</span><strong>{counts['commits_pushed']}</strong>"
        f"<small>共 {counts['pushes']} 次推送</small></article>"
        f"<article><span>Issue / PR 动态</span><strong>{issue_pr_total}</strong>"
        f"<small>Issue {counts['issues']} · PR {counts['pull_requests']} · 评论 {counts['comments']}</small></article>"
        f"<article><span>历史记录</span><strong>{len(history)} 天</strong>"
        "<small>每日自动更新</small></article>"
    )

    activity_items = sorted(
        issues + pull_requests + comments,
        key=lambda item: parse_iso(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    sections = [
        render_section(
            "新 Star 的仓库",
            f"共 {counts['stars']} 个",
            watched,
            "过去 24 小时没有新的 Star。",
        ),
        render_section(
            "最近推送",
            f"共 {counts['pushes']} 次推送，{counts['commits_pushed']} 次提交",
            pushes,
            "过去 24 小时没有公开推送。",
        ),
        render_section(
            "Issue / PR 动态",
            f"Issue {counts['issues']} · PR {counts['pull_requests']} · 评论 {counts['comments']}",
            activity_items,
            "过去 24 小时没有 Issue / PR 动态。",
        ),
        render_section(
            "其他动态",
            f"共 {counts['other']} 条",
            others,
            "没有其他值得关注的动态。",
        ),
    ]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GitHub 动态日报 · {esc(login)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #1d4ed8;
      --soft: #eef2ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background: var(--bg);
    }}
    header {{
      padding: 36px min(5vw, 56px) 24px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    h1, h2, p {{ margin: 0; }}
    h1 {{ font-size: clamp(28px, 4vw, 46px); font-weight: 720; }}
    header p {{ margin-top: 10px; color: var(--muted); line-height: 1.7; }}
    main {{ width: min(1180px, calc(100% - 28px)); margin: 24px auto 48px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    article, .day, details {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    article {{ padding: 16px; }}
    article span, article small {{ display: block; color: var(--muted); }}
    article strong {{ display: block; margin: 10px 0 6px; font-size: 28px; line-height: 1.2; }}
    .day {{ margin-top: 16px; overflow: hidden; }}
    .day-title {{ padding: 18px 18px 14px; border-bottom: 1px solid var(--line); }}
    .day-title h2 {{ font-size: 22px; }}
    .day-title p {{ margin-top: 6px; color: var(--muted); }}
    .event-list {{ list-style: none; margin: 0; padding: 0; }}
    .event {{ padding: 14px 18px; border-bottom: 1px solid var(--line); }}
    .event:last-child {{ border-bottom: 0; }}
    .event-top {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; flex-wrap: wrap; }}
    .event-top a {{ color: var(--accent); font-weight: 600; text-decoration: none; }}
    .event-top a:hover {{ text-decoration: underline; }}
    .event-meta {{ color: var(--muted); font-weight: 400; font-size: 13px; }}
    .event time {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .event .title {{ margin-top: 6px; font-weight: 650; overflow-wrap: anywhere; }}
    .event .desc {{ margin-top: 4px; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }}
    .empty {{ padding: 18px; color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 640px; }}
    th, td {{ padding: 11px 14px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }}
    th {{ color: var(--muted); font-size: 13px; font-weight: 650; background: #fbfcfe; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--accent); }}
    @media (max-width: 760px) {{
      header {{ padding: 28px 16px 20px; }}
      main {{ width: calc(100% - 20px); margin-top: 14px; }}
      article strong {{ font-size: 24px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>GitHub 动态日报</h1>
    <p><a href="https://github.com/{esc(login)}" rel="noreferrer">@{esc(login)}</a>（{esc(profile_label)}）
    的公开动态汇总，数据窗口：{esc(window_label)}。页面生成于北京时间 {esc(generated)}。</p>
  </header>
  <main>
    <div class="cards">{cards}</div>
    {''.join(sections)}
    <section class="day">
      <div class="day-title"><h2>历史概览</h2><p>最近 30 天汇总</p></div>
      {render_history_table(history)}
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    start = datetime.now(timezone.utc)
    since = start - timedelta(hours=24)

    profile = fetch_profile()
    try:
        events = fetch_events(since)
    except (HTTPError, URLError, ValueError) as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        return 1

    watched, pushes, issues, pull_requests, comments, others = classify_events(
        events, since
    )

    counts = {
        "stars": len(watched),
        "pushes": len(pushes),
        "commits_pushed": sum(item["commit_count"] for item in pushes),
        "issues": len(issues),
        "pull_requests": len(pull_requests),
        "comments": len(comments),
        "other": len(others),
    }

    record = {
        "date": start.astimezone(BEIJING).strftime("%Y-%m-%d"),
        "generated_at": start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "window_start": since.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "window_end": start.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        **counts,
    }

    history = load_history()
    history = [item for item in history if item.get("date") != record["date"]]
    history.append(record)
    history.sort(key=lambda item: str(item.get("date", "")))

    save_history(history)
    html_text = render_report(
        login=profile.get("login") or USER,
        display_name=profile.get("name") or "",
        start=start,
        since=since,
        counts=counts,
        watched=watched,
        pushes=pushes,
        issues=issues,
        pull_requests=pull_requests,
        comments=comments,
        others=others,
        history=history,
    )
    REPORT_PATH.write_text(html_text, encoding="utf-8")
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(html_text, encoding="utf-8")

    print(f"Updated {REPORT_PATH}")
    print(f"Updated {DOCS_PATH}")
    print(
        "Summary: "
        f"{counts['stars']} stars, {counts['pushes']} pushes "
        f"({counts['commits_pushed']} commits), {counts['issues']} issues, "
        f"{counts['pull_requests']} PRs, {counts['comments']} comments, "
        f"{counts['other']} others"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
