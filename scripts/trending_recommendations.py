#!/usr/bin/env python3
"""
Hourly job for BookGenius (daily updates, warn before 30h of staleness): reads Israel's Google Trends RSS feed, asks Gemini
for 2 evergreen guide/book recommendations inspired by today's trends, and
writes data/trending-recs.json for the front-end (recBar) to display.

Only writes the output file on full success, so a bad run never overwrites
yesterday's good recommendations (the front-end also ignores stale files
older than ~36h — see TREND_RECS_MAX_AGE_MS in index.htm).

Required env var: GEMINI_API_KEY
Optional env vars: GEMINI_MODEL (default: gemini-3.5-flash), TRENDS_GEO (default: IL)

No third-party dependencies (stdlib only), so no pip install step is needed
in the workflow.
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

GEO = os.environ.get("TRENDS_GEO", "IL")
TRENDS_URL = "https://trends.google.com/trending/rss?geo=" + GEO
NS = {"ht": "https://trends.google.com/trending/rss"}
# gemini-2.0-flash was shut down by Google (404). Use gemini-3.5-flash,
# or gemini-3.1-flash-lite for a cheaper/faster option.
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash"
API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Retry only temporary HTTP failures; invalid API keys/permissions fail immediately.
RETRYABLE_GEMINI_HTTP_CODES = {429, 500, 502, 503, 504}
GEMINI_MAX_ATTEMPTS = 5

OUT_PATH = os.path.join("data", "trending-recs.json")
HISTORY_PATH = os.path.join("data", "trending-recs-history.json")
MAX_TRENDS = 15
HISTORY_DAYS = 5
REFRESH_INTERVAL = timedelta(hours=24)
MAX_AGE_BEFORE_ERROR = timedelta(hours=30)


def fetch_trends():
    """Returns a list of {"title": str, "news": [{"title","snippet"}, ...]}."""
    req = urllib.request.Request(
        TRENDS_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; BookGeniusBot/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        news = []
        for ni in item.findall("ht:news_item", NS):
            ni_title = (ni.findtext("ht:news_item_title", default="", namespaces=NS) or "").strip()
            ni_snippet = (ni.findtext("ht:news_item_snippet", default="", namespaces=NS) or "").strip()
            if ni_title:
                news.append({"title": ni_title, "snippet": ni_snippet})
        items.append({"title": title, "news": news[:3]})
        if len(items) >= MAX_TRENDS:
            break
    return items


def load_history():
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    out = []
    for row in data:
        try:
            d = datetime.fromisoformat(row.get("date", ""))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if d >= cutoff:
            out.append(row)
    return out


def save_history(history, new_topics):
    today = datetime.now(timezone.utc).date().isoformat()
    for t in new_topics:
        history.append({"date": today, "topic": t})
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def build_prompt(trends, recent_topics):
    lines = []
    for t in trends:
        lines.append("- " + t["title"])
        for n in t["news"]:
            snippet = (" — " + n["snippet"]) if n["snippet"] else ""
            lines.append("    · " + n["title"] + snippet)
    trends_block = "\n".join(lines) if lines else "(לא נמצאו טרנדים היום)"
    recent_block = ", ".join(recent_topics) if recent_topics else "(אין)"


    return (
        "אתה עוזר שמנתח רשימת טרנדים פופולריים בחיפוש בישראל (Google Trends) להיום, "
        "ומציע על בסיסם רעיונות למדריכים עבור כלי כתיבת ספרים בשם BookGenius.\n\n"
        "להלן רשימת הטרנדים של היום, עם כתבות חדשות קשורות לכל טרנד (אם יש):\n"
        + trends_block + "\n\n"
        "המשימה שלך: הצע בדיוק 2 מדריכים, בהשראת הטרנדים שלמעלה, שמתאימים לקריאה תמיד — "
        "אך רלוונטיים במיוחד כרגע. זו לא כתיבה על האירוע עצמו, אלא מדריך מעשי ושימושי "
        "שנושא הטרנד מעורר צורך בו.\n\n"
        "דוגמאות לסוג הקשר הנדרש:\n"
        "- טרנד \"פיגוע\" -> מדריך \"כיצד לנהוג בעת פיגוע\" (לא סיקור הפיגוע עצמו).\n"
        "- טרנד \"בחירות\" -> מדריך \"כיצד לבדוק ולהשוות מצעי מפלגות\" (לא תעמולה לכיוון מסוים).\n\n"
        "כללים מחייבים:\n"
        "1. השמטה מוחלטת של כל תוכן בעל אופי מיני.\n"
        "2. אין לכתוב תוכן שמסקר את האירוע עצמו — רק מדריך מעשי, חינוכי או שימושי שהטרנד ממחיש את הצורך בו.\n"
        "3. אם לטרנד מסוים אין זווית הגיונית למדריך מעשי (רכילות סלבריטאים, תוצאת ספורט חד-פעמית וכו') — "
        "התעלם ממנו ובחר טרנד אחר מהרשימה.\n"
        "4. הישאר ניטרלי ככל האפשר בנושאים פוליטיים/שנויים במחלוקת — התמקד ב\"איך לבדוק/להבין/להעריך\" ולא בעמדה.\n"
        "5. בנושא רגיש (אסון, פיגוע, אובדן חיים) — המדריך חייב להיות בעל כיוון מגן, תומך או מעשי בלבד, "
        "לעולם לא תיאור גרפי של האירוע.\n"
        "6. אל תציע שוב נושא מתוך הרשימה הבאה, שכבר הוצעה בימים האחרונים: " + recent_block + "\n"
        "7. אם אף טרנד לא מתאים לפי הכללים האלה, בחר נושא מדריך כללי ושימושי שתמיד רלוונטי, "
        "במקום לכפות התאמה מלאכותית.\n\n"
        "כתוב הכל בעברית. עבור chapters, החזר מספר שלם בין 5 ל-15. "
        "עבור inspired_by, רשום את הטרנד שהשרה את ההצעה (או \"כללי\" אם לא התבססת על טרנד ספציפי).\n"
        "החזר אך ורק אובייקט JSON תקני, ללא כל טקסט נוסף סביבו."
    )



def call_gemini(prompt):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + MODEL + ":generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "recommendations": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "topic": {"type": "STRING"},
                                "desc": {"type": "STRING"},
                                "writing_instructions": {"type": "STRING"},
                                "chapters": {"type": "INTEGER"},
                                "inspired_by": {"type": "STRING"},
                            },
                            "required": ["topic", "desc", "writing_instructions", "chapters", "inspired_by"],
                        },
                    }
                },
                "required": ["recommendations"],
            },
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        # The key goes in a header instead of the URL so it never shows up in logs.
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
        method="POST",
    )
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            if e.code not in RETRYABLE_GEMINI_HTTP_CODES or attempt == GEMINI_MAX_ATTEMPTS:
                raise RuntimeError(
                    "HTTP %s (model=%s, attempt=%s/%s): %s"
                    % (e.code, MODEL, attempt, GEMINI_MAX_ATTEMPTS, detail)
                ) from None
            delay = 2 ** attempt + random.uniform(0, 1)
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after and retry_after.strip().isdigit():
                delay = max(delay, min(int(retry_after.strip()), 60))
            print(
                "WARN: Gemini HTTP %s (model=%s); retrying in %.1fs (attempt %s/%s)"
                % (e.code, MODEL, delay, attempt, GEMINI_MAX_ATTEMPTS),
                flush=True,
            )
            time.sleep(delay)

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("no candidates in response: " + json.dumps(data, ensure_ascii=False)[:500])

    # Newer models may return "thought" parts too; keep only the real text parts.
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise RuntimeError("empty text in response, finishReason=" + str(candidates[0].get("finishReason")))
    return json.loads(text)


def last_success_age(now=None):
    """Return the age of the last valid saved update, or None if unavailable."""
    now = now or datetime.now(timezone.utc)
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        recs = data.get("recommendations")
        if not isinstance(recs, list) or len(recs) != 2:
            return None
        if not all(isinstance(r, dict) and all(r.get(k) for k in ("topic", "desc", "writing_instructions", "chapters")) for r in recs):
            return None
        stamp = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        age = now - stamp
        return age if age >= timedelta(0) else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def report_failure(reason):
    """A failed refresh is nonfatal until the last valid update is 30h old."""
    age = last_success_age()
    if age is None:
        print("FAIL: %s; no valid previous recommendations are available" % reason)
        return 1
    age_hours = age.total_seconds() / 3600
    if age >= MAX_AGE_BEFORE_ERROR:
        print("FAIL: %s; last successful update was %.1f hours ago (30h limit)" % (reason, age_hours))
        return 1
    print("WARN: %s; last successful update was %.1f hours ago (under 30h, retry next hour)" % (reason, age_hours))
    return 0


def main():
    age = last_success_age()
    if age is not None and age < REFRESH_INTERVAL:
        print("SKIP: recommendations updated successfully within the last 24 hours")
        return 0

    try:
        if not API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")

        try:
            trends = fetch_trends()
        except (urllib.error.URLError, ET.ParseError) as e:
            raise RuntimeError("could not fetch/parse Google Trends RSS: %s" % e) from e

        if not trends:
            raise RuntimeError("no trends returned from feed")

        history = load_history()
        recent_topics = [h.get("topic", "") for h in history]
        prompt = build_prompt(trends, recent_topics)
        result = call_gemini(prompt)

        recs = result.get("recommendations") if isinstance(result, dict) else None
        if not isinstance(recs, list) or len(recs) < 2:
            raise RuntimeError("Gemini did not return at least 2 recommendations")
        recs = recs[:2]

        for r in recs:
            for key in ("topic", "desc", "writing_instructions", "chapters"):
                if not isinstance(r, dict) or not r.get(key):
                    raise RuntimeError("a recommendation is missing field: %s" % key)

        os.makedirs("data", exist_ok=True)
        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "geo": GEO,
            "recommendations": recs,
        }
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        save_history(history, [r["topic"] for r in recs])
    except Exception as e:
        return report_failure(str(e))

    print("OK: wrote", OUT_PATH, "with", len(recs), "recommendations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
