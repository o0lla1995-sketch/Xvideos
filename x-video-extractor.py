# ═══════════════════════════════════════════════════════════════════════════
# X/Twitter Video Extraction Server — Python (v166)
# ═══════════════════════════════════════════════════════════════════════════
#
# Deploy on: Render.com / Railway / any Python server
# Requirements: pip install flask flask-cors yt-dlp requests
#
# USAGE:
#   GET /extract?url=https://x.com/user/status/1234567890
#   Returns: { title, duration, thumbnail, formats: [{resolution, url}] }
#
# ═══════════════════════════════════════════════════════════════════════════

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import os

app = Flask(__name__)
CORS(app)

def extract_tweet_id(url):
    """Extract tweet ID from various URL formats"""
    if not url:
        return None
    match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', url, re.IGNORECASE)
    if match:
        return match.group(1)
    # Normalized: platform.twitter.com/embed/Tweet.html?id=<id>
    embed_match = re.search(r'[?&]id=(\d+)', url)
    if embed_match and 'platform.twitter.com/embed/' in url:
        return embed_match.group(1)
    if re.match(r'^\d{15,25}$', url.strip()):
        return url.strip()
    return None

def resolve_redirects(short_url):
    """
    v176: Follow redirect chains to resolve short URLs to real tweet URLs.
    Handles:
      - t.co short links (HTTP + JS redirects → x.com/.../status/ID)
      - twitter.com/i/redirect URLs
      - Any other redirect that ends at a tweet status URL

    Returns the final resolved URL. If no redirect occurs or resolution fails,
    returns the original URL.
    """
    print(f"[*] Resolving URL: {short_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        session = requests.Session()
        # allow_redirects=True follows the full HTTP redirect chain automatically
        response = session.head(short_url, headers=headers, allow_redirects=True, timeout=10)
        real_url = response.url
        if real_url and real_url != short_url:
            print(f"[+] HTTP redirect resolved: {real_url}")
            return real_url
    except Exception as e:
        print(f"[-] HTTP redirect failed ({e}), trying HTML parsing")

    # If HTTP redirect didn't work (e.g., t.co uses JS redirect), try fetching
    # the page and parsing the canonical URL or embedded tweet URL.
    try:
        response = requests.get(short_url, headers=headers, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            html = response.text
            # Try canonical URL
            canonical_match = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if canonical_match and re.search(r'x\.com|twitter\.com', canonical_match.group(1), re.IGNORECASE):
                print(f"[+] Canonical URL resolved: {canonical_match.group(1)}")
                return canonical_match.group(1)
            # Try meta refresh
            refresh_match = re.search(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\']+)["\']', html, re.IGNORECASE)
            if refresh_match:
                refresh_url = refresh_match.group(1).strip()
                if re.search(r'x\.com|twitter\.com', refresh_url, re.IGNORECASE):
                    print(f"[+] Meta refresh resolved: {refresh_url}")
                    return refresh_url
            # Try finding tweet URL in the HTML
            tweet_match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', html, re.IGNORECASE)
            if tweet_match:
                resolved = f"https://x.com/i/status/{tweet_match.group(1)}"
                print(f"[+] Tweet URL extracted from HTML: {resolved}")
                return resolved
    except Exception as e:
        print(f"[-] HTML parsing failed: {e}")

    return short_url

def extract_from_syndication(tweet_id):
    """Extract metadata from Twitter's public Syndication API"""
    api_url = f"https://cdn.syndication.twimg.com/tweet-item?id={tweet_id}&lang=en"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()

        video_title = data.get("text", "Untitled")
        duration = None
        thumbnail_url = None
        video_formats = []

        # Extract from mediaDetails
        if "mediaDetails" in data and len(data["mediaDetails"]) > 0:
            media = data["mediaDetails"][0]
            thumbnail_url = media.get("media_url_https")

            if "video_info" in media:
                if "duration_millis" in media["video_info"]:
                    # v170: Round to integer seconds — the VideoManager form
                    # expects an integer for the `duration` field, and HTML5
                    # <video> doesn't support fractional durations either.
                    duration = round(media["video_info"]["duration_millis"] / 1000)

                for v in media["video_info"].get("variants", []):
                    if v.get("content_type") == "mp4" and v.get("url"):
                        bitrate = v.get("bitrate", 0)
                        video_formats.append({
                            "resolution": f"{round(bitrate/1000)}kbps" if bitrate else "Standard",
                            "height": "N/A",
                            "width": "N/A",
                            "url": v["url"].split("?tag=")[0]
                        })

        # Fallback from data.video
        if not thumbnail_url and "video" in data:
            thumbnail_url = data["video"].get("poster")

        if not duration and "video" in data:
            duration = data["video"].get("duration")

        # v177: Sort to prefer .mp4 (with audio) over .m3u8 (video-only on Twitter).
        # Twitter's .m3u8 streams are often video-only (AVC video, no audio),
        # while .mp4 variants contain both audio + video. Putting .mp4 first
        # ensures the player picks the format with sound.
        def format_priority(fmt):
            url = fmt.get("url", "").lower().split("?")[0]
            is_mp4 = url.endswith(".mp4") or ".mp4" in url
            # .mp4 → priority 0 (first), .m3u8 → priority 1 (after)
            return (0 if is_mp4 else 1,)

        # Sort by (1) extension (.mp4 first), then (2) bitrate (highest first)
        def bitrate_key(fmt):
            res = fmt.get("resolution", "0")
            if "kbps" in res:
                try:
                    return int(res.replace("kbps", ""))
                except:
                    return 0
            return 0

        video_formats.sort(key=lambda x: (format_priority(x), -bitrate_key(x)))

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

def extract_with_ytdlp(tweet_url):
    """Fallback: use yt-dlp for complete metadata"""
    try:
        import yt_dlp
        ydl_opts = {
            'no_warnings': True,
            'skip_download': True,
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)

            title = info.get('title') or info.get('description', 'Untitled')
            duration = info.get('duration')
            thumbnail = info.get('thumbnail')

            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    ext = f.get('ext')
                    vcodec = f.get('vcodec', 'none')
                    acodec = f.get('acodec', 'none')

                    # v177: Only include formats with VIDEO codec (skip audio-only)
                    if vcodec == 'none':
                        continue

                    # v177: Skip .m3u8 (HLS) formats when we have .mp4 alternatives.
                    # Twitter's .m3u8 streams are often video-only (no audio),
                    # while .mp4 variants contain both audio + video.
                    # Only include .m3u8 if it has an audio codec (rare on Twitter).
                    if ext == 'm3u8' and acodec == 'none':
                        continue

                    # Prefer .mp4 with both video + audio
                    if ext == 'mp4' and vcodec != 'none':
                        res_note = f.get('format_note') or f.get('resolution') or 'Standard'
                        h = f.get('height', 'N/A')
                        w = f.get('width', 'N/A')
                        url = f.get('url')

                        if url and not any(d['url'] == url for d in formats):
                            formats.append({
                                "resolution": res_note,
                                "height": h,
                                "width": w,
                                "url": url
                            })

                # v177: Sort formats to prefer ones with audio (acodec != 'none')
                # and higher resolution. .mp4 with audio comes first.
                def format_priority(fmt):
                    url = fmt.get("url", "").lower().split("?")[0]
                    is_mp4 = url.endswith(".mp4") or ".mp4" in url
                    return 0 if is_mp4 else 1

                formats.sort(key=lambda x: format_priority(x))

            return {
                "title": title,
                "duration": duration,
                "thumbnail": thumbnail,
                "formats": formats,
                "source": "yt-dlp"
            }

    except Exception as e:
        print(f"[-] yt-dlp error: {e}")
        return None

@app.route('/extract', methods=['GET', 'POST'])
def extract():
    url = None
    if request.method == 'GET':
        url = request.args.get('url')
    else:
        data = request.get_json()
        url = data.get('url') if data else None

    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    # v176: Resolve short links (t.co, redirect URLs) → real tweet URL.
    # This is critical because Syndication API + yt-dlp need the real tweet ID.
    # Without this, t.co short links fail with "Invalid X/Twitter URL".
    original_url = url
    url = resolve_redirects(url)

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return jsonify({
            "error": "Invalid X/Twitter URL",
            "originalUrl": original_url,
            "resolvedUrl": url if url != original_url else None
        }), 400

    # Step 1: Try Syndication API (fast, no dependencies)
    result = extract_from_syndication(tweet_id)

    # Step 2: Fallback to yt-dlp if Syndication failed or no formats found.
    # Pass the RESOLVED URL (not the original) — yt-dlp also follows redirects
    # internally, but passing the resolved URL saves a round-trip and ensures
    # we hit the right tweet.
    if not result or not result.get("formats"):
        print("[*] Trying yt-dlp fallback...")
        ytdlp_result = extract_with_ytdlp(url)

        if ytdlp_result:
            if not result:
                result = ytdlp_result
                result["tweetId"] = tweet_id
            else:
                # Merge: use Syndication title, yt-dlp formats
                if not result.get("formats"):
                    result["formats"] = ytdlp_result.get("formats", [])
                if not result.get("duration"):
                    result["duration"] = ytdlp_result.get("duration")
                if not result.get("thumbnail"):
                    result["thumbnail"] = ytdlp_result.get("thumbnail")
                result["source"] = "syndication+yt-dlp"

    if not result:
        return jsonify({"error": "Could not extract video data"}), 404

    return jsonify({"ok": True, **result})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"ok": True, "service": "X/Twitter Video Extraction Server"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
