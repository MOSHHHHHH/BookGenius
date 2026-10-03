#!/usr/bin/env python3
"""
Daily job for BookGenius: reads Israel's Google Trends RSS feed, asks Gemini
for 2 evergreen guide/book recommendations inspired by today's trends, and
writes data/trending-recs.json for the front-end (recBar) to display.

Only writes the output file on full success, so a bad run never overwrites
yesterday's good recommendations (the front-end also ignores stale files
older than ~36h — see TREND_RECS_MAX_AGE_MS in index.htm).

Required env var: GEMINI_API_KEY
Optional env vars: GEMINI_MODEL (default: gemini-2.0-flash), TRENDS_GEO (default: IL)

No third-party dependencies (stdlib only), so no pip install step is needed
in the workflow.
"""
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

GEO = os.environ.get("TRENDS_GEO", "IL")
TRENDS_URL = "https://trends.google.com/trending/rss?geo=" + GEO
NS = {"ht": "https://trends.google.com/trending/rss"}
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
API_KEY = os.environ.get("GEMINI_API_KEY", "")

OUT_PATH = os.path.join("data", "trending-recs.json")
HISTORY_PATH = os.path.join("data", "trending-recs-history.json")
MAX_TRENDS = 15
HISTORY_DAYS = 5


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
        + MODEL + ":generateContent?key=" + API_KEY
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
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def main():
    if not API_KEY:
        print("FAIL: GEMINI_API_KEY is not set")
        sys.exit(1)

    try:
        trends = fetch_trends()
    except (urllib.error.URLError, ET.ParseError) as e:
        print("FAIL: could not fetch/parse Google Trends RSS:", e)
        sys.exit(1)

    if not trends:
        print("FAIL: no trends returned from feed")
        sys.exit(1)

    history = load_history()
    recent_topics = [h.get("topic", "") for h in history]

    prompt = build_prompt(trends, recent_topics)

    try:
        result = call_gemini(prompt)
    except Exception as e:
        print("FAIL: Gemini request failed:", e)
        sys.exit(1)

    recs = result.get("recommendations") if isinstance(result, dict) else None
    if not isinstance(recs, list) or len(recs) < 2:
        print("FAIL: Gemini did not return at least 2 recommendations")
        sys.exit(1)
    recs = recs[:2]

    for r in recs:
        for key in ("topic", "desc", "writing_instructions", "chapters"):
            if key not in r or not r[key]:
                print("FAIL: a recommendation is missing field:", key)
                sys.exit(1)

    os.makedirs("data", exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "geo": GEO,
        "recommendations": recs,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    save_history(history, [r["topic"] for r in recs])
    print("OK: wrote", OUT_PATH, "with", len(recs), "recommendations")


if __name__ == "__main__":
    main()
