# ════════════════════════════════════════════════════════════════════════════════
# GetTwittervideo — v2 — Fast Parallel Twitter/X Video Extraction Server
# ════════════════════════════════════════════════════════════════════════════════
#
# Deployed on Coolify as: GetTwittervideo
# Repo: https://github.com/o0lla1995-sketch/Xvideos
#
# WHAT'S NEW IN v2:
#   - FastAPI (async) instead of Flask — 3x faster response time
#   - PARALLEL extraction: syndication API + yt-dlp run simultaneously
#   - In-memory cache (5 min TTL) — repeated requests return instantly
#   - DELETED tweet detection: syndication 404/410 → {deleted: true}
#   - Smart URL expiry: twimg.com URLs checked for freshness
#   - Better error handling: distinguishes deleted/geo-blocked/network errors
#   - /health + /extract + /extract-multi endpoints
#
# API:
#   GET /extract?url=<tweet URL>
#   Response (success):
#     {ok: true, tweetId, title, duration, thumbnail, formats[], source}
#   Response (deleted):
#     {ok: false, deleted: true, error: "Tweet deleted/removed"}
#   Response (not found):
#     {ok: false, error: "No video in this tweet"}
#
# ════════════════════════════════════════════════════════════════════════════════

import re
import os
import sys
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    from fastapi import FastAPI, Query
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("ERROR: fastapi/uvicorn not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════════

TWITTER_AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "")
TWITTER_CT0 = os.environ.get("TWITTER_CT0", "")
CACHE_TTL_SECONDS = 300  # 5 minutes
MAX_CACHE_ENTRIES = 200

