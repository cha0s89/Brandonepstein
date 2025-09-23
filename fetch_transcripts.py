import os
import sys
import time
import json
import requests
from pathlib import Path
from tqdm import tqdm
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_HANDLE = os.getenv("CHANNEL_HANDLE", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
LANGS = [s.strip() for s in os.getenv("TRANSCRIPT_LANGS", "en,en-US").split(",") if s.strip()]

OUT_DIR = Path("output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://www.googleapis.com/youtube/v3"

def die(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)

def resolve_channel_and_uploads_playlist():
    if not API_KEY:
        die("YOUTUBE_API_KEY is missing")

    # If we have a channel ID directly, use it
    channel_id = None
    if CHANNEL_ID:
        channel_id = CHANNEL_ID
    elif CHANNEL_HANDLE:
        # Resolve handle -> channel
        url = f"{BASE}/channels?part=contentDetails&forHandle={CHANNEL_HANDLE}&key={API_KEY}"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            die(f"Could not resolve handle {CHANNEL_HANDLE}")
        channel_id = items[0]["id"]
    else:
        die("Provide CHANNEL_HANDLE or CHANNEL_ID")

    # Get uploads playlist
    url = f"{BASE}/channels?part=contentDetails&id={channel_id}&key={API_KEY}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    if not items:
        die(f"No channel found for id {channel_id}")
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return channel_id, uploads_playlist

def list_all_videos(uploads_playlist_id):
    videos = []
    page_token = None
    while True:
        url = (
            f"{BASE}/playlistItems?part=contentDetails,snippet&playlistId={uploads_playlist_id}"
            f"&maxResults=50&key={API_KEY}"
            + (f"&pageToken={page_token}" if page_token else "")
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        for item in data.get("items", []):
            vid = item["contentDetails"]["videoId"]
            title = item["snippet"]["title"]
            published = item["contentDetails"].get("videoPublishedAt", "") or item["snippet"].get("publishedAt", "")
            videos.append({
                "videoId": vid,
                "title": title,
                "publishedAt": published
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.1)  # be nice to API
    return videos

def get_transcript_text(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=LANGS)
        text = " ".join(chunk["text"] for chunk in transcript if chunk.get("text"))
        return text.strip()
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return ""
    except Exception as e:
        # occasional transient errors
        return ""

def main():
    channel_id, uploads = resolve_channel_and_uploads_playlist()
    print(f"[INFO] Channel: {channel_id} | Uploads playlist: {uploads}")
    videos = list_all_videos(uploads)
    print(f"[INFO] Found {len(videos)} videos")

    merged_lines = []
    index_rows = []

    per_episode_dir = OUT_DIR / "episodes"
    per_episode_dir.mkdir(parents=True, exist_ok=True)

    for v in tqdm(videos, desc="Fetching transcripts"):
        vid = v["videoId"]
        title = v["title"].replace("\n", " ").strip()
        pub = v["publishedAt"][:10] if v["publishedAt"] else ""
        url = f"https://www.youtube.com/watch?v={vid}"

        text = get_transcript_text(vid)
        if not text:
            section = f"### {title}\nURL: {url}\nDate: {pub}\n\n(No transcript available)\n\n"
        else:
            section = f"### {title}\nURL: {url}\nDate: {pub}\n\n{text}\n\n"

        merged_lines.append(section)

        # write per-episode file for convenience
        safe_name = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).rstrip()
        per_path = per_episode_dir / f"{pub}_{safe_name[:80]}_{vid}.txt"
        with per_path.open("w", encoding="utf-8") as f:
            f.write(section)

        index_rows.append({
            "title": title,
            "date": pub,
            "videoId": vid,
            "url": url,
            "has_transcript": bool(text)
        })

    # merged file
    merged_path = OUT_DIR / "BrandonEpstein_ALL_Transcripts.txt"
    with merged_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(merged_lines))

    # index json
    with (OUT_DIR / "index.json").open("w", encoding="utf-8") as f:
        json.dump(index_rows, f, ensure_ascii=False, indent=2)

    print(f"[DONE] Wrote {merged_path} and per-episode files in {per_episode_dir}")

if __name__ == "__main__":
    main()
