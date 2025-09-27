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
    # super-simple VTT → txt with [mm:ss] timestamps
    lines = []
    ts_re = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.\d+\s-->\s(\d{2}):(\d{2}):(\d{2})\.\d+")
    with vtt_path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("WEBVTT") or "-->" in line and ts_re.search(line):
                # skip headers and cue timestamps (we’ll only add starts in merged text)
                continue
            if re.match(r"^\d+$", line):  # cue index numbers
                continue
            # remove HTML/italics tags
            line = re.sub(r"</?[^>]+>", "", line)
            # collapse extra whitespace
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
    # No exact per-line timestamps from VTT here (kept simple). If you want timestamps,
    # we could parse cues and add [mm:ss]. This gets you clean readable text quickly.
    return "\n".join(lines)

def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160]

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
        if not folder.is_dir():
            continue
        if not folder.name.endswith("]"):
            continue
        vid = folder.name.split("[")[-1][:-1]
        tfile = folder / "transcript.txt"
        nofile = folder / "NO_TRANSCRIPT.txt"
        if tfile.exists() or not nofile.exists():
            continue

        url = f"https://www.youtube.com/watch?v={vid}"
        vtt_out = TMP / f"{vid}.en.vtt"

        # try to fetch manual or auto EN captions to VTT
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

        # Find a produced VTT (manual or auto). yt-dlp may name it with .en.vtt or just .vtt
        produced = None
        cand1 = TMP / f"{vid}.en.vtt"
        cand2 = TMP / f"{vid}.vtt"
        if cand1.exists():
            produced = cand1
        elif cand2.exists():
            produced = cand2
        else:
            # try to find any *.vtt for this id
            vtts = list(TMP.glob(f"{vid}.*.vtt")) + list(TMP.glob(f"{vid}.vtt"))
            if vtts:
                produced = vtts[0]

        if not produced or not produced.exists():
            print(f"No VTT produced for {vid}.")
            continue

        # convert to txt and save as transcript.txt
        try:
            text = vtt_to_txt(produced)
            if text.strip():
                tfile.write_text(text, encoding="utf-8")
                print(f"Saved transcript from VTT: {tfile}")
                # remove NO_TRANSCRIPT marker
                try:
                    nofile.unlink()
                except Exception:
                    pass
                filled += 1
            else:
                print(f"Empty text after VTT parse for {vid}.")
        except Exception as e:
            print(f"Error converting VTT for {vid}: {e}")

    # cleanup
    try:
        shutil.rmtree(TMP)
    except Exception:
        pass

    print(f"Done. Filled {filled} transcripts from YouTube captions.")

if __name__ == "__main__":
    main()
