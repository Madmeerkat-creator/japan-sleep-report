"""
v3 일본인 수면 만족도 분석 스크립트
- sleepStartAt/sleepEndAt 기준 취침/기상 시각 계산
- 모든 중간 결과를 CSV/MD 파일로 보존
"""

import json
import csv
import math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

from config import (
    ACTIVITY_LABELS_KR,
    MOOD_LABELS_KR,
    WEEKDAY_MAP,
    WEEKDAY_ORDER,
)

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path.home() / "Desktop/Project/claude/dataset/sleeps/monthly_enriched"
USER_LANG_PATH = Path.home() / "Desktop/Project/claude/dataset/users/sleep_uid_lang.csv"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MONTHS = [
    "2024_11", "2024_12",
    "2025_01", "2025_02", "2025_03", "2025_04", "2025_05", "2025_06",
    "2025_07", "2025_08", "2025_09", "2025_10", "2025_11", "2025_12",
    "2026_01", "2026_02",
]

MIN_SLEEP_SECONDS = 3600


# ── Utility Functions ──

def load_user_lang():
    """userId -> lang 매핑 로드."""
    lang_map = {}
    with open(USER_LANG_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lang_map[row["userId"]] = row["lang"]
    return lang_map


def utc_to_local_hour(utc_str, tz_name):
    """UTC ISO 문자열 → 로컬 시각(시간 float, 예: 1.5 = 1:30)."""
    if not utc_str or not tz_name:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo(tz_name))
        return local.hour + local.minute / 60
    except Exception:
        return None


def normalize_bedtime(hour_float):
    """취침 시각 정규화: 0~4시는 +24로 변환 (연속 평균 계산용)."""
    if hour_float is None:
        return None
    if hour_float < 12:
        return hour_float + 24
    return hour_float


def denormalize_bedtime(norm_hour):
    """정규화된 취침 시각 → 실제 시각으로 복원."""
    if norm_hour >= 24:
        return norm_hour - 24
    return norm_hour


def hour_to_hhmm(h):
    """시간 float → HH:MM 문자열."""
    hh = int(h) % 24
    mm = round((h - int(h)) * 60)
    if mm == 60:
        hh += 1
        mm = 0
    return f"{hh}:{mm:02d}"


def hour_to_display(h):
    """시간 float → '오전/오후 H:MM' 형식."""
    hh = int(h) % 24
    mm = round((h - int(h)) * 60)
    if mm == 60:
        hh += 1
        mm = 0
    period = "오전" if hh < 12 else "오후"
    display_h = hh if hh <= 12 else hh - 12
    if hh == 0:
        display_h = 0
    return f"오전 {hh}:{mm:02d}" if hh < 12 else f"오후 {hh - 12}:{mm:02d}"


