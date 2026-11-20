#!/usr/bin/env python3
"""CSVの試合日程から、iPhoneカレンダーで購読できる .ics を生成する。

使い方:  python3 build_ics.py
入力:    calendars.json と data/*.csv
出力:    docs/<key>.ics（GitHub Pagesでそのまま公開できる）

CSVの列:
  id        … 試合ごとの一意なID（変えなければ、日時を直しても同じ予定として上書きされる）
  date      … 試合日 YYYY-MM-DD
  date_alt  … 「土 or 日」のように日付未確定のときの2日目（任意）
  time      … キックオフ HH:MM（現地時間）。空欄なら「時刻未定」の終日予定になる
  round     … 節・ラウンド名
  home/away … チーム名（短縮名でOK）
  venue     … 会場
  result    … 結果（任意。例: ○3-2 / W 4-0）
  status    … confirmed（確定）/ tentative（勝ち上がった場合など）
  note      … 備考（任意）
"""
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
UID_DOMAIN = "football-calendar.local"
WEEKDAYS = "月火水木金土日"


def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> str:
    """RFC 5545: 1行75オクテットで折り返す（UTF-8の文字途中では切らない）。"""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not out else 74  # 継続行は先頭スペース分を引く
        if size + n > limit:
            out.append(cur)
            cur, size = ch, n
        else:
            cur += ch
            size += n
    out.append(cur)
    return "\r\n ".join(out)


def md(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def build_event(cfg: dict, row: dict, stamp: str) -> list[str]:
    tz = ZoneInfo(cfg["tz"])
    d1 = date.fromisoformat(row["date"])
    d2 = date.fromisoformat(row["date_alt"]) if row.get("date_alt") else None
    time_s = (row.get("time") or "").strip()
    tentative = row.get("status", "confirmed").strip() == "tentative"
    home, away = row["home"].strip(), row["away"].strip()
    result = (row.get("result") or "").strip()

    if home == "未定" and away == "未定":
        card = "浦和" if cfg["key"].startswith("urawa") else "Man Utd"
    else:
        card = f"{home} vs {away}"

    title = f"【{cfg['label']} {row['round']}】{card}"
    if result:
        title += f" {result}"
    if d2:
        title += f"（{md(d1)} or {md(d2)}）"
    elif not time_s:
        title += "（時刻未定）"
    if tentative:
        title += " ※勝ち上がった場合"

    desc = [f"大会: {cfg['name']}", f"ラウンド: {row['round']}",
            f"対戦: {home} vs {away}", f"会場: {row['venue']}"]
    if time_s:
        desc.append(f"キックオフ: {time_s}（{cfg['tz_label']}）")
    else:
        desc.append("キックオフ: 未定")
    if d2:
        desc.append(f"開催日: {md(d1)} または {md(d2)}（確定後に更新）")
    if result:
        desc.append(f"結果: {result}")
    if row.get("note"):
        desc.append(f"備考: {row['note']}")

    lines = ["BEGIN:VEVENT",
             f"UID:{cfg['key']}-{row['id']}@{UID_DOMAIN}",
             f"DTSTAMP:{stamp}"]
    if time_s and not d2:
        hh, mm = map(int, time_s.split(":"))
        start = datetime(d1.year, d1.month, d1.day, hh, mm, tzinfo=tz)
        end = start + timedelta(minutes=cfg.get("duration_min", 120))
        fmt = "%Y%m%dT%H%M%SZ"
        lines += [f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}",
                  f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}"]
    else:
        last = d2 or d1
        lines += [f"DTSTART;VALUE=DATE:{d1.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(last + timedelta(days=1)).strftime('%Y%m%d')}",
                  "TRANSP:TRANSPARENT"]
    lines += [f"SUMMARY:{esc(title)}",
              f"LOCATION:{esc(row['venue'])}",
              f"DESCRIPTION:{esc(chr(10).join(desc))}",
              f"STATUS:{'TENTATIVE' if tentative else 'CONFIRMED'}",
              "END:VEVENT"]
    return lines


def build_calendar(cfg: dict) -> tuple[str, int]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with open(ROOT / cfg["csv"], encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("id", "").strip()]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//football-calendar//JA", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH",
             f"X-WR-CALNAME:{esc(cfg['name'])}",
             "X-WR-TIMEZONE:Asia/Tokyo",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
             "X-PUBLISHED-TTL:PT6H"]
    for row in rows:
        lines += build_event(cfg, row, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n", len(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    configs = json.loads((ROOT / "calendars.json").read_text(encoding="utf-8"))
    for cfg in configs:
        text, n = build_calendar(cfg)
        (OUT / f"{cfg['key']}.ics").write_text(text, encoding="utf-8", newline="")
        print(f"{cfg['key']}.ics: {n}試合")


if __name__ == "__main__":
    main()
