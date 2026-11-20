#!/usr/bin/env python3
"""取得した外部データから data/*.csv を自動更新し、変更点のレポートを書き出す。

  浦和レッズ … 浦和レッズ公式サイトの日程ページ（J1・ルヴァン・天皇杯）
               → 公式ページの内容でCSVを丸ごと作り直す（公式が正）
  Man Utd    … FotMob の配信カレンダー（CL・カラバオ・FAカップ）
               → 既存CSVの行と日付で突き合わせて、日時・相手・会場・結果を更新／新規追加

使い方: python3 sync_fixtures.py --upstream .upstream --report report.md --errors errors.md
  report.md … 日程（日時・相手・会場）の変更があったときだけ作られる（通知用）
  errors.md … 取得・解析に失敗したときだけ作られる
"""
import argparse
import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
FIELDS = ["id", "date", "date_alt", "time", "round", "home", "away",
          "venue", "result", "status", "note"]
# 通知の対象にする項目（結果だけの変化は通知しない）
SCHEDULE_FIELDS = ("date", "date_alt", "time", "home", "away", "venue", "status")
JST = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
WEEKDAYS = "月火水木金土日"
TBD = {"", "未定", "会場未定", "対戦相手未定"}

URAWA_CATEGORIES = {"league": "urawa_j1", "levain": "urawa_levain",
                    "emperors-cup": "urawa_emperor"}
FOTMOB_COMPETITIONS = {"Champions League": "manutd_ucl",
                       "EFL Cup": "manutd_carabao",
                       "FA Cup": "manutd_facup"}
SINGLE_LEG_CUPS = {"manutd_carabao", "manutd_facup"}  # 負けたら以降の予定を消す


# ---------------------------------------------------------------- 共通
def load_settings() -> dict:
    s = json.loads((ROOT / "calendars.json").read_text(encoding="utf-8"))
    return s if isinstance(s, dict) else {"calendars": s}


def load_names() -> dict:
    p = ROOT / "team_names.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (r.get(k) or "").strip() for k in FIELDS}
                for r in csv.DictReader(f) if (r.get("id") or "").strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["date"], r["time"] or "99:99", r["id"]))


def fmt_when(r: dict) -> str:
    def md(s):
        d = date.fromisoformat(s)
        return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"
    if not r.get("date"):
        return "日付未定"
    s = md(r["date"])
    if r.get("date_alt"):
        s += f" or {md(r['date_alt'])}"
    return s + (f" {r['time']}" if r.get("time") else " 時刻未定")


def card(r: dict) -> str:
    if r["home"] in TBD and r["away"] in TBD:
        return "対戦相手未定"
    return f"{r['home']} vs {r['away']}"