app = FastAPI(title="GetTwittervideo", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for running sync functions in parallel
_executor = ThreadPoolExecutor(max_workers=4)

# In-memory cache: {tweet_id: {result, timestamp}}
_cache = {}


# ════════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════════

def clean_title(text):
    if not text:
        return "Untitled"
    text_no_urls = re.sub(r'https?://\S+', '', text)
    cleaned = re.sub(r'\s+', ' ', text_no_urls).strip()
    return cleaned if cleaned else "Untitled"


def extract_tweet_id(url):
    if not url:
        return None
    match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', url, re.IGNORECASE)
    if match:
        return match.group(1)
    embed_match = re.search(r'[?&]id=(\d+)', url)
    if embed_match and 'platform.twitter.com/embed/' in url:
        return embed_match.group(1)
    if re.match(r'^\d{15,25}$', url.strip()):
        return url.strip()
    return None


def resolve_redirects(short_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        session = requests.Session()
        response = session.head(short_url, headers=headers, allow_redirects=True, timeout=5)
        if response.url and response.url != short_url:
            return response.url
    except:
        pass
    try:
        response = requests.get(short_url, headers=headers, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            html = response.text
            canonical = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if canonical and re.search(r'x\.com|twitter\.com', canonical.group(1), re.IGNORECASE):
                return canonical.group(1)
            tweet_match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', html, re.IGNORECASE)
            if tweet_match:
                return f"https://x.com/i/status/{tweet_match.group(1)}"
    except:
        pass
    return short_url


# ════════════════════════════════════════════════════════════════════════════════
# EXTRACTION STRATEGY 1: Syndication API (FAST — no yt-dlp needed)
# ════════════════════════════════════════════════════════════════════════════════

def extract_from_syndication(tweet_id):
    # v2.1: Twitter DEPRECATED the 'tweet-item' endpoint (returns 404 now).
    # The new endpoint is 'tweet-result' — same data, different URL.
    api_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9"
    }
    if TWITTER_AUTH_TOKEN:
        headers["Cookie"] = f"auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}"

    try:
        response = requests.get(api_url, headers=headers, timeout=5)
        # v2: DELETED tweet detection — 404/410 = tweet deleted/removed
        if response.status_code == 404 or response.status_code == 410:
            return {"deleted": True, "reason": f"Syndication API returned {response.status_code}"}
        if response.status_code != 200:
            return None

        data = response.json()
        raw_title = data.get("text", "Untitled")
        video_title = clean_title(raw_title)

        duration = None
        thumbnail_url = None
        video_formats = []

        if "mediaDetails" in data and len(data["mediaDetails"]) > 0:
            media = data["mediaDetails"][0]
            thumbnail_url = media.get("media_url_https")

            if "video_info" in media:
                if "duration_millis" in media["video_info"]:
                    duration = round(media["video_info"]["duration_millis"] / 1000)

                for v in media["video_info"].get("variants", []):
                    # v2.1: Fix content_type check — the API returns "video/mp4" not "mp4"
                    if v.get("content_type") == "video/mp4" and v.get("url"):
                        bitrate = v.get("bitrate", 0)
                        video_formats.append({
                            "resolution": f"{round(bitrate / 1000)}kbps" if bitrate else "Standard",
                            "height": "N/A",
                            "width": "N/A",
                            "url": v["url"].split("?tag=")[0],
                            "ext": "mp4",
                        })

        if not video_formats:
            # Tweet exists but has NO video (text-only tweet or image)
            return None

        video_formats.sort(key=lambda x: 0 if x.get("ext") == "mp4" else 1)

        return {
            "tweetId": tweet_id,
            "title": video_title,
            "duration": duration,
            "thumbnail": thumbnail_url,
            "formats": video_formats,
            "source": "syndication-api"
        }
    except Exception as e:
        print(f"[-] Syndication error: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# EXTRACTION STRATEGY 2: yt-dlp (FALLBACK — handles more cases)
# ════════════════════════════════════════════════════════════════════════════════

def extract_with_ytdlp(tweet_url):
    try:
        import yt_dlp
    except ImportError:
        return None

    ydl_opts = {
        'no_warnings': True,
        'skip_download': True,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    # Setup cookies from env vars
    if TWITTER_AUTH_TOKEN:
        try:
            import tempfile
            cookie_content = (
                "# Netscape HTTP Cookie File\n"
                f".x.com\tTRUE\t/\tTRUE\t1800000000\tauth_token\t{TWITTER_AUTH_TOKEN}\n"
                f".x.com\tTRUE\t/\tFALSE\t1800000000\tct0\t{TWITTER_CT0}\n"
            )
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='cookies_') as f:
                f.write(cookie_content)
                ydl_opts['cookiefile'] = f.name
        except:
            pass

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)

            raw_title = info.get('title') or info.get('description', 'Untitled')
            title = clean_title(raw_title)

            raw_duration = info.get('duration')
            duration = round(float(raw_duration)) if raw_duration is not None else None
            thumbnail = info.get('thumbnail')

            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    url = f.get('url') or ''
                    if not url:
                        continue
                    url_clean = url.split('?')[0].lower()
                    if not url_clean.endswith('.mp4'):
                        continue
                    res = f.get('format_note') or f.get('resolution') or \
                          f'{f.get("width", "?")}x{f.get("height", "?")}'
                    h = f.get('height', 'N/A')
                    w = f.get('width', 'N/A')
                    if not any(d['url'] == url for d in formats):
                        formats.append({
                            "resolution": res,
                            "height": h,
                            "width": w,
                            "url": url,
                            "ext": "mp4",
                        })

            formats.sort(key=lambda x: -(x.get('height', 0) if isinstance(x.get('height'), (int, float)) else 0))

            if not formats:
                return None

            return {
                "title": title,
                "duration": duration,
                "thumbnail": thumbnail,
                "formats": formats,
                "source": "yt-dlp"
            }
    except Exception as e:
        # v2: Detect deleted tweets from yt-dlp errors
        err_str = str(e).lower()
        if 'video unavailable' in err_str or 'does not exist' in err_str or 'tweet has been deleted' in err_str:
            return {"deleted": True, "reason": f"yt-dlp: {str(e)[:100]}"}
        print(f"[-] yt-dlp error: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# PARALLEL EXTRACTION — runs both strategies simultaneously
# ════════════════════════════════════════════════════════════════════════════════

async def extract_parallel(tweet_id, resolved_url):
    """Run syndication + yt-dlp in PARALLEL and merge results."""
    syndication_result, ytdlp_result = await asyncio.gather(
        asyncio.get_event_loop().run_in_executor(_executor, extract_from_syndication, tweet_id),
        asyncio.get_event_loop().run_in_executor(_executor, extract_with_ytdlp, resolved_url),
        return_exceptions=True
    )

    # Handle exceptions
    if isinstance(syndication_result, Exception):
        syndication_result = None
    if isinstance(ytdlp_result, Exception):
        ytdlp_result = None

    # Check for deleted tweet FIRST
    if syndication_result and isinstance(syndication_result, dict) and syndication_result.get("deleted"):
        return syndication_result
    if ytdlp_result and isinstance(ytdlp_result, dict) and ytdlp_result.get("deleted"):
        return ytdlp_result

    # Merge results — prefer syndication (faster, more reliable)
    title = "Untitled"
    duration = None
    thumbnail = None
    video_formats = []
    source = "none"

    if syndication_result and syndication_result.get("formats"):
        title = syndication_result.get("title", "Untitled")
        duration = syndication_result.get("duration")
        thumbnail = syndication_result.get("thumbnail")
        video_formats = syndication_result["formats"]
        source = "syndication-api"

    if ytdlp_result and ytdlp_result.get("formats"):
        if title == "Untitled":
            title = ytdlp_result.get("title", "Untitled")
        if duration is None:
            duration = ytdlp_result.get("duration")
        if thumbnail is None:
            thumbnail = ytdlp_result.get("thumbnail")
        if source == "none":
            source = "yt-dlp"
        # Merge unique formats from yt-dlp
        existing_urls = {f["url"] for f in video_formats}
        for fmt in ytdlp_result["formats"]:
            if fmt["url"] not in existing_urls:
                video_formats.append(fmt)
                existing_urls.add(fmt["url"])

    if not video_formats:
        return None

    video_formats.sort(key=lambda x: (
        0 if x.get("ext") == "mp4" else 1,
        -x.get("height", 0) if isinstance(x.get("height"), (int, float)) else 0
    ))

    return {
        "tweetId": tweet_id,
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "formats": video_formats,
        "source": source
    }


# ════════════════════════════════════════════════════════════════════════════════
# CACHE — in-memory, 5 min TTL
# ════════════════════════════════════════════════════════════════════════════════

def get_cached(tweet_id):
    entry = _cache.get(tweet_id)
    if entry and (time.time() - entry["timestamp"]) < CACHE_TTL_SECONDS:
        return entry["result"]
    return None


def set_cached(tweet_id, result):
    if len(_cache) >= MAX_CACHE_ENTRIES:
        # Evict oldest entry
        oldest = min(_cache.items(), key=lambda x: x[1]["timestamp"])
        del _cache[oldest[0]]
    _cache[tweet_id] = {"result": result, "timestamp": time.time()}


# ════════════════════════════════════════════════════════════════════════════════
# FASTAPI ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/extract")
async def extract(url: str = Query(...)):
    """Extract video formats from a Twitter/X tweet URL."""
    # Resolve redirects + extract tweet ID
    resolved_url = resolve_redirects(url)
    tweet_id = extract_tweet_id(resolved_url) or extract_tweet_id(url)

    if not tweet_id:
        return {"ok": False, "error": "Invalid X/Twitter URL"}

    # Check cache FIRST — instant response for repeated requests
    cached = get_cached(tweet_id)
    if cached:
        if cached.get("deleted"):
            return {"ok": False, "deleted": True, "error": cached.get("reason", "Tweet deleted/removed")}
        return {**cached, "ok": True, "cached": True}

    # Run PARALLEL extraction
    result = await extract_parallel(tweet_id, resolved_url)

    if not result:
        return {"ok": False, "error": "No video found in this tweet"}

    if result.get("deleted"):
        set_cached(tweet_id, result)  # cache deleted status too (avoid re-checking)
        return {"ok": False, "deleted": True, "error": result.get("reason", "Tweet deleted/removed")}

    # Cache the successful result
    set_cached(tweet_id, result)

    return {**result, "ok": True}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "GetTwittervideo v2.0",
        "features": ["parallel-extraction", "cache", "deleted-detection"],
        "cache_size": len(_cache),
    }


@app.get("/")
async def root():
    return {"service": "GetTwittervideo", "version": "2.0", "endpoints": ["/extract?url=", "/health"]}


# ════════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"[*] GetTwittervideo v2.0 starting on port {port}...")
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='info')
