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
    match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status/(\d+)', url, re.IGNORECASE)
    if match:
        return match.group(1)
    if re.match(r'^\d{15,25}$', url.strip()):
        return url.strip()
    return None

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
                    duration = round(media["video_info"]["duration_millis"] / 1000, 2)

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

        # Sort by bitrate (highest first)
        video_formats.sort(key=lambda x: int(x.get("resolution", "0").replace("kbps", "")) if "kbps" in x.get("resolution", "") else 0, reverse=True)

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

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return jsonify({"error": "Invalid X/Twitter URL"}), 400

    # Step 1: Try Syndication API (fast, no dependencies)
    result = extract_from_syndication(tweet_id)

    # Step 2: Fallback to yt-dlp if Syndication failed or no formats found
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
