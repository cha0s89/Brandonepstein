import os
import re
import json
import subprocess
import sys
import shutil
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
except ImportError:
    print("Please install youtube-transcript-api: pip install youtube-transcript-api")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    print("Please install tqdm: pip install tqdm")
    sys.exit(1)

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Please install faster-whisper: pip install faster-whisper")
    sys.exit(1)

# --- Configuration ---
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://www.youtube.com/@richroll/videos").strip()

ROOT = Path("data/transcripts/youtube")
OUTDIR = ROOT / "richroll"
TMP = Path("tmp_audio")
TMP.mkdir(parents=True, exist_ok=True)
OUTDIR.mkdir(parents=True, exist_ok=True)

def run_yt_dlp_list(url: str, max_videos=0) -> dict:
    cmd = [
        sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", url
    ]
    if max_videos > 0:
        cmd = [
            sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", "-I", f"1:{max_videos}", url
        ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)
    return json.loads(r.stdout)

def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160]

def get_transcript_text(video_id: str) -> str:
    try:
        transcript = None
        listing = YouTubeTranscriptApi.list_transcripts(video_id)
        for lang in ("en", "en-US"):
            try:
                transcript = listing.find_manually_created_transcript([lang]).fetch()
                break
            except:
                continue
        if transcript is None:
            for lang in ("en", "en-US"):
                try:
                    transcript = listing.find_generated_transcript([lang]).fetch()
                    break
                except:
                    continue
        if not transcript:
            return ""
        text = " ".join(chunk["text"] for chunk in transcript if chunk.get("text"))
        return text.strip()
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return ""
    except Exception:
        return ""

def transcribe_with_faster_whisper(audio_path: Path, out_txt: Path):
    print(f"[INFO] Running Whisper on {audio_path}")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), language="en", vad_filter=True)
    with out_txt.open("w", encoding="utf-8") as f:
        for seg in segments:
            mm = int(seg.start // 60)
            ss = int(seg.start % 60)
            f.write(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}\n")

def main():
    print(f"[INFO] Listing videos from: {CHANNEL_URL}")
    data = run_yt_dlp_list(CHANNEL_URL)
    entries = data.get("entries") or []
    print(f"[INFO] Found {len(entries)} videos.")

    for entry in tqdm(entries, desc="Processing videos"):
        vid = entry.get("id")
        title = (entry.get("title") or f"Video {vid}").replace("\n", " ").strip()
        url = f"https://www.youtube.com/watch?v={vid}"

        folder_name = f"{safe_name(title)} [{vid}]"
        out_folder = OUTDIR / folder_name
        out_folder.mkdir(parents=True, exist_ok=True)
        meta_file = out_folder / "metadata.txt"
        transcript_file = out_folder / "transcript.txt"
        notrans_file = out_folder / "NO_TRANSCRIPT.txt"

        # Write metadata
        meta_file.write_text(f"Title: {title}\nVideoID: {vid}\nURL: {url}\nDate: {entry.get('upload_date','')}\n", encoding="utf-8")

        # Skip if transcript already exists
        if transcript_file.exists():
            continue

        # Try to fetch transcript from YouTube
        text = get_transcript_text(vid)
        if text:
            transcript_file.write_text(text, encoding="utf-8")
            if notrans_file.exists():
                notrans_file.unlink()
            continue

        # If no transcript, try Whisper
        print(f"[INFO] No YouTube transcript for {vid}, attempting Whisper transcription...")
        audio_out = TMP / f"{vid}.m4a"
        if audio_out.exists():
            audio_out.unlink()
        yt_dl_cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestaudio/best",
            "-x", "--audio-format", "m4a",
            "-o", str(audio_out),
            url
        ]
        r = subprocess.run(yt_dl_cmd)
        if r.returncode != 0:
            print(f"[ERROR] Failed to download audio for {vid}")
            notrans_file.write_text("Could not download audio for Whisper transcription.", encoding="utf-8")
            continue

        try:
            transcribe_with_faster_whisper(audio_out, transcript_file)
            if notrans_file.exists():
                notrans_file.unlink()
        except Exception as e:
            print(f"[ERROR] Whisper failed on {vid}: {e}")
            notrans_file.write_text(f"Whisper error: {e}", encoding="utf-8")
        finally:
            if audio_out.exists():
                audio_out.unlink()

    # Cleanup temp
    try:
        shutil.rmtree(TMP)
    except Exception:
        pass

    print("[DONE] Processing complete.")

if __name__ == "__main__":
    main()
