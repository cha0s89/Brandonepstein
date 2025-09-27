import json, os, re, subprocess, sys, shutil
from pathlib import Path

ROOT = Path("data/transcripts/youtube")
OUTDIR = ROOT / "brandonepstein"
LAST_RUN = ROOT / "last_run.json"
TMP = Path("tmp_caps")
TMP.mkdir(parents=True, exist_ok=True)

def run(cmd):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

def vtt_to_txt(vtt_path: Path) -> str:
    lines = []
    ts_re = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.\d+\s-->\s(\d{2}):(\d{2}):(\d{2})\.\d+")
    with vtt_path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or ("-->" in line and ts_re.search(line)) or line.startswith("WEBVTT"):
                continue
            if re.match(r"^\d+$", line):
                continue
            line = re.sub(r"</?[^>]+>", "", line)
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
    return "\n".join(lines)

def main():
    if not LAST_RUN.exists():
        print("No last_run.json; nothing to do.")
        return

    stats = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    ids = stats.get("processed_ids", [])
    if not ids:
        print("No processed IDs; nothing to do.")
        return

    filled = 0
    for folder in OUTDIR.iterdir():
        if not folder.is_dir() or not folder.name.endswith("]"):
            continue
        vid = folder.name.split("[")[-1][:-1]
        tfile = folder / "transcript.txt"
        nofile = folder / "NO_TRANSCRIPT.txt"
        if tfile.exists() or not nofile.exists():
            continue

        url = f"https://www.youtube.com/watch?v={vid}"
        vtt_out = TMP / f"{vid}.en.vtt"

        try:
            if vtt_out.exists():
                vtt_out.unlink()
            run([
                "yt-dlp",
                "--skip-download",
                "--write-sub", "--write-auto-sub",
                "--sub-lang", "en",
                "--sub-format", "vtt",
                "-o", str(TMP / f"{vid}.%(ext)s"),
                url
            ])
        except Exception as e:
            print(f"yt-dlp captions failed for {vid}: {e}")
            continue

        produced = None
        cand1 = TMP / f"{vid}.en.vtt"
        cand2 = TMP / f"{vid}.vtt"
        if cand1.exists():
            produced = cand1
        elif cand2.exists():
            produced = cand2
        else:
            vtts = list(TMP.glob(f"{vid}.*.vtt")) + list(TMP.glob(f"{vid}.vtt"))
            if vtts:
                produced = vtts[0]

        if not produced or not produced.exists():
            print(f"No VTT produced for {vid}.")
            continue

        try:
            text = vtt_to_txt(produced)
            if text.strip():
                tfile.write_text(text, encoding="utf-8")
                print(f"Saved transcript from VTT: {tfile}")
                try:
                    nofile.unlink()
                except Exception:
                    pass
                filled += 1
            else:
                print(f"Empty text after VTT parse for {vid}.")
        except Exception as e:
            print(f"Error converting VTT for {vid}: {e}")

    try:
        shutil.rmtree(TMP)
    except Exception:
        pass

    print(f"Done. Filled {filled} transcripts from YouTube captions.")

if __name__ == "__main__":
    main()
