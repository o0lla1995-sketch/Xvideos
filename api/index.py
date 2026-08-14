# ════════════════════════════════════════════════════════════════════════════════
# X/Twitter Video Extractor — Vercel Python Serverless Function (index.py)
# ════════════════════════════════════════════════════════════════════════════════

import re
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    import requests
except ImportError:
    requests = None

app = Flask(__name__)
CORS(app)

# ════════════════════════════════════════════════════════════════════════════════
# SECURE CONFIGURATION (Vercel Environment Variables)
# ════════════════════════════════════════════════════════════════════════════════
TWITTER_AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "")
TWITTER_CT0        = os.environ.get("TWITTER_CT0", "")


def extract_tweet_id(url):
    """استخراج معرف التغريدة من مختلف صيغ الروابط"""
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
    """تتبع روابط التوجيه المختصرة للوصول إلى الرابط الحقيقي للتغريدة"""
    if not requests:
        return short_url
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        session = requests.Session()
        response = session.head(short_url, headers=headers, allow_redirects=True, timeout=8)
        real_url = response.url
        if real_url and real_url != short_url:
            return real_url
    except Exception:
        pass

    try:
        response = requests.get(short_url, headers=headers, timeout=8, allow_redirects=True)
        if response.status_code == 200:
            html = response.text
            canonical_match = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if canonical_match and re.search(r'x\.com|twitter\.com', canonical_match.group(1), re.IGNORECASE):
                return canonical_match.group(1)
            tweet_match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', html, re.IGNORECASE)
            if tweet_match:
                return f"https://x.com/i/status/{tweet_match.group(1)}"
    except Exception:
        pass

    return short_url


def extract_from_syndication(tweet_id):
    """استخراج بيانات التغريدة والمدة من واجهة Syndication API"""
    if not requests:
        return None

    api_url = f"https://cdn.syndication.twimg.com/tweet-item?id={tweet_id}&lang=en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    if TWITTER_AUTH_TOKEN:
        headers["Cookie"] = f"auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}"

    try:
        response = requests.get(api_url, headers=headers, timeout=8)
        if response.status_code != 200:
            return None

        data = response.json()
        video_title = data.get("text", "Untitled")
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
                    if v.get("content_type") == "mp4" and v.get("url"):
                        clean_url = v.get("url").split("?tag=")[0]
                        dim_match = re.search(r'/(\d+)x(\d+)/', clean_url)
                        width = int(dim_match.group(1)) if dim_match else 0
                        height = int(dim_match.group(2)) if dim_match else 0
                        resolution = f"{width}x{height}" if width and height else "Standard"

                        video_formats.append({
                            "ext": "mp4",
                            "height": height,
                            "resolution": resolution,
                            "url": clean_url,
                            "width": width
                        })

        if not thumbnail_url and "video" in data:
            thumbnail_url = data["video"].get("poster")
        if duration is None and "video" in data:
            try:
                duration = round(float(data["video"].get("duration", 0)))
            except:
                pass

        video_formats.sort(key=lambda x: x.get("height", 0), reverse=True)

        return {
            "tweetId": tweet_id,
            "title": video_title,
            "duration": int(duration) if duration is not None else None,
            "thumbnail": thumbnail_url,
            "formats": video_formats,
            "source": "vercel-python-syndication"
        }

    except Exception:
        return None


def extract_from_html_page(tweet_url, tweet_id):
    """محاولة احتياطية لسحب البيانات من صفحة الـ HTML المباشرة"""
    if not requests:
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml"
        }
        response = requests.get(tweet_url, headers=headers, timeout=8)
        if response.status_code != 200:
            return None

        html = response.text

        title_match = re.search(r'<meta[^>]*property=["\']og:title["'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        title = title_match.group(1) if title_match else "Untitled"

        thumb_match = re.search(r'<meta[^>]*property=["\']og:image["'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        thumbnail = thumb_match.group(1) if thumb_match else None

        duration = None
        dur_match = re.search(r'"duration_millis"\s*:\s*(\d+)', html) or re.search(r'"duration"\s*:\s*([\d.]+)', html)
        if dur_match:
            val = float(dur_match.group(1))
            duration = round(val / 1000) if val > 1000 else round(val)

        mp4_matches = re.findall(r'https?://[^\s<>"]+?/amplify_video/[^\s<>"]+?\.mp4[^\s<>"]*', html)
        video_matches = re.findall(r'https?://[^\s<>"]+?/ext_tw_video/[^\s<>"]+?\.mp4[^\s<>"]*', html)
        
        all_links = list(set(mp4_matches + video_matches))
        all_links = [link.replace("&amp;", "&") for link in all_links]

        if not all_links:
            return None

        video_formats = []
        for link in all_links:
            clean_url = link.split("?")[0]
            dim_match = re.search(r'/(\d+)x(\d+)/', clean_url)
            width = int(dim_match.group(1)) if dim_match else 0
            height = int(dim_match.group(2)) if dim_match else 0
            resolution = f"{width}x{height}" if width and height else "Standard"

            video_formats.append({
                "ext": "mp4",
                "height": height,
                "resolution": resolution,
                "url": clean_url,
                "width": width
            })

        video_formats.sort(key=lambda x: x.get("height", 0), reverse=True)

        return {
            "tweetId": tweet_id,
            "title": title,
            "duration": int(duration) if duration is not None else None,
            "thumbnail": thumbnail,
            "formats": video_formats,
            "source": "vercel-python-html-fallback"
        }
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@app.route('/extract', methods=['GET', 'POST'])
def extract():
    target_url = request.args.get('url') if request.method == 'GET' else (request.get_json() or {}).get('url')

    if not target_url:
        return jsonify({"error": "Missing url parameter"}), 400

    resolved_url = resolve_redirects(target_url)
    tweet_id = extract_tweet_id(resolved_url) or extract_tweet_id(target_url)

    if not tweet_id:
        return jsonify({"error": "Invalid X/Twitter URL", "originalUrl": target_url}), 400

    result = extract_from_syndication(tweet_id)

    if not result or not result.get("formats"):
        result = extract_from_html_page(resolved_url, tweet_id)

    if not result or not result.get("formats"):
        return jsonify({"error": "Could not extract video data"}), 404

    duration_value = result.get("duration")
    duration_final = int(duration_value) if duration_value is not None else None

    final_response = {
        "duration": duration_final,
        "formats": result["formats"],
        "ok": True,
        "source": result.get("source", "vercel-python"),
        "thumbnail": result.get("thumbnail"),
        "title": result.get("title", "Untitled"),
        "tweetId": tweet_id
    }

    return jsonify(final_response)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"ok": True, "service": "X/Twitter Video Extraction Server - Vercel Python"})
