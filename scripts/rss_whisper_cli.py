"""Command-line interface for RSS transcription using faster-whisper."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rss_whisper import FeedTranscriber


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download podcast episodes from an RSS feed and transcribe them with faster-whisper.",
    )
    parser.add_argument("feed", help="URL to the RSS feed containing podcast episodes")
    parser.add_argument(
        "--output",
        default="output/rss_transcripts",
        type=Path,
        help="Directory where transcript files should be written",
    )
    parser.add_argument("--model", default="base", help="Name of the faster-whisper model to load")
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language hint passed to faster-whisper (e.g. 'en').",
    )
    parser.add_argument("--beam-size", type=int, default=5, help="Beam size used during decoding")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Decoding temperature passed to faster-whisper",
    )
    parser.add_argument(
        "--no-vad",
        dest="vad_filter",
        action="store_false",
        help="Disable VAD filtering when transcribing",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="Compute type for faster-whisper (e.g. int8, float16, float32)",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Device override for faster-whisper (defaults to CUDA when available, else CPU)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=30,
        help="Chunk size (in seconds) passed to faster-whisper",
    )
    parser.add_argument(
        "--max-episodes",
        type=int,
        default=None,
        help="Limit the number of episodes processed from the feed",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-transcribe episodes even if the transcript file already exists",
    )
    parser.set_defaults(vad_filter=True, skip_existing=True)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Configure the logging verbosity",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    transcriber = FeedTranscriber(
        feed_url=args.feed,
        output_dir=args.output,
        model_size=args.model,
        language=args.language,
        beam_size=args.beam_size,
        temperature=args.temperature,
        vad_filter=args.vad_filter,
        compute_type=args.compute_type,
        device=args.device,
        chunk_size=args.chunk_size,
    )

    written = transcriber.transcribe(max_episodes=args.max_episodes, skip_existing=args.skip_existing)
    logging.info("Created %d transcript(s)", len(written))
    for path in written:
        logging.debug("%s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
