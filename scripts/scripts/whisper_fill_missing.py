import json, os, re, subprocess, sys, shutil
from pathlib import Path

# Output roots must match your main script
ROOT = Path("data/transcripts/youtube")
OUTDIR = ROOT / "brandonepstein"
LAST_RUN = ROOT / "last_run.json"

TMP = Path("tmp_audio")
TMP.mkdir(parents=True, exist_ok=True)

def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160]

def find_missing_folders():
    """
    Return list of (video_id, folder_path, url) for episodes that have NO_TRANSCRIPT.txt
    and no transcript.txt present.
    """
    missing = []
    if not LAST_RUN.exists():
        return missing
    stats = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    ids = stats.get("processed_ids", [])
    for vid in ids:
        candidates = [p for p in OUTDIR.glob(f"*[{vid}]") if p.is_dir()]
        if not candidates:
            candidates = [p for p in OUTDIR.iterdir() if p.is_dir() and p.name.endswith(f"[{vid}]")]
        for folder in candidates:
            tfile = folder / "transcript.txt"
            notefile = folder / "NO_TRANSCRIPT.txt"
            meta = folder / "metadata.txt"
            if tfile.exists() or not notefile.exists():
                continue
            url = None
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if line.startswith("URL:"):
                        url = line.split("URL:",1)[1].strip()
                        break
            if not url:
                url = f"https://www.youtube.com/watch?v={vid}"
            missing.append((vid, folder, url))
    return missing

def run(cmd):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(cmd)}")

def transcribe_with_faster_whisper(audio_path: Path, out_txt: Path):
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), language="en", vad_filter=True)
    with out_txt.open("w", encoding="utf-8") as f:
        for seg in segments:
            mm = int(seg.start // 60)
            ss = int(seg.start % 60)
            f.write(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}\n")

def main():
    missing = find_missing_folders()
    if not missing:
        print("No missing transcripts to fill with Whisper.")
        return

    print(f"Found {len(missing)} episodes without captions. Generating transcripts with Whisper...")

    for vid, folder, url in missing:
        print(f"Processing {vid} → {folder.name}")
        # 1) download audio
        audio_out = TMP / f"{vid}.m4a"
        if audio_out.exists():
            audio_out.unlink()
        run([
            "yt-dlp",
            "-f", "bestaudio/best",
            "-x", "--audio-format", "m4a",
            "-o", str(audio_out),
            url
        ])

        # 2) transcribe
        tfile = folder / "transcript.txt"
        try:
            transcribe_with_faster_whisper(audio_out, tfile)
            print(f"Saved transcript: {tfile}")
            nt = folder / "NO_TRANSCRIPT.txt"
            if nt.exists():
                nt.unlink()
        except Exception as e:
            err = folder / "ERROR.txt"
            err.write_text(str(e), encoding="utf-8")
            print(f"ERROR on {vid}: {e}")

    # cleanup
    try:
        shutil.rmtree(TMP)
    except Exception:
        pass

if __name__ == "__main__":
    main()
