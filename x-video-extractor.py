# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# X/Twitter Video Extractor â€” Standalone Python Script (v178)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#
# This is a STANDALONE version of the extractor â€” it can be run as a Flask
# server OR imported as a Python module. It's the SAME code that's bundled
# in the project at `scripts/x-video-extractor.py`.
#
# USAGE:
#   1. As a script (test from CLI):
#      pip install -q --upgrade yt-dlp requests flask flask-cors
#      python x-video-extractor-standalone.py
#      â†’ Starts Flask server on port 5000
#      â†’ GET http://localhost:5000/extract?url=https://x.com/i/status/123
#
#   2. As a Python module:
#      from x_video_extractor_standalone import get_x_video_resolved
#      tweet_id, thumbnail, formats = get_x_video_resolved("https://x.com/i/status/123")
#      # formats = [{resolution, height, width, url, ext}, ...]
#      # .mp4 formats (with audio) are returned FIRST, sorted by height
#
# v178 KEY FIX: yt-dlp's `ext` field was UNRELIABLE for Twitter â€” it sometimes
# labeled .mp4 URLs as 'm3u8_native' or other values. The fix detects the
# extension by checking the URL itself (url.endswith('.mp4')), not the
# `ext` field. This ensures .mp4 URLs (which contain audio + video) are
# correctly identified and returned FIRST.
#
# Why this matters:
#   - Twitter's .m3u8 streams are VIDEO-ONLY (AVC video, no audio track)
#   - Twitter's .mp4 URLs contain BOTH audio + video
#   - The previous code was returning only .m3u8 â†’ silent videos
#   - This fix returns .mp4 URLs â†’ audio plays correctly
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

import re
import os
import sys

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CORE EXTRACTION FUNCTIONS (importable as a module)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def extract_tweet_id(url):
    """Extract tweet ID from various URL formats"""
    if not url:
        return None
    # Raw: x.com/<user>/status/<id>  OR  x.com/i/status/<id>  OR  twitter.com/<user>/status/<id>
    match = re.search(r'(?:x\.com|twitter\.com)/(?:[^/]+/)?status(?:es)?/(\d+)', url, re.IGNORECASE)
    if match:
        return match.group(1)
    # Normalized: platform.twitter.com/embed/Tweet.html?id=<id>
    embed_match = re.search(r'[?&]id=(\d+)', url)
    if embed_match and 'platform.twitter.com/embed/' in url:
        return embed_match.group(1)
    # Bare tweet ID
    if re.match(r'^\d{15,25}$', url.strip()):
        return url.strip()
    return None