# ---------------------------------------------------------------- 浦和（公式）
def parse_urawa(html: str, names: dict) -> dict[str, list[dict]]:
    from bs4 import BeautifulSoup  # GitHub Actions 上で pip install する

    ja = names.get("ja", {})
    out = {k: [] for k in URAWA_CATEGORIES.values()}
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select("div.filter-item"):
        key = URAWA_CATEGORIES.get(item.get("data-category", ""))
        if not key:
            continue
        tokens = list(item.stripped_strings)
        title = tokens[0]
        if "KICK OFF" not in tokens:
            continue
        k = tokens.index("KICK OFF")
        head, tail = tokens[1:k], tokens[k + 1:]
        side = head[0] if head and head[0] in ("HOME", "AWAY", "NEUTRAL") else "NEUTRAL"
        dates = [t for t in head if re.fullmatch(r"\d{1,2}/\d{1,2}", t)]
        ts = item.get("timestamp", "")
        if not dates or not ts.isdigit():
            continue
        d1 = datetime.fromtimestamp(int(ts), JST).date()
        d2 = None
        if len(dates) > 1:
            m, d = map(int, dates[1].split("/"))
            d2 = date(d1.year + (1 if m < d1.month else 0), m, d)

        kickoff, venue, opponent = (tail + ["", "", ""])[:3]
        result = ""
        if len(tail) > 4 and tail[3] in ("○", "●", "△"):
            score = re.sub(r"\s", "", tail[4])
            if re.fullmatch(r"\d+-\d+", score):
                result = tail[3] + score
        time_s = kickoff if re.fullmatch(r"\d{1,2}:\d{2}", kickoff) else ""
        if time_s and result:  # 終了試合は実際のKO時刻（19:33等）なので15分単位に丸める
            hh, mm = map(int, time_s.split(":"))
            time_s = f"{hh:02d}:{mm - mm % 15:02d}"
        elif time_s:
            hh, mm = map(int, time_s.split(":"))
            time_s = f"{hh:02d}:{mm:02d}"
        notes = [t for t in tail if t.startswith("※")]

        # ラウンド名とID
        if key == "urawa_j1":
            season = re.search(r"(\d{4})/(\d{2})", title)
            n = re.search(r"第(\d+)節", title)
            if not (season and n):
                continue
            rnd = f"第{int(n.group(1))}節"
            rid = f"{season.group(1)}-{season.group(2)}-r{int(n.group(1)):02d}"
        elif key == "urawa_levain":
            season = re.search(r"(\d{4})/(\d{2})", title)
            rnd = re.sub(r"^.*ルヴァンカップ\s*", "", title).replace("プライムラウンド", "").strip()
            rnd = re.sub(r"\s+", " ", rnd)
            prefix = f"{season.group(1)}-{season.group(2)}" if season else "levain"
            rid = f"{prefix}-{rnd.replace(' ', '')}"
        else:
            nth = re.search(r"第(\d+)回", title)
            rnd = re.sub(r"^.*選手権大会\s*", "", title).strip()
            rid = f"{nth.group(1) if nth else 'emperor'}-{rnd.replace(' ', '')}"

        if opponent in TBD:
            home = away = "未定"
            status = "tentative"
            notes.insert(0, "対戦相手未定（勝ち上がった場合）")
        else:
            opp = ja.get(opponent, opponent)
            home, away = ("浦和", opp) if side in ("HOME", "NEUTRAL") else (opp, "浦和")
            status = "confirmed"

        out[key].append({
            "id": rid, "date": d1.isoformat(),
            "date_alt": d2.isoformat() if d2 else "", "time": time_s,
            "round": rnd, "home": home, "away": away,
            "venue": venue or "未定", "result": result, "status": status,
            "note": " ".join(notes),
        })

    if len(out["urawa_j1"]) < 10:
        raise ValueError(f"浦和公式ページからJ1の試合を読み取れませんでした（{len(out['urawa_j1'])}件）。"
                         "ページの構成が変わった可能性があります。")
    return {k: sort_rows(v) for k, v in out.items()}


# ---------------------------------------------------------------- Man Utd（FotMob）
def parse_ics(text: str) -> list[dict]:
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events, cur, depth = [], None, 0
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur, depth = {}, 0
        elif ln == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None:
            if ln.startswith("BEGIN:"):
                depth += 1
            elif ln.startswith("END:"):
                depth -= 1
            elif depth == 0 and ":" in ln:
                k, v = ln.split(":", 1)
                cur[k.split(";")[0]] = v.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n")
    return events


