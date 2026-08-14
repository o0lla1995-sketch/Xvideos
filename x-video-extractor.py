# ════════════════════════════════════════════════════════════════════════════════
# X/Twitter Video Extractor — Standalone Python Script (v182 - Secure Render Env Cookies)
# ════════════════════════════════════════════════════════════════════════════════
#
# USAGE:
#   1. As a script (test from CLI):
#      python x-video-extractor-standalone.py <tweet_url>
#
#   2. As a Flask server:
#      python x-video-extractor-standalone.py --server
# ════════════════════════════════════════════════════════════════════════════════

import re
import os
import sys

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


# ════════════════════════════════════════════════════════════════════════════════
# SECURE CONFIGURATION (Environment Variables for Render)
# ════════════════════════════════════════════════════════════════════════════════
# سيقوم السكربت بقراءة الكوكيز من بيئة التشغيل (Render Environment Variables)
# وإذا لم تجدها (للاختبار المحلي)، يمكنك وضع القيم الاحتياطية هنا أو تركها فارغة
TWITTER_AUTH_TOKEN = os.environ.get("TWITTER_AUTH_TOKEN", "ضع_رمز_auth_token_هنا_إن_أردت_محلياً")
TWITTER_CT0        = os.environ.get("TWITTER_CT0", "ضع_رمز_ct0_هنا_إن_أردت_محلياً")

COOKIES_FILE_PATH = "cookies.txt"

