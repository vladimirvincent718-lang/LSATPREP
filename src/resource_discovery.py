"""
Resource discovery helpers for Course Materials.

The module is intentionally UI-free so API calls, scoring, and module inference
can be tested without Streamlit.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


MODULE_RE = re.compile(
    r"\b(?P<kind>module|week|unit|lesson|chapter)\s*#?\s*(?P<num>\d+[a-z]?)\b"
    r"(?:\s*[:\-]\s*(?P<title>[^\n|;,]{2,80}))?",
    re.IGNORECASE,
)

POSITIVE_SIGNALS = [
    "university", "college", ".edu", ".gov", "official", "association",
    "institute", "academy", "hospital", "clinic", "medical center",
    "professor", "phd", "ph.d", "md", "m.d", "doctor", "certified",
    "board certified", "licensed", "research", "journal", "foundation",
    "society", "organization", "department", "lecture", "course",
]

NEGATIVE_SIGNALS = [
    "reaction", "prank", "vlog", "drama", "gossip", "shocking", "exposed",
    "buy now", "sponsored", "affiliate", "promo code", "sale", "unboxing",
    "top 10", "hack", "get rich", "side hustle", "miracle", "secret trick",
]

SOURCE_PREFERENCES = {
    "University / institution": ["university", "college", ".edu", ".gov", "department", "institute"],
    "Professional organization": ["association", "society", "organization", "foundation", "official"],
    "Credentialed educator": ["professor", "phd", "ph.d", "md", "m.d", "doctor", "certified", "licensed"],
    "Any educational source": [],
}


@dataclass
class DiscoveryError(Exception):
    message: str


def infer_modules(materials: list[dict]) -> list[dict]:
    modules: dict[str, dict] = {}
    for mat in materials:
        explicit_module = clean_text(mat.get("module_name", ""))
        if explicit_module and clean_text(mat.get("material_section", "")) == "Module":
            key = re.sub(r"[^a-z0-9]+", "-", explicit_module.lower()).strip("-")
            item = modules.setdefault(
                key,
                {"key": key, "label": explicit_module, "material_ids": [], "topics": []},
            )
            if mat.get("id") not in item["material_ids"]:
                item["material_ids"].append(mat.get("id"))
            for topic in _topic_candidates(mat):
                if topic and topic not in item["topics"]:
                    item["topics"].append(topic)

        combined = "\n".join(
            str(mat.get(field) or "")
            for field in ("title", "notes", "content_text")
        )
        for match in MODULE_RE.finditer(combined):
            kind = match.group("kind").title()
            num = match.group("num").upper()
            title = clean_text(match.group("title") or "")
            label = f"{kind} {num}"
            if title:
                label = f"{label}: {title}"
            key = f"{kind.lower()}-{num.lower()}"
            item = modules.setdefault(
                key,
                {"key": key, "label": label, "material_ids": [], "topics": []},
            )
            if mat.get("id") not in item["material_ids"]:
                item["material_ids"].append(mat.get("id"))
            for topic in _topic_candidates(mat):
                if topic and topic not in item["topics"]:
                    item["topics"].append(topic)
    return sorted(modules.values(), key=_module_sort_key)


def build_module_query(course: dict, module: dict, difficulty: str) -> str:
    parts = [
        str(course.get("title") or ""),
        str(course.get("category") or ""),
        module.get("label", ""),
    ]
    parts.extend(module.get("topics", [])[:3])
    if difficulty and difficulty.lower() != "intermediate":
        parts.append(difficulty)
    parts.append("educational lecture")
    return " ".join(clean_text(part) for part in parts if clean_text(part))


def discover_resources(
    course: dict,
    modules: list[dict],
    *,
    youtube_key: str = "",
    google_key: str = "",
    google_cx: str = "",
    include_videos: bool = True,
    include_articles: bool = True,
    max_per_module: int = 3,
    min_video_minutes: int = 0,
    max_video_minutes: int = 60,
    difficulty: str = "intermediate",
    source_preference: str = "Any educational source",
) -> list[dict]:
    results: list[dict] = []
    for module in modules:
        query = build_module_query(course, module, difficulty)
        if include_videos:
            if not youtube_key:
                raise DiscoveryError("YouTube API key is missing.")
            results.extend(
                search_youtube(
                    youtube_key,
                    query,
                    module,
                    max_per_module=max_per_module,
                    min_minutes=min_video_minutes,
                    max_minutes=max_video_minutes,
                    source_preference=source_preference,
                )
            )
        if include_articles:
            if not google_key or not google_cx:
                raise DiscoveryError("Google Custom Search API key or Search Engine ID is missing.")
            results.extend(
                search_articles(
                    google_key,
                    google_cx,
                    query,
                    module,
                    max_per_module=max_per_module,
                    source_preference=source_preference,
                )
            )
    return results


def search_youtube(
    api_key: str,
    query: str,
    module: dict,
    *,
    max_per_module: int,
    min_minutes: int,
    max_minutes: int,
    source_preference: str,
) -> list[dict]:
    search_payload = _get_json(
        "https://www.googleapis.com/youtube/v3/search",
        {
            "key": api_key,
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(25, max(5, max_per_module * 4)),
            "safeSearch": "strict",
            "relevanceLanguage": "en",
        },
    )
    items = search_payload.get("items", [])
    video_ids = [
        item.get("id", {}).get("videoId")
        for item in items
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return []

    details = _get_json(
        "https://www.googleapis.com/youtube/v3/videos",
        {
            "key": api_key,
            "part": "contentDetails,statistics,snippet",
            "id": ",".join(video_ids),
            "maxResults": len(video_ids),
        },
    )
    rows = []
    for item in details.get("items", []):
        snippet = item.get("snippet", {})
        duration = parse_iso8601_duration(item.get("contentDetails", {}).get("duration", ""))
        minutes = max(1, math.ceil(duration.total_seconds() / 60)) if duration else 0
        if minutes and (minutes < min_minutes or minutes > max_video_minutes):
            continue
        title = clean_text(snippet.get("title", "Untitled video"))
        channel = clean_text(snippet.get("channelTitle", ""))
        description = clean_text(snippet.get("description", ""))
        url = f"https://www.youtube.com/watch?v={item.get('id')}"
        score, reason = score_resource(
            title=title,
            source=channel,
            snippet=description,
            url=url,
            source_preference=source_preference,
        )
        rows.append(
            {
                "module": module["label"],
                "resource_type": "Video",
                "title": title,
                "source": channel,
                "url": url,
                "estimated_minutes": minutes,
                "published": (snippet.get("publishedAt") or "")[:10],
                "snippet": description[:260],
                "credibility_score": score,
                "credibility_reason": reason,
                "query": query,
            }
        )
    return sorted(rows, key=lambda r: r["credibility_score"], reverse=True)[:max_per_module]


def search_articles(
    api_key: str,
    cx: str,
    query: str,
    module: dict,
    *,
    max_per_module: int,
    source_preference: str,
) -> list[dict]:
    payload = _get_json(
        "https://www.googleapis.com/customsearch/v1",
        {
            "key": api_key,
            "cx": cx,
            "q": f"{query} article OR guide OR overview",
            "num": min(10, max(3, max_per_module * 3)),
            "safe": "active",
        },
    )
    rows = []
    for item in payload.get("items", []):
        title = clean_text(item.get("title", "Untitled article"))
        url = item.get("link", "")
        source = clean_text(item.get("displayLink") or _domain(url))
        snippet = clean_text(item.get("snippet", ""))
        score, reason = score_resource(
            title=title,
            source=source,
            snippet=snippet,
            url=url,
            source_preference=source_preference,
        )
        rows.append(
            {
                "module": module["label"],
                "resource_type": "Link",
                "title": title,
                "source": source,
                "url": url,
                "estimated_minutes": estimate_reading_minutes(title, snippet),
                "published": "",
                "snippet": snippet[:260],
                "credibility_score": score,
                "credibility_reason": reason,
                "query": query,
            }
        )
    return sorted(rows, key=lambda r: r["credibility_score"], reverse=True)[:max_per_module]


def score_resource(
    *,
    title: str,
    source: str,
    snippet: str,
    url: str,
    source_preference: str,
) -> tuple[int, str]:
    text = f"{title} {source} {snippet} {url}".lower()
    score = 50
    reasons = []

    positives = [signal for signal in POSITIVE_SIGNALS if signal in text]
    negatives = [signal for signal in NEGATIVE_SIGNALS if signal in text]
    if positives:
        score += min(35, len(positives) * 7)
        reasons.append("educational/source signals: " + ", ".join(positives[:3]))
    if negatives:
        score -= min(35, len(negatives) * 10)
        reasons.append("possible low-fit signals: " + ", ".join(negatives[:3]))

    preferred = SOURCE_PREFERENCES.get(source_preference, [])
    matched_preferred = [signal for signal in preferred if signal in text]
    if matched_preferred:
        score += 15
        reasons.append("matches preferred source type")

    if ".edu" in text or ".gov" in text:
        score += 10
    if "youtube.com" in url and any(word in text for word in ("lecture", "course", "lesson")):
        score += 5

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("ranked by relevance with no strong source signal")
    return score, "; ".join(reasons)


def parse_iso8601_duration(value: str) -> timedelta:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value or "",
    )
    if not match:
        return timedelta()
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return timedelta(**parts)


def estimate_reading_minutes(title: str, snippet: str) -> int:
    words = len(re.findall(r"\w+", f"{title} {snippet}"))
    return max(3, min(20, math.ceil(max(words, 650) / 220)))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _topic_candidates(mat: dict) -> list[str]:
    values = []
    for field in ("title", "notes"):
        raw = clean_text(mat.get(field, ""))
        raw = MODULE_RE.sub("", raw).strip(" -:|")
        if raw:
            values.append(raw[:90])
    content = clean_text(mat.get("content_text", ""))
    if content:
        values.append(content[:120])
    return values


def _module_sort_key(module: dict) -> tuple[str, int, str]:
    match = re.search(r"^(Module|Week|Unit|Lesson|Chapter)\s+(\d+)", module["label"], re.I)
    if not match:
        return (module["label"], 0, module["label"])
    return (match.group(1).lower(), int(match.group(2)), module["label"])


def _get_json(url: str, params: dict) -> dict:
    full_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(full_url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DiscoveryError(f"API request failed ({exc.code}): {body[:240]}")
    except URLError as exc:
        raise DiscoveryError(f"Network request failed: {exc.reason}")
    except json.JSONDecodeError:
        raise DiscoveryError("API returned invalid JSON.")


def _domain(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "")