def minutes_to_hm(minutes):
    """분 → 'Xh Ym' 또는 'X시간 Y분'."""
    h = int(minutes // 60)
    m = int(round(minutes % 60))
    return f"{h}시간 {m}분"


def write_csv(path, rows, fieldnames):
    """CSV 파일 저장."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_md(path, content):
    """MD 파일 저장."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ── Phase 1: Data Load + Filter ──

def load_and_filter():
    """16개월 JSON 로드, 필드 추출, ja 필터링."""
    lang_map = load_user_lang()
    print(f"[Phase 1] 유저 언어 매핑 로드: {len(lang_map):,}명")

    all_records = []
    ja_records = []
    non_ja_records = []
    monthly_stats = []

    for month in MONTHS:
        path = DATA_DIR / f"{month}.json"
        with open(path, "r") as f:
            data = json.load(f)

        month_total = 0
        month_ja = 0

        for rec in data:
            sleep = rec.get("sleep", {})
            seconds = sleep.get("seconds", 0)
            if not seconds or seconds < MIN_SLEEP_SECONDS:
                continue

            user_id = rec.get("userId", "")
            tz = rec.get("timezone", "")
            date = rec.get("date", "")
            rating = rec.get("rating")
            onboarding = rec.get("sleepOnboarding", {}) or {}
            activities = onboarding.get("activities", []) or []
            moods = onboarding.get("moods", []) or []

            sleep_start = sleep.get("sleepStartAt", "")
            sleep_end = sleep.get("sleepEndAt", "")

            bedtime_hour = utc_to_local_hour(sleep_start, tz)
            waketime_hour = utc_to_local_hour(sleep_end, tz)

            record = {
                "userId": user_id,
                "date": date,
                "timezone": tz,
                "seconds": seconds,
                "sleepStartAt": sleep_start,
                "sleepEndAt": sleep_end,
                "bedtime_hour": bedtime_hour,
                "waketime_hour": waketime_hour,
                "rating": rating,
                "activities": activities,
                "moods": moods,
            }

            month_total += 1
            lang = lang_map.get(user_id, "unknown")

            all_records.append(record)

            if lang == "ja":
                month_ja += 1
                ja_records.append(record)
            else:
                non_ja_records.append(record)

        monthly_stats.append({
            "month": month,
            "total": month_total,
            "japan": month_ja,
        })
        print(f"  {month}: total={month_total:,}, ja={month_ja:,}")

    # Save step-01
    csv_rows = [{"month": s["month"], "total_records": s["total"], "japan_records": s["japan"]} for s in monthly_stats]
    write_csv(OUTPUT_DIR / "step-01_data-overview.csv", csv_rows, ["month", "total_records", "japan_records"])

    total_all = sum(s["total"] for s in monthly_stats)
    total_ja = sum(s["japan"] for s in monthly_stats)
    all_users = len(set(r["userId"] for r in all_records))
    ja_users = len(set(r["userId"] for r in ja_records))

    md = f"""# Step 01: 데이터 개요

## 기간
2024년 11월 ~ 2026년 2월 (16개월)

## 전체 통계
- 전체 수면 기록 (≥1h): **{total_all:,}건**
- 전체 유저 수: **{all_users:,}명**
- 일본 수면 기록: **{total_ja:,}건** ({total_ja/total_all*100:.1f}%)
- 일본 유저 수: **{ja_users:,}명**

## 월별 breakdown
| 월 | 전체 건수 | 일본 건수 |
|----|----------|----------|
"""
    for s in monthly_stats:
        md += f"| {s['month']} | {s['total']:,} | {s['japan']:,} |\n"

    write_md(OUTPUT_DIR / "step-01_data-overview.md", md)
    print(f"\n[Phase 1 완료] 전체={total_all:,}, 일본={total_ja:,}, 일본 유저={ja_users:,}")

    return all_records, ja_records, non_ja_records


# ── Phase 2: Japan Basic Stats ──

def compute_basic_stats(all_records, ja_records, non_ja_records):
    """전체/일본 기초 통계 계산."""
    print("\n[Phase 2] 기초 통계 계산...")

    def calc_stats(records, label):
        durations = [r["seconds"] / 3600 for r in records]
        bedtimes_norm = [normalize_bedtime(r["bedtime_hour"]) for r in records if r["bedtime_hour"] is not None]
        waketimes = [r["waketime_hour"] for r in records if r["waketime_hour"] is not None]
        ratings = [r["rating"] for r in records if r["rating"] is not None]
        rated_count = len(ratings)

        avg_dur_h = sum(durations) / len(durations) if durations else 0
        avg_bed_norm = sum(bedtimes_norm) / len(bedtimes_norm) if bedtimes_norm else 0
        avg_bed = denormalize_bedtime(avg_bed_norm)
        avg_wake = sum(waketimes) / len(waketimes) if waketimes else 0
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        avg_rating_10 = avg_rating * 2

        return {
            "label": label,
            "count": len(records),
            "users": len(set(r["userId"] for r in records)),
            "avg_duration_h": avg_dur_h,
            "avg_duration_min": avg_dur_h * 60,
            "avg_bedtime": avg_bed,
            "avg_waketime": avg_wake,
            "avg_rating_5": avg_rating,
            "avg_rating_10": avg_rating_10,
            "rated_count": rated_count,
        }

    all_stats = calc_stats(all_records, "전체")
    ja_stats = calc_stats(ja_records, "일본")
    non_ja_stats = calc_stats(non_ja_records, "일본 외")

    # Save step-02 CSV
    csv_rows = []
    for s in [all_stats, ja_stats, non_ja_stats]:
        csv_rows.append({
            "group": s["label"],
            "records": s["count"],
            "users": s["users"],
            "avg_sleep_hours": round(s["avg_duration_h"], 3),
            "avg_sleep_minutes": round(s["avg_duration_min"], 1),
            "avg_bedtime": hour_to_hhmm(s["avg_bedtime"]),
            "avg_waketime": hour_to_hhmm(s["avg_waketime"]),
            "avg_rating_10": round(s["avg_rating_10"], 2),
            "rated_count": s["rated_count"],
        })
    write_csv(
        OUTPUT_DIR / "step-02_japan-filtered-stats.csv",
        csv_rows,
        ["group", "records", "users", "avg_sleep_hours", "avg_sleep_minutes",
         "avg_bedtime", "avg_waketime", "avg_rating_10", "rated_count"],
    )

    dur_diff = ja_stats["avg_duration_min"] - non_ja_stats["avg_duration_min"]
    bed_diff = (normalize_bedtime(ja_stats["avg_bedtime"]) - normalize_bedtime(non_ja_stats["avg_bedtime"])) * 60
    wake_diff = (ja_stats["avg_waketime"] - non_ja_stats["avg_waketime"]) * 60
    rat_diff = ja_stats["avg_rating_10"] - non_ja_stats["avg_rating_10"]

    md = f"""# Step 02: 일본 필터 후 기초 통계

## 일본 외 vs 일본 비교

| 항목 | 일본 외 | 일본 | 차이 |
|------|---------|------|------|
| 수면 기록 | {non_ja_stats['count']:,}건 | {ja_stats['count']:,}건 | - |
| 유저 수 | {non_ja_stats['users']:,}명 | {ja_stats['users']:,}명 | - |
| 평균 수면 시간 | {minutes_to_hm(non_ja_stats['avg_duration_min'])} | {minutes_to_hm(ja_stats['avg_duration_min'])} | {dur_diff:+.0f}분 |
| 평균 취침 시각 | {hour_to_hhmm(non_ja_stats['avg_bedtime'])} | {hour_to_hhmm(ja_stats['avg_bedtime'])} | {bed_diff:+.0f}분 |
| 평균 기상 시각 | {hour_to_hhmm(non_ja_stats['avg_waketime'])} | {hour_to_hhmm(ja_stats['avg_waketime'])} | {wake_diff:+.0f}분 |
| 수면 만족도 (10점) | {non_ja_stats['avg_rating_10']:.2f} | {ja_stats['avg_rating_10']:.2f} | {rat_diff:+.2f} |
| 만족도 기록 건수 | {non_ja_stats['rated_count']:,}건 | {ja_stats['rated_count']:,}건 | - |
"""
    write_md(OUTPUT_DIR / "step-02_japan-filtered-stats.md", md)

    print(f"  전체: {all_stats['count']:,}건, 수면={minutes_to_hm(all_stats['avg_duration_min'])}, "
          f"취침={hour_to_hhmm(all_stats['avg_bedtime'])}, 기상={hour_to_hhmm(all_stats['avg_waketime'])}, "
          f"만족도={all_stats['avg_rating_10']:.2f}")
    print(f"  일본: {ja_stats['count']:,}건, 수면={minutes_to_hm(ja_stats['avg_duration_min'])}, "
          f"취침={hour_to_hhmm(ja_stats['avg_bedtime'])}, 기상={hour_to_hhmm(ja_stats['avg_waketime'])}, "
          f"만족도={ja_stats['avg_rating_10']:.2f}")
    print(f"  일본 외: {non_ja_stats['count']:,}건, 수면={minutes_to_hm(non_ja_stats['avg_duration_min'])}, "
          f"취침={hour_to_hhmm(non_ja_stats['avg_bedtime'])}, 기상={hour_to_hhmm(non_ja_stats['avg_waketime'])}, "
          f"만족도={non_ja_stats['avg_rating_10']:.2f}")

    return all_stats, ja_stats, non_ja_stats


# ── Phase 3: Section Analyses ──

def section1_comparison(non_ja_stats, ja_stats):
    """Section 1: 일본 외 vs 일본 비교 CSV."""
    rows = []
    metrics = [
        ("수면 시간", minutes_to_hm(non_ja_stats["avg_duration_min"]), minutes_to_hm(ja_stats["avg_duration_min"]),
         f"{ja_stats['avg_duration_min'] - non_ja_stats['avg_duration_min']:+.0f}분"),
        ("취침 시각", hour_to_hhmm(non_ja_stats["avg_bedtime"]), hour_to_hhmm(ja_stats["avg_bedtime"]),
         f"{(normalize_bedtime(ja_stats['avg_bedtime']) - normalize_bedtime(non_ja_stats['avg_bedtime'])) * 60:+.0f}분"),
        ("기상 시각", hour_to_hhmm(non_ja_stats["avg_waketime"]), hour_to_hhmm(ja_stats["avg_waketime"]),
         f"{(ja_stats['avg_waketime'] - non_ja_stats['avg_waketime']) * 60:+.0f}분"),
        ("수면 만족도", f"{non_ja_stats['avg_rating_10']:.2f}", f"{ja_stats['avg_rating_10']:.2f}",
         f"{ja_stats['avg_rating_10'] - non_ja_stats['avg_rating_10']:+.2f}"),
        ("데이터 수", f"{non_ja_stats['count']:,}", f"{ja_stats['count']:,}", "-"),
    ]
    for name, val_non_ja, val_ja, diff in metrics:
        rows.append({"metric": name, "non_ja": val_non_ja, "japan": val_ja, "diff": diff})

    write_csv(OUTPUT_DIR / "step-03_section1-comparison.csv", rows, ["metric", "non_ja", "japan", "diff"])
    print("\n[Section 1] 일본 외 vs 일본 비교 저장 완료")


def section2_1_duration(ja_records):
    """Section 2-1: 수면시간 30분 구간별 만족도."""
    print("[Section 2-1] 수면시간별 만족도...")
    buckets = defaultdict(lambda: {"ratings": [], "count": 0})

    for r in ja_records:
        hours = r["seconds"] / 3600
        if r["rating"] is not None:
            # 30분 단위 버킷: 3h, 3.5h, 4h, ...
            bucket = round(hours * 2) / 2
            if bucket < 3:
                bucket = 3.0
            if bucket > 12:
                bucket = 12.0
            buckets[bucket]["ratings"].append(r["rating"])
            buckets[bucket]["count"] += 1

    rows = []
    for bucket in sorted(buckets.keys()):
        data = buckets[bucket]
        avg_r = sum(data["ratings"]) / len(data["ratings"])
        rows.append({
            "sleep_hours": bucket,
            "avg_rating_5": round(avg_r, 3),
            "avg_rating_10": round(avg_r * 2, 2),
            "count": len(data["ratings"]),
        })

    write_csv(OUTPUT_DIR / "step-03_section2-1-duration.csv", rows,
              ["sleep_hours", "avg_rating_5", "avg_rating_10", "count"])
    print(f"  {len(rows)} 구간 저장")
    return rows


def section2_2_bedtime(ja_records):
    """Section 2-2: 취침시각 1시간 구간별 만족도."""
    print("[Section 2-2] 취침시각별 만족도...")
    buckets = defaultdict(lambda: {"ratings": [], "count": 0})

    for r in ja_records:
        if r["rating"] is not None and r["bedtime_hour"] is not None:
            hour = int(r["bedtime_hour"]) % 24
            buckets[hour]["ratings"].append(r["rating"])
            buckets[hour]["count"] += 1

    # 20~4시 순서 (v2와 동일)
    hour_order = [20, 21, 22, 23, 0, 1, 2, 3, 4]
    rows = []
    for h in hour_order:
        if h in buckets:
            data = buckets[h]
            avg_r = sum(data["ratings"]) / len(data["ratings"])
            rows.append({
                "bedtime_hour": h,
                "avg_rating_5": round(avg_r, 3),
                "avg_rating_10": round(avg_r * 2, 2),
                "count": len(data["ratings"]),
            })

    write_csv(OUTPUT_DIR / "step-03_section2-2-bedtime.csv", rows,
              ["bedtime_hour", "avg_rating_5", "avg_rating_10", "count"])
    print(f"  {len(rows)} 시간대 저장")
    return rows


def section2_3_waketime(ja_records):
    """Section 2-3: 기상시각 1시간 구간별 만족도."""
    print("[Section 2-3] 기상시각별 만족도...")
    buckets = defaultdict(lambda: {"ratings": []})

    for r in ja_records:
        if r["rating"] is not None and r["waketime_hour"] is not None:
            hour = int(r["waketime_hour"]) % 24
            buckets[hour]["ratings"].append(r["rating"])

    hour_order = [4, 5, 6, 7, 8, 9, 10, 11, 12]
    rows = []
    for h in hour_order:
        if h in buckets:
            data = buckets[h]
            avg_r = sum(data["ratings"]) / len(data["ratings"])
            rows.append({
                "waketime_hour": h,
                "avg_rating_5": round(avg_r, 3),
                "avg_rating_10": round(avg_r * 2, 2),
                "count": len(data["ratings"]),
            })

    write_csv(OUTPUT_DIR / "step-03_section2-3-waketime.csv", rows,
              ["waketime_hour", "avg_rating_5", "avg_rating_10", "count"])
    print(f"  {len(rows)} 시간대 저장")
    return rows


def section2_4_activities(ja_records):
    """Section 2-4: 활동별 만족도 + 수면시간 + 취침시각."""
    print("[Section 2-4] 활동별 만족도...")
    buckets = defaultdict(lambda: {"ratings": [], "durations": [], "bedtimes": []})

    for r in ja_records:
        for act in r["activities"]:
            buckets[act]["durations"].append(r["seconds"] / 3600)
            if r["bedtime_hour"] is not None:
                buckets[act]["bedtimes"].append(normalize_bedtime(r["bedtime_hour"]))
            if r["rating"] is not None:
                buckets[act]["ratings"].append(r["rating"])

    # 일본 전체 평균 (rated records)
    ja_rated = [r for r in ja_records if r["rating"] is not None]
    ja_avg_rating = sum(r["rating"] for r in ja_rated) / len(ja_rated) if ja_rated else 0
    ja_avg_duration = sum(r["seconds"] / 3600 for r in ja_records) / len(ja_records)
    ja_avg_bedtime_vals = [normalize_bedtime(r["bedtime_hour"]) for r in ja_records if r["bedtime_hour"] is not None]
    ja_avg_bedtime = sum(ja_avg_bedtime_vals) / len(ja_avg_bedtime_vals) if ja_avg_bedtime_vals else 0

    rows = []
    for act, data in sorted(buckets.items(), key=lambda x: -sum(x[1]["ratings"]) / max(len(x[1]["ratings"]), 1)):
        if not data["ratings"]:
            continue
        avg_r = sum(data["ratings"]) / len(data["ratings"])
        avg_dur = sum(data["durations"]) / len(data["durations"])
        avg_bed = denormalize_bedtime(sum(data["bedtimes"]) / len(data["bedtimes"])) if data["bedtimes"] else 0
        kr_label = ACTIVITY_LABELS_KR.get(act, act)
        rows.append({
            "activity": act,
            "activity_kr": kr_label,
            "avg_rating_5": round(avg_r, 3),
            "avg_rating_10": round(avg_r * 2, 2),
            "rating_diff_10": round((avg_r - ja_avg_rating) * 2, 2),
            "avg_sleep_hours": round(avg_dur, 2),
            "sleep_diff_min": round((avg_dur - ja_avg_duration) * 60, 0),
            "avg_bedtime": hour_to_hhmm(avg_bed),
            "rated_count": len(data["ratings"]),
            "total_count": len(data["durations"]),
        })

    write_csv(OUTPUT_DIR / "step-03_section2-4-activities.csv", rows,
              ["activity", "activity_kr", "avg_rating_5", "avg_rating_10", "rating_diff_10",
               "avg_sleep_hours", "sleep_diff_min", "avg_bedtime", "rated_count", "total_count"])
    print(f"  {len(rows)} 활동 저장")
    return rows


def section2_5_emotions(ja_records):
    """Section 2-5: 감정별 만족도."""
    print("[Section 2-5] 감정별 만족도...")
    buckets = defaultdict(lambda: {"ratings": [], "count": 0})

    for r in ja_records:
        for mood in r["moods"]:
            buckets[mood]["count"] += 1
            if r["rating"] is not None:
                buckets[mood]["ratings"].append(r["rating"])

    ja_rated = [r for r in ja_records if r["rating"] is not None]
    ja_avg_rating = sum(r["rating"] for r in ja_rated) / len(ja_rated) if ja_rated else 0

    rows = []
    for mood, data in sorted(buckets.items(), key=lambda x: -sum(x[1]["ratings"]) / max(len(x[1]["ratings"]), 1)):
        if not data["ratings"]:
            continue
        avg_r = sum(data["ratings"]) / len(data["ratings"])
        kr_label = MOOD_LABELS_KR.get(mood, mood)
        rows.append({
            "mood": mood,
            "mood_kr": kr_label,
            "avg_rating_5": round(avg_r, 3),
            "avg_rating_10": round(avg_r * 2, 2),
            "rating_diff_10": round((avg_r - ja_avg_rating) * 2, 2),
            "rated_count": len(data["ratings"]),
            "total_count": data["count"],
        })

    write_csv(OUTPUT_DIR / "step-03_section2-5-emotions.csv", rows,
              ["mood", "mood_kr", "avg_rating_5", "avg_rating_10", "rating_diff_10",
               "rated_count", "total_count"])
    print(f"  {len(rows)} 감정 저장")
    return rows


def section2_6_weekday(ja_records):
    """Section 2-6: 요일별 수면시간 + 만족도 + 취침/기상 시각."""
    print("[Section 2-6] 요일별 패턴...")
    buckets = defaultdict(lambda: {"durations": [], "ratings": [], "bedtimes": [], "waketimes": []})

    for r in ja_records:
        date_str = r["date"]
        if not date_str:
            continue
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekday_en = dt.strftime("%A")
            weekday_kr = WEEKDAY_MAP.get(weekday_en, "")
        except Exception:
            continue

        buckets[weekday_kr]["durations"].append(r["seconds"] / 3600)
        if r["rating"] is not None:
            buckets[weekday_kr]["ratings"].append(r["rating"])
        if r["bedtime_hour"] is not None:
            buckets[weekday_kr]["bedtimes"].append(normalize_bedtime(r["bedtime_hour"]))
        if r["waketime_hour"] is not None:
            buckets[weekday_kr]["waketimes"].append(r["waketime_hour"])

    rows = []
    for day in WEEKDAY_ORDER:
        data = buckets[day]
        if not data["durations"]:
            continue
        avg_dur = sum(data["durations"]) / len(data["durations"])
        avg_rat = (sum(data["ratings"]) / len(data["ratings"]) * 2) if data["ratings"] else 0
        avg_bed = denormalize_bedtime(sum(data["bedtimes"]) / len(data["bedtimes"])) if data["bedtimes"] else 0
        avg_wake = sum(data["waketimes"]) / len(data["waketimes"]) if data["waketimes"] else 0

        rows.append({
            "weekday": day,
            "avg_sleep_hours": round(avg_dur, 3),
            "avg_rating_10": round(avg_rat, 2),
            "avg_bedtime": hour_to_hhmm(avg_bed),
            "avg_bedtime_decimal": round(avg_bed, 2),
            "avg_waketime": hour_to_hhmm(avg_wake),
            "avg_waketime_decimal": round(avg_wake, 2),
            "count": len(data["durations"]),
            "rated_count": len(data["ratings"]),
        })

    write_csv(OUTPUT_DIR / "step-03_section2-6-weekday.csv", rows,
              ["weekday", "avg_sleep_hours", "avg_rating_10", "avg_bedtime", "avg_bedtime_decimal",
               "avg_waketime", "avg_waketime_decimal", "count", "rated_count"])
    print(f"  {len(rows)} 요일 저장")
    return rows


def write_analysis_summary(non_ja_stats, ja_stats, dur_rows, bed_rows, wake_rows, act_rows, mood_rows, weekday_rows):
    """전체 분석 결과 요약 MD."""
    # 주중/주말 계산
    weekday_data = {r["weekday"]: r for r in weekday_rows}
    weekday_days = ["월", "화", "수", "목", "금"]
    weekend_days = ["토", "일"]

    wd_dur = sum(weekday_data[d]["avg_sleep_hours"] for d in weekday_days) / 5
    we_dur = sum(weekday_data[d]["avg_sleep_hours"] for d in weekend_days) / 2
    wd_rat = sum(weekday_data[d]["avg_rating_10"] for d in weekday_days) / 5
    we_rat = sum(weekday_data[d]["avg_rating_10"] for d in weekend_days) / 2

    md = f"""# Step 03: 분석 결과 요약

## 일본 외 vs 일본 (Section 1)
- 일본 외: {non_ja_stats['count']:,}건, 수면 {minutes_to_hm(non_ja_stats['avg_duration_min'])}, 만족도 {non_ja_stats['avg_rating_10']:.2f}
- 일본: {ja_stats['count']:,}건, 수면 {minutes_to_hm(ja_stats['avg_duration_min'])}, 만족도 {ja_stats['avg_rating_10']:.2f}
- 취침: 일본 외 {hour_to_hhmm(non_ja_stats['avg_bedtime'])} → 일본 {hour_to_hhmm(ja_stats['avg_bedtime'])}
- 기상: 일본 외 {hour_to_hhmm(non_ja_stats['avg_waketime'])} → 일본 {hour_to_hhmm(ja_stats['avg_waketime'])}

## 수면시간별 만족도 (Section 2-1)
- 7시간 이상에서 평균 이상 만족도
- 주요 구간: {', '.join(f"{r['sleep_hours']}h={r['avg_rating_10']}" for r in dur_rows if 5 <= r['sleep_hours'] <= 10)}

## 취침시각별 만족도 (Section 2-2)
- 이른 취침일수록 높은 만족도
- 주요 시간대: {', '.join(f"{r['bedtime_hour']}시={r['avg_rating_10']}" for r in bed_rows)}

## 기상시각별 만족도 (Section 2-3)
- 늦은 기상일수록 높은 만족도 (충분한 수면)
- 주요 시간대: {', '.join(f"{r['waketime_hour']}시={r['avg_rating_10']}" for r in wake_rows)}

## 활동별 만족도 TOP 5 / BOTTOM 3 (Section 2-4)
- TOP: {', '.join(f"{r['activity_kr']}({r['avg_rating_10']})" for r in act_rows[:5])}
- BOTTOM: {', '.join(f"{r['activity_kr']}({r['avg_rating_10']})" for r in act_rows[-3:])}

## 감정별 만족도 TOP 3 / BOTTOM 3 (Section 2-5)
- TOP: {', '.join(f"{r['mood_kr']}({r['avg_rating_10']})" for r in mood_rows[:3])}
- BOTTOM: {', '.join(f"{r['mood_kr']}({r['avg_rating_10']})" for r in mood_rows[-3:])}

## 주중 vs 주말 (Section 2-6)
- 주중 수면: {wd_dur:.2f}h, 만족도: {wd_rat:.2f}
- 주말 수면: {we_dur:.2f}h, 만족도: {we_rat:.2f}
- 차이: 수면 +{(we_dur - wd_dur)*60:.0f}분, 만족도 +{we_rat - wd_rat:.2f}
"""
    write_md(OUTPUT_DIR / "step-03_analysis-summary.md", md)
    print("\n[분석 요약] step-03_analysis-summary.md 저장 완료")


# ── Main ──

def main():
    print("=" * 60)
    print("v3 일본인 수면 만족도 분석")
    print("sleepStartAt / sleepEndAt 기준")
    print("=" * 60)

    # Phase 1
    all_records, ja_records, non_ja_records = load_and_filter()

    # Phase 2
    all_stats, ja_stats, non_ja_stats = compute_basic_stats(all_records, ja_records, non_ja_records)

    # Phase 3
    section1_comparison(non_ja_stats, ja_stats)
    dur_rows = section2_1_duration(ja_records)
    bed_rows = section2_2_bedtime(ja_records)
    wake_rows = section2_3_waketime(ja_records)
    act_rows = section2_4_activities(ja_records)
    mood_rows = section2_5_emotions(ja_records)
    weekday_rows = section2_6_weekday(ja_records)
    write_analysis_summary(non_ja_stats, ja_stats, dur_rows, bed_rows, wake_rows, act_rows, mood_rows, weekday_rows)

    print("\n" + "=" * 60)
    print("분석 완료! output/ 폴더 확인")
    print("=" * 60)


if __name__ == "__main__":
    main()