def setup_cookies_file():
    """توليد ملف cookies.txt تلقائياً من متغيرات البيئة الآمنة"""
    try:
        if not TWITTER_AUTH_TOKEN or "ضع_رمز" in TWITTER_AUTH_TOKEN:
            return None
            
        netscape_content = (
            "# Netscape HTTP Cookie File\n"
            f".x.com\tTRUE\t/\tTRUE\t1800000000\tauth_token\t{TWITTER_AUTH_TOKEN}\n"
            f".x.com\tTRUE\t/\tFALSE\t1800000000\tct0\t{TWITTER_CT0}\n"
        )
        with open(COOKIES_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(netscape_content)
        return COOKIES_FILE_PATH
    except Exception as e:
        print(f"[-] تحذير: تعذر إنشاء ملف الكوكيز: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# CORE EXTRACTION FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════════

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
    print(f"[*] Resolving URL: {short_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        session = requests.Session()
        response = session.head(short_url, headers=headers, allow_redirects=True, timeout=10)
        real_url = response.url
        if real_url and real_url != short_url:
            print(f"[+] HTTP redirect resolved: {real_url}")
            return real_url
    except Exception as e:
        print(f"[-] HTTP redirect failed ({e}), trying HTML parsing")

    try:
        response = requests.get(short_url, headers=headers, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            html = response.text
            canonical_match = re.search(r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if canonical_match and re.search(r'x\.com|twitter\.com', canonical_match.group(1), re.IGNORECASE):
                return canonical_match.group(1)
            tweet_match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', html, re.IGNORECASE)
            if tweet_match:
                return f"https://x.com/i/status/{tweet_match.group(1)}"
    except Exception as e:
        print(f"[-] HTML parsing failed: {e}")

    return short_url


def extract_from_syndication(tweet_id):
    """استخراج بيانات التغريدة مع العنوان من واجهة Syndication API مع الكوكيز الآمنة"""
    api_url = f"https://cdn.syndication.twimg.com/tweet-item?id={tweet_id}&lang=en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    if TWITTER_AUTH_TOKEN and "ضع_رمز" not in TWITTER_AUTH_TOKEN:
        headers["Cookie"] = f"auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}"

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
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
                        bitrate = v.get("bitrate", 0)
                        video_formats.append({
                            "resolution": f"{round(bitrate/1000)}kbps" if bitrate else "Standard",
                            "height": "N/A",
                            "width": "N/A",
                            "url": v["url"].split("?tag=")[0],
                            "ext": "mp4",
                        })

        if not thumbnail_url and "video" in data:
            thumbnail_url = data["video"].get("poster")
        if not duration and "video" in data:
            duration = data["video"].get("duration")

        def format_priority(fmt):
            url = fmt.get("url", "").lower().split("?")[0]
            return 0 if (url.endswith(".mp4") or ".mp4" in url) else 1

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
            "source": "syndication-api-env-cookie"
        }

    except Exception as e:
        print(f"[-] Syndication error: {e}")
        return None


def extract_with_ytdlp(tweet_url):
    """استخدام yt-dlp مع ملف الكوكيز الآمن"""
    try:
        import yt_dlp
    except ImportError:
        print("[-] yt-dlp not installed. Run: pip install yt-dlp")
        return None

    cookie_file = setup_cookies_file()

    ydl_opts = {
        'no_warnings': True,
        'skip_download': True,
        'quiet': True,
    }

    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)

            title = info.get('title') or info.get('description', 'Untitled')
            duration = info.get('duration')
            thumbnail = info.get('thumbnail')

            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    url = f.get('url') or ''
                    if not url:
                        continue

                    url_clean = url.split('?')[0].lower()
                    is_mp4 = url_clean.endswith('.mp4')

                    if not is_mp4:
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

            return {
                "title": title,
                "duration": duration,
                "thumbnail": thumbnail,
                "formats": formats,
                "source": "yt-dlp-env-cookie"
            }

    except Exception as e:
        print(f"[-] yt-dlp error: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════════

def get_x_video_resolved(short_url):
    print(f"[*] جاري تتبع الرابط المختصر: {short_url}")

    real_url = resolve_redirects(short_url)
    tweet_id = extract_tweet_id(real_url) or extract_tweet_id(short_url)
    if not tweet_id:
        print(f"[-] فشل استخراج معرف التغريدة")
        return None, None, None, []

    video_formats = []
    thumbnail_url = None
    title = "Untitled"
    duration = None

    syndication_result = extract_from_syndication(tweet_id)
    if syndication_result:
        thumbnail_url = syndication_result.get("thumbnail")
        title = syndication_result.get("title", "Untitled")
        duration = syndication_result.get("duration")
        video_formats = syndication_result.get("formats", [])

    if not video_formats:
        print("[*] Syndication API فشل، استخدام yt-dlp...")
        ytdlp_result = extract_with_ytdlp(real_url)
        if ytdlp_result:
            video_formats = ytdlp_result.get("formats", [])
            thumbnail_url = thumbnail_url or ytdlp_result.get("thumbnail")
            title = title if title != "Untitled" else ytdlp_result.get("title", "Untitled")
            duration = duration or ytdlp_result.get("duration")
    else:
        ytdlp_result = extract_with_ytdlp(real_url)
        if ytdlp_result and ytdlp_result.get("formats"):
            if title == "Untitled":
                title = ytdlp_result.get("title", "Untitled")
            existing_urls = {f["url"] for f in video_formats}
            for fmt in ytdlp_result["formats"]:
                if fmt["url"] not in existing_urls:
                    video_formats.append(fmt)
                    existing_urls.add(fmt["url"])
            video_formats.sort(key=lambda x: (0 if x.get("ext") == "mp4" else 1,
                                             -x.get("height", 0) if isinstance(x.get("height"), (int, float)) else 0))

    return tweet_id, title, thumbnail_url, video_formats


# ════════════════════════════════════════════════════════════════════════════════
# CLI TEST MODE
# ════════════════════════════════════════════════════════════════════════════════

def _cli_test():
    if len(sys.argv) < 2:
        target_url = "https://x.com/i/status/2088244067482427507"
        print(f"\n[*] Using default test URL: {target_url}")
    else:
        target_url = sys.argv[1]

    tweet_id, title, thumbnail, formats = get_x_video_resolved(target_url)

    print("\n" + "=" * 60)
    print(f" المعرّف: {tweet_id}")
    print(f" العنوان: {title}")
    print("=" * 60)
    print(f"\n[🖼️] رابط صورة الخلفية:\n{thumbnail}")

    if formats:
        print(f"\n[🎥] الجودات المتاحة ({len(formats)} رابط):")
        for i, fmt in enumerate(formats, 1):
            ext_label = fmt.get('ext', '?')
            print(f"\n  {i}. {fmt['resolution']} ({fmt['width']}x{fmt['height']}) [{ext_label}]")
            print(f"     {fmt['url']}")
    else:
        print("\n[-] لم يتم العثور على روابط فيديو.")
    print("\n" + "=" * 60)


# ════════════════════════════════════════════════════════════════════════════════
# FLASK SERVER MODE
# ════════════════════════════════════════════════════════════════════════════════

def _run_flask_server():
    try:
        from flask import Flask, request, jsonify
        from flask_cors import CORS
    except ImportError:
        print("ERROR: Flask not installed. Run: pip install flask flask-cors")
        sys.exit(1)

    app = Flask(__name__)
    CORS(app)

    @app.route('/extract', methods=['GET', 'POST'])
    def extract():
        url = request.args.get('url') if request.method == 'GET' else (request.get_json() or {}).get('url')

        if not url:
            return jsonify({"error": "Missing url parameter"}), 400

        original_url = url
        resolved_url = resolve_redirects(url)
        tweet_id = extract_tweet_id(resolved_url)

        if not tweet_id:
            return jsonify({
                "error": "Invalid X/Twitter URL",
                "originalUrl": original_url,
                "resolvedUrl": resolved_url
            }), 400

        tweet_id, title, thumbnail, formats = get_x_video_resolved(resolved_url)

        if not formats:
            return jsonify({"error": "Could not extract video data"}), 404

        result = {
            "ok": True,
            "tweetId": tweet_id,
            "title": title,
            "thumbnail": thumbnail,
            "formats": formats,
            "source": "python-standalone-env-cookie-server"
        }

        return jsonify(result)

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"ok": True, "service": "X/Twitter Video Extraction Server v182 (Secure Env Cookies)"})

    port = int(os.environ.get('PORT', 5000))
    print(f"[*] Starting X/Twitter Extraction Server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    if os.environ.get('PORT') or '--server' in sys.argv:
        _run_flask_server()
    else:
        _cli_test()
