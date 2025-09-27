import os, re, json, subprocess
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# ----- Config via env -----
YT_SOURCE = os.getenv("YT_SOURCE", "").strip()
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "0") or "0")

# Output: one folder per episode; idempotent + archived IDs
ROOT = Path("data/transcripts/youtube")
OUTDIR = ROOT / "brandonepstein"
OUTDIR.mkdir(parents=True, exist_ok=True)

ARCHIVE = ROOT / "archive_ids.txt"
ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
if not ARCHIVE.exists():
    ARCHIVE.write_text("", encoding="utf-8")

RUN_INDEX = ROOT / "last_run.json"  # we always update this, so there's something to commit

def is_archived(video_id: str) -> bool:
    return any(line.strip() == video_id for line in ARCHIVE.read_text(encoding="utf-8").splitlines())

def mark_archived(video_id: str):
    with ARCHIVE.open("a", encoding="utf-8") as f:
        f.write(video_id + "\n")

def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160]

def normalize_source(url: str) -> str:
    if not url:
        raise SystemExit("YT_SOURCE is empty. Set it in the workflow env.")
    url = url.strip()
    if url.startswith("@"):
        url = "https://www.youtube.com/" + url
    if "youtube.com/@" in url and not url.rstrip("/").endswith("/videos"):
        url = url.rstrip("/") + "/videos"
    return url

def yt_dlp_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("yt-dlp failed with:", " ".join(cmd))
        print("STDERR:\n", r.stderr)
        raise SystemExit(1)
    return json.loads(r.stdout)

def list_videos(url: str):
    base_cmd = ["yt-dlp", "-J", "--flat-playlist", "--no-warnings", url]
    if MAX_VIDEOS > 0:
        base_cmd = ["yt-dlp", "-J", "--flat-playlist", "-I", f"1:{MAX_VIDEOS}", "--no-warnings", url]
    entries = []
    try:
        data = yt_dlp_json(base_cmd)
        entries = data.get("entries") or []
    except SystemExit:
        pass
    if not entries:
        try:
            data2 = yt_dlp_json(["yt-dlp", "-J", "--no-warnings", url])
            entries = data2.get("entries") or []
        except SystemExit:
            pass
    if not entries:
        print(f"No videos found at URL:\n  {url}")
        raise SystemExit(1)
    videos = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id") or e.get("url")
        title = e.get("title") or vid
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": title,
            "upload_date": e.get("upload_date") or "",
            "webpage_url": f"https://www.youtube.com/watch?v={vid}",
        })
    return videos

def fetch_transcript_chunks(video_id: str, langs=("en","en-US","en-GB")):
    tlist = YouTubeTranscriptApi.list_transcripts(video_id)
    for lang in langs:
        try:
            return tlist.find_manually_created_transcript([lang]).fetch()
        except: pass
    for lang in langs:
        try:
            return tlist.find_generated_transcript([lang]).fetch()
        except: pass
    for t in tlist:
        if t.is_translatable:
            try:
                return t.translate("en").fetch()
            except: pass
    raise NoTranscriptFound("No available transcript (manual/auto/translated).")

def chunks_to_text(chunks):
    lines = []
    for c in chunks:
        mm = int(c["start"] // 60)
        ss = int(c["start"] % 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {c['text']}")
    return "\n".join(lines)

def main():
    src = normalize_source(YT_SOURCE)
    print(f"Using source: {src}")
    videos = list_videos(src)
    print(f"Found {len(videos)} videos in source")

    stats = {"source": src, "total_listed": len(videos), "saved": 0, "skipped_existing": 0,
             "skipped_archived": 0, "no_transcript": 0, "errors": 0, "processed_ids": []}

    for v in videos:
        vid = v["id"]
        if not vid:
            continue
        stats["processed_ids"].append(vid)

        if is_archived(vid):
            print(f"Skip archived: {vid}")
            stats["skipped_archived"] += 1
            continue

        title = v["title"]
        date = v["upload_date"]
        if re.fullmatch(r"\d{8}", date or ""):
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

        folder_name = f"{(date + ' - ') if date else ''}{safe_name(title)} [{vid}]"
        folder = OUTDIR / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        fpath = folder / "transcript.txt"
        meta = folder / "metadata.txt"

        if fpath.exists():
            print(f"Skip existing file: {folder_name}/transcript.txt")
            stats["skipped_existing"] += 1
            # still mark archived so we never retry
            mark_archived(vid)
            continue

        try:
            chunks = fetch_transcript_chunks(vid)
            text = chunks_to_text(chunks)
            meta.write_text(
                f"Title: {title}\nVideoID: {vid}\nURL: {v['webpage_url']}\nDate: {date or ''}\n",
                encoding="utf-8"
            )
            fpath.write_text(text, encoding="utf-8")
            print(f"Saved: {folder_name}/transcript.txt")
            mark_archived(vid)
            stats["saved"] += 1
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"No transcript: {vid} ({e})")
            # record a small marker file so the run always has output to commit
            (folder / "NO_TRANSCRIPT.txt").write_text(str(e), encoding="utf-8")
            # do NOT mark archived here so you can later run a Whisper fallback if you want
            stats["no_transcript"] += 1
        except Exception as e:
            print(f"Error on {vid}: {e}")
            (folder / "ERROR.txt").write_text(str(e), encoding="utf-8")
            stats["errors"] += 1

    RUN_INDEX.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print("Run stats:", json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()