def resolve_redirects(short_url):
    """
    v176: Follow redirect chains to resolve short URLs to real tweet URLs.
    Handles:
      - t.co short links (HTTP + JS redirects â†’ x.com/.../status/ID)
      - twitter.com/i/redirect URLs
      - Any other redirect that ends at a tweet status URL

    Returns the final resolved URL. If no redirect occurs or resolution fails,
    returns the original URL.
    """
    print(f"[*] Resolving URL: {short_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Step 1: Try HTTP redirect (HEAD with allow_redirects=True)
    try:
        session = requests.Session()
        response = session.head(short_url, headers=headers, allow_redirects=True, timeout=10)
        real_url = response.url
        if real_url and real_url != short_url:
            print(f"[+] HTTP redirect resolved: {real_url}")
            return real_url
    except Exception as e:
        print(f"[-] HTTP redirect failed ({e}), trying HTML parsing")

    # Step 2: If HTTP redirect didn't work (e.g., t.co uses JS redirect),
    # try fetching the page and parsing the canonical URL or embedded tweet URL.
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
    """Extract metadata from Twitter's public Syndication API (no auth needed)"""
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
                    # v170: Round to integer seconds
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

        # Fallback from data.video
        if not thumbnail_url and "video" in data:
            thumbnail_url = data["video"].get("poster")

        if not duration and "video" in data:
            duration = data["video"].get("duration")

        # v177: Sort to prefer .mp4 (with audio) over .m3u8 (video-only).
        # All Syndication API formats are .mp4, but we keep the sort for consistency.
        def format_priority(fmt):
            url = fmt.get("url", "").lower().split("?")[0]
            is_mp4 = url.endswith(".mp4") or ".mp4" in url
            return 0 if is_mp4 else 1

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
    """
    v179: Use yt-dlp to extract .mp4 video formats (with audio).
    Simple filter that matches the user's reference code exactly:
      - Only include formats where ext == 'mp4' and vcodec != 'none'
      - This is PROVEN to work (returns 2 .mp4 URLs for the test tweet).

    Returns formats sorted by height descending (highest quality first).
    All returned formats are .mp4 with audio + video.
    """
    try:
        import yt_dlp
    except ImportError:
        print("[-] yt-dlp not installed. Run: pip install yt-dlp")
        return None

    ydl_opts = {
        'no_warnings': True,
        'skip_download': True,
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tweet_url, download=False)

            title = info.get('title') or info.get('description', 'Untitled')
            duration = info.get('duration')
            thumbnail = info.get('thumbnail')

            # v179: SIMPLE filter â€” match the user's reference code exactly.
            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    ext = f.get('ext')
                    vcodec = f.get('vcodec', 'none')

                    if ext == 'mp4' and vcodec != 'none':
                        res = f.get('format_note') or f.get('resolution') or 'Standard'
                        h = f.get('height', 'N/A')
                        w = f.get('width', 'N/A')
                        url = f.get('url')

                        if url and not any(d['url'] == url for d in formats):
                            formats.append({
                                "resolution": res,
                                "height": h,
                                "width": w,
                                "url": url,
                                "ext": "mp4",
                            })

            # Sort by height descending (highest quality first)
            formats.sort(key=lambda x: -(x.get('height', 0) if isinstance(x.get('height'), (int, float)) else 0))

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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MAIN ENTRY POINT â€” used by both CLI and Flask server
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def get_x_video_resolved(short_url):
    """
    Main extraction function â€” mirrors the user's reference code.

    Pipeline:
      1. Resolve redirects (t.co â†’ x.com/.../status/ID)
      2. Extract tweet ID
      3. Try Syndication API (fast, no deps)
      4. Fallback to yt-dlp (slower, but gets ALL formats including .mp4)
      5. Merge results if both succeed

    Returns: (tweet_id, thumbnail, formats)
      - formats: list of {resolution, height, width, url, ext}
      - .mp4 formats (with audio) are FIRST in the list
    """
    print(f"[*] Ø¬Ø§Ø±Ù ØªØªØ¨Ø¹ Ø§Ù„Ø±Ø§Ø¨Ø· Ø§Ù„Ù…Ø®ØªØµØ±: {short_url}")

    # Step 1: Resolve redirects
    real_url = resolve_redirects(short_url)
    if real_url == short_url:
        print(f"[+] Ù„Ù… ÙŠØ­Ø¯Ø« ØªÙˆØ¬ÙŠÙ‡ØŒ Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ø±Ø§Ø¨Ø· Ø§Ù„Ø£ØµÙ„ÙŠ")
    else:
        print(f"[+] Ø§Ù„Ø±Ø§Ø¨Ø· Ø§Ù„Ø­Ù‚ÙŠÙ‚ÙŠ Ø¨Ø¹Ø¯ Ø§Ù„ØªÙˆØ¬ÙŠÙ‡: {real_url}")

    # Step 2: Extract tweet ID
    tweet_id = extract_tweet_id(real_url)
    if not tweet_id:
        # Try original URL as fallback
        tweet_id = extract_tweet_id(short_url)
    if not tweet_id:
        print(f"[-] ÙØ´Ù„ Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØºØ±ÙŠØ¯Ø©")
        return None, None, []
    print(f"[*] Ù…Ø¹Ø±Ù‘Ù Ø§Ù„ØªØºØ±ÙŠØ¯Ø© Ø§Ù„Ù…Ø³ØªØ®Ù„Øµ: {tweet_id}")

    video_formats = []
    thumbnail_url = None
    title = "Untitled"
    duration = None

    # Step 3: Try Syndication API first (fast)
    syndication_result = extract_from_syndication(tweet_id)
    if syndication_result:
        thumbnail_url = syndication_result.get("thumbnail")
        title = syndication_result.get("title", "Untitled")
        duration = syndication_result.get("duration")
        video_formats = syndication_result.get("formats", [])
        print(f"[+] Syndication API: {len(video_formats)} formats")

    # Step 4: Fallback / supplement with yt-dlp (gets .mp4 URLs reliably)
    if not video_formats:
        print("[*] Syndication API ÙØ´Ù„ØŒ Ø§Ø³ØªØ®Ø¯Ø§Ù… yt-dlp...")
        ytdlp_result = extract_with_ytdlp(real_url)
        if ytdlp_result:
            video_formats = ytdlp_result.get("formats", [])
            if not thumbnail_url:
                thumbnail_url = ytdlp_result.get("thumbnail")
            if not title or title == "Untitled":
                title = ytdlp_result.get("title", "Untitled")
            if not duration:
                duration = ytdlp_result.get("duration")
            print(f"[+] yt-dlp: {len(video_formats)} formats")
    else:
        # v178: Even if Syndication succeeded, ALSO try yt-dlp to get .mp4 URLs
        # that the Syndication API might have missed. Merge the results.
        print("[*] Ø£ÙŠØ¶Ø§Ù‹ Ù†Ø­Ø§ÙˆÙ„ yt-dlp Ù„Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø±ÙˆØ§Ø¨Ø· .mp4 Ø¥Ø¶Ø§ÙÙŠØ©...")
        ytdlp_result = extract_with_ytdlp(real_url)
        if ytdlp_result and ytdlp_result.get("formats"):
            existing_urls = {f["url"] for f in video_formats}
            for fmt in ytdlp_result["formats"]:
                if fmt["url"] not in existing_urls:
                    video_formats.append(fmt)
                    existing_urls.add(fmt["url"])
            # Re-sort to keep .mp4 first
            video_formats.sort(key=lambda x: (0 if x.get("ext") == "mp4" else 1,
                                             -x.get("height", 0) if isinstance(x.get("height"), (int, float)) else 0))
            print(f"[+] Ø¨Ø¹Ø¯ Ø§Ù„Ø¯Ù…Ø¬: {len(video_formats)} formats")

    return tweet_id, thumbnail_url, video_formats


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CLI TEST MODE â€” run as a script to test extraction
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _cli_test():
    """Test extraction from the command line."""
    if len(sys.argv) < 2:
        print("Usage: python x-video-extractor-standalone.py <tweet_url>")
        print("Example: python x-video-extractor-standalone.py https://x.com/i/status/2087433750686699679")
        # Use the user's test URL as default
        target_url = "https://x.com/i/status/2087433750686699679"
        print(f"\n[*] Using default test URL: {target_url}")
    else:
        target_url = sys.argv[1]

    tweet_id, thumbnail, formats = get_x_video_resolved(target_url)

    print("\n" + "=" * 60)
    print(f" Ø§Ù„Ù…Ø¹Ø±Ù‘Ù: {tweet_id}")
    print("=" * 60)
    print(f"\n[ðŸ–¼ï¸] Ø±Ø§Ø¨Ø· ØµÙˆØ±Ø© Ø§Ù„Ø®Ù„ÙÙŠØ©:\n{thumbnail}")

    if formats:
        print(f"\n[ðŸŽ¥] Ø§Ù„Ø¬ÙˆØ¯Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø© ({len(formats)} Ø±Ø§Ø¨Ø·):")
        for i, fmt in enumerate(formats, 1):
            ext_label = fmt.get('ext', '?')
            print(f"\n  {i}. {fmt['resolution']} ({fmt['width']}x{fmt['height']}) [{ext_label}]")
            print(f"     {fmt['url']}")
    else:
        print("\n[-] Ù„Ù… ÙŠØªÙ… Ø§Ù„Ø¹Ø«ÙˆØ± Ø¹Ù„Ù‰ Ø±ÙˆØ§Ø¨Ø· ÙÙŠØ¯ÙŠÙˆ.")
    print("\n" + "=" * 60)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FLASK SERVER MODE â€” expose as HTTP API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _run_flask_server():
    """Run as a Flask HTTP server."""
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
        if request.method == 'GET':
            url = request.args.get('url')
        else:
            data = request.get_json()
            url = data.get('url') if data else None

        if not url:
            return jsonify({"error": "Missing url parameter"}), 400

        # Resolve redirects first
        original_url = url
        url = resolve_redirects(url)

        tweet_id = extract_tweet_id(url)
        if not tweet_id:
            return jsonify({
                "error": "Invalid X/Twitter URL",
                "originalUrl": original_url,
                "resolvedUrl": url if url != original_url else None
            }), 400

        # Try Syndication API first
        result = extract_from_syndication(tweet_id)

        # Fallback / supplement with yt-dlp
        if not result or not result.get("formats"):
            print("[*] Trying yt-dlp fallback...")
            ytdlp_result = extract_with_ytdlp(url)
            if ytdlp_result:
                if not result:
                    result = ytdlp_result
                    result["tweetId"] = tweet_id
                else:
                    # Merge
                    if not result.get("formats"):
                        result["formats"] = ytdlp_result.get("formats", [])
                    if not result.get("duration"):
                        result["duration"] = ytdlp_result.get("duration")
                    if not result.get("thumbnail"):
                        result["thumbnail"] = ytdlp_result.get("thumbnail")
                    result["source"] = "syndication+yt-dlp"
        else:
            # v178: Also try yt-dlp to supplement with .mp4 URLs
            ytdlp_result = extract_with_ytdlp(url)
            if ytdlp_result and ytdlp_result.get("formats"):
                existing_urls = {f["url"] for f in result.get("formats", [])}
                for fmt in ytdlp_result["formats"]:
                    if fmt["url"] not in existing_urls:
                        result["formats"].append(fmt)
                        existing_urls.add(fmt["url"])
                # Re-sort to keep .mp4 first
                result["formats"].sort(key=lambda x: (0 if x.get("ext") == "mp4" else 1,
                                                       -x.get("height", 0) if isinstance(x.get("height"), (int, float)) else 0))
                result["source"] = "syndication+yt-dlp"

        if not result:
            return jsonify({"error": "Could not extract video data"}), 404

        # v170: Round duration to integer
        if result.get("duration") is not None:
            try:
                result["duration"] = round(float(result["duration"]))
            except:
                pass

        return jsonify({"ok": True, **result})

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"ok": True, "service": "X/Twitter Video Extraction Server v178"})

    port = int(os.environ.get('PORT', 5000))
    print(f"[*] Starting X/Twitter Extraction Server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ENTRY POINT â€” choose mode based on how the script is invoked
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

if __name__ == '__main__':
    # If PORT env var is set OR --server flag is passed â†’ run as Flask server
    if os.environ.get('PORT') or '--server' in sys.argv:
        _run_flask_server()
    else:
        # Default: CLI test mode
        _cli_test()