def parse_fotmob(text: str, names: dict) -> dict[str, list[dict]]:
    en = names.get("en", {})
    out = {k: [] for k in FOTMOB_COMPETITIONS.values()}
    events = parse_ics(text)
    if not events:
        raise ValueError("FotMobのカレンダーから試合を読み取れませんでした。配信形式が変わった可能性があります。")
    for ev in events:
        comp = ev.get("DESCRIPTION", "").split("\n")[-1].strip()
        key = FOTMOB_COMPETITIONS.get(comp)
        if not key:
            continue
        m = re.match(r"^(?:\S+\s)?(.+?) - (.+?)(?:\s+\((\d+)-(\d+)\))?\s*$", ev.get("SUMMARY", ""))
        st = ev.get("DTSTART", "")
        if not m or not re.fullmatch(r"\d{8}T\d{6}Z", st):
            continue
        home, away = m.group(1).strip(), m.group(2).strip()
        start = datetime.strptime(st, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(LONDON)
        result = ""
        if m.group(3) is not None:
            h, a = int(m.group(3)), int(m.group(4))
            utd_home = "Manchester United" in home
            us, them = (h, a) if utd_home else (a, h)
            result = f"{'W' if us > them else 'L' if us < them else 'D'} {us}-{them}"
        out[key].append({
            "match_id": ev.get("UID", "").split("-")[0],
            "date": start.date(), "time": start.strftime("%H:%M"),
            "home": en.get(home, home), "away": en.get(away, away),
            "venue": (ev.get("LOCATION") or "").split(",")[0].strip(),
            "result": result,
        })
    return out


def merge_utd(key: str, rows: list[dict], events: list[dict]) -> list[dict]:
    rows = [dict(r) for r in rows]
    used = set()
    for ev in sorted(events, key=lambda e: e["date"]):
        best, best_score = None, None
        for i, r in enumerate(rows):
            if i in used or not r["date"]:
                continue
            diff = abs((date.fromisoformat(r["date"]) - ev["date"]).days)
            if diff > 5:
                continue
            score = (diff, r["home"] in TBD)  # 日付が近い行・確定済みの行を優先
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is None:
            rows.append({k: "" for k in FIELDS} | {
                "id": f"fm{ev['match_id']}", "status": "confirmed"})
            best = len(rows) - 1
        used.add(best)
        r = rows[best]
        r["date"], r["date_alt"], r["time"] = ev["date"].isoformat(), "", ev["time"]
        if r["home"] in TBD or r["away"] in TBD:
            r["home"], r["away"] = ev["home"], ev["away"]
            r["note"] = ""
        if r["venue"] in TBD and ev["venue"]:
            r["venue"] = ev["venue"]
        if ev["result"]:
            r["result"] = ev["result"]
        r["status"] = "confirmed"

    rows = sort_rows(rows)
    if key in SINGLE_LEG_CUPS:  # 1試合制のカップ戦で負けたら、以降の「勝ち上がった場合」の予定を消す
        lost = [r["date"] for r in rows if r["result"].startswith("L")]
        if lost:
            rows = [r for r in rows if not (r["date"] > max(lost) and r["home"] in TBD)]
    return rows


# ---------------------------------------------------------------- 差分レポート
def diff_report(label: str, old: list[dict], new: list[dict]) -> list[str]:
    o = {r["id"]: r for r in old}
    n = {r["id"]: r for r in new}
    lines = []
    for rid, r in n.items():
        name = f"【{label}{' ' + r['round'] if r['round'] else ''}】"
        if rid not in o:
            lines.append(f"- 🆕 {name}{card(r)}　{fmt_when(r)}　{r['venue']}")
            continue
        p = o[rid]
        changed = [f for f in SCHEDULE_FIELDS if p.get(f, "") != r.get(f, "")]
        if not changed:
            continue
        parts = []
        if {"date", "date_alt", "time"} & set(changed):
            parts.append(f"日時 {fmt_when(p)} → **{fmt_when(r)}**")
        if {"home", "away"} & set(changed):
            parts.append(f"対戦 {card(p)} → **{card(r)}**")
        if "venue" in changed:
            parts.append(f"会場 {p['venue']} → **{r['venue']}**")
        if not parts and "status" in changed:
            parts.append("確定")
        lines.append(f"- ✏️ {name}{card(r)}　" + "、".join(parts))
    for rid, p in o.items():
        if rid not in n:
            name = f"【{label}{' ' + p['round'] if p['round'] else ''}】"
            lines.append(f"- 🗑️ {name}{card(p)}　{fmt_when(p)}（日程から削除）")
    return lines


# ---------------------------------------------------------------- main
def read_upstream(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError("データをダウンロードできませんでした（サイトが一時的に応答しなかった可能性があります）。")
    return path.read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default=".upstream")
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--errors", default="errors.md")
    args = ap.parse_args()
    up = Path(args.upstream)

    settings = load_settings()
    cals = {c["key"]: c for c in settings["calendars"]}
    names = load_names()
    new_data: dict[str, list[dict]] = {}
    errors: list[str] = []

    try:
        html = read_upstream(up / "urawa_official_game.html")
        new_data.update(parse_urawa(html, names))
    except Exception as e:  # noqa: BLE001
        errors.append(f"- 浦和レッズ公式の日程ページ: {e}")

    try:
        text = read_upstream(up / "fotmob_manutd.ics")
        for key, events in parse_fotmob(text, names).items():
            if key in cals:
                new_data[key] = merge_utd(key, read_csv(ROOT / cals[key]["csv"]), events)
    except Exception as e:  # noqa: BLE001
        errors.append(f"- Man Utd（FotMob）: {e}")

    report: list[str] = []
    for key, rows in new_data.items():
        if key not in cals:
            continue
        path = ROOT / cals[key]["csv"]
        old = read_csv(path)
        if old == rows:
            continue
        write_csv(path, rows)
        lines = diff_report(cals[key]["label"], old, rows)
        print(f"{key}: 更新（日程の変更 {len(lines)}件）")
        if lines:
            report += [f"### {cals[key]['name']}", *lines, ""]

    if report:
        Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
        print("\n".join(report))
    if errors:
        Path(args.errors).write_text("\n".join(errors) + "\n", encoding="utf-8")
        print("\n".join(errors))


if __name__ == "__main__":
    main()
