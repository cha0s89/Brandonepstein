import os, re, json, subprocess
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

YT_SOURCE = os.getenv("YT_SOURCE", "").strip()
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "0") or "0")

OUTDIR = Path("data/transcripts/youtube/brandonepstein")
OUTDIR.mkdir(parents=True, exist_ok=True)

def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160]

def list_videos(url: str):
    # Use yt-dlp to get structured listing (no downloads)
    # -I selects first N items if MAX_VIDEOS > 0
    cmd = ["yt-dlp", "-J", url]
    if MAX_VIDEOS > 0:
      cmd = ["yt-dlp", "-J", "-I", f"1:{MAX_VIDEOS}", url]

    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)

    entries = []
    if "entries" in data and data["entries"]:
        for e in data["entries"]:
            if e and e.get("id"):
                entries.append(e)
    elif data.get("id"):
        entries.append(data)

    # Normalize a minimal schema
    videos = []
    for e in entries:
        videos.append({
            "id": e.get("id"),
            "title": e.get("title") or e.get("id"),
            "upload_date": e.get("upload_date") or "",
            "channel": e.get("channel") or "",
            "webpage_url": e.get("webpage_url") or "",
        })
    return videos

def fetch_transcript(video_id: str, langs=("en","en-US","en-GB")):
    tlist = YouTubeTranscriptApi.list_transcripts(video_id)

    # Prefer human EN
    for lang in langs:
        try:
            return tlist.find_manually_created_transcript([lang]).fetch()
        except: pass

    # Fallback: auto EN
    for lang in langs:
        try:
            return tlist.find_generated_transcript([lang]).fetch()
        except: pass

    # Last resort: translate another language to EN (if allowed)
    for t in tlist:
        if t.is_translatable:
            try:
                return t.translate("en").fetch()
            except: pass

    raise NoTranscriptFound("No available transcript (manual/auto/translated).")

def format_srtish(chunks):
    # Simple [mm:ss] text lines
    lines = []
    for c in chunks:
        mm = int(c["start"] // 60)
        ss = int(c["start"] % 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {c['text']}")
    return "\n".join(lines)

def main():
    if not YT_SOURCE:
        raise SystemExit("YT_SOURCE env var not set.")

    videos = list_videos(YT_SOURCE)
    print(f"Found {len(videos)} videos in source")

    saved = 0
    for v in videos:
        vid = v["id"]
        title = v["title"]
        upload_date = v["upload_date"]
        if re.fullmatch(r"\d{8}", upload_date):
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        folder = OUTDIR / f"{upload_date + ' - ' if upload_date else ''}{safe_name(title)} [{video_id}]"
folder.mkdir(parents=True, exist_ok=True)
fpath = folder / "transcript.txt"

        if fpath.exists():
            print(f"Skip existing: {fname}")
            continue

        try:
            chunks = fetch_transcript(vid)
            text = format_srtish(chunks)
            fpath.write_text(text, encoding="utf-8")
            print(f"Saved: {fname}")
            saved += 1
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"No transcript: {vid} ({e})")
        except Exception as e:
            print(f"Error on {vid}: {e}")

    print(f"Done. Saved {saved}/{len(videos)} transcripts to {OUTDIR}")

if __name__ == "__main__":
    main()
