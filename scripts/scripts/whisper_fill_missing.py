import json, os, re, subprocess, sys, shutil
from pathlib import Path

ROOT = Path("data/transcripts/youtube")
OUTDIR = ROOT / "brandonepstein"
LAST_RUN = ROOT / "last_run.json"

TMP = Path("tmp_audio")
TMP.mkdir(parents=True, exist_ok=True)

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
    if not LAST_RUN.exists():
        print("No last_run.json; nothing to do.")
        return

    # Walk all folders; pick those with NO_TRANSCRIPT and no transcript.txt
    targets = []
    for folder in OUTDIR.iterdir():
        if not folder.is_dir() or not folder.name.endswith("]"):
            continue
        vid = folder.name.split("[")[-1][:-1]
        tfile = folder / "transcript.txt"
        nofile = folder / "NO_TRANSCRIPT.txt"
        if tfile.exists() or not nofile.exists():
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        targets.append((vid, folder, url))

    if not targets:
        print("No missing transcripts to fill with Whisper.")
        return

    print(f"Found {len(targets)} episodes without captions. Generating transcripts with Whisper...")

    for vid, folder, url in targets:
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
            # remove NO_TRANSCRIPT marker if present
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
