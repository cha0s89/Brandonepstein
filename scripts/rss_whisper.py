"""Tools for transcribing podcast episodes from an RSS feed using faster-whisper.

The module exposes a :class:`FeedTranscriber` helper that downloads audio
enclosures from a feed, runs the Whisper model, and persists plain-text
transcripts.  It is intended to be driven by :mod:`scripts.rss_whisper_cli`,
although projects may import the helper directly for custom workflows.
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree

import requests
from faster_whisper import WhisperModel

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class Episode:
    """Metadata for a single RSS item with an audio enclosure."""

    title: str
    audio_url: str
    guid: Optional[str] = None
    publication_date: Optional[str] = None

    def slug(self) -> str:
        """Return a filesystem-safe slug for the episode."""

        base = self.guid or self.title or "episode"
        base = base.strip().lower()
        base = re.sub(r"[^a-z0-9]+", "-", base)
        base = base.strip("-")
        return base or "episode"


class FeedTranscriber:
    """Download and transcribe podcast episodes from an RSS feed."""

    def __init__(
        self,
        feed_url: str,
        output_dir: Path,
        model_size: str = "base",
        language: Optional[str] = None,
        beam_size: int = 5,
        temperature: float = 0.0,
        vad_filter: bool = True,
        compute_type: str = "int8",
        device: Optional[str] = None,
        chunk_size: int = 30,
    ) -> None:
        self.feed_url = feed_url
        self.output_dir = output_dir
        self.model_size = model_size
        self.language = language
        self.beam_size = beam_size
        self.temperature = temperature
        self.vad_filter = vad_filter
        self.compute_type = compute_type
        self.device = device
        self.chunk_size = chunk_size

        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Feed parsing
    # ------------------------------------------------------------------
    def fetch_feed(self) -> ElementTree.Element:
        """Download and parse the RSS feed."""

        _LOGGER.info("Fetching feed: %s", self.feed_url)
        response = requests.get(self.feed_url, timeout=30)
        response.raise_for_status()
        with contextlib.closing(response):
            root = ElementTree.fromstring(response.content)
        return root

    def iter_episodes(self, root: ElementTree.Element) -> Iterator[Episode]:
        """Yield :class:`Episode` entries from the feed."""

        channel = root.find("channel") or root
        for item in channel.findall("item"):
            enclosure = item.find("enclosure")
            if enclosure is None or not enclosure.get("url"):
                continue

            title = (item.findtext("title") or "").strip()
            guid = (item.findtext("guid") or "").strip() or None
            pub_date = (item.findtext("pubDate") or "").strip() or None

            if not title:
                title = guid or enclosure.get("url")

            yield Episode(
                title=title,
                audio_url=enclosure.get("url"),
                guid=guid,
                publication_date=pub_date,
            )

    # ------------------------------------------------------------------
    # Download/transcribe workflow
    # ------------------------------------------------------------------
    def download_episode(self, episode: Episode, destination: Path) -> Path:
        """Download the episode audio to *destination*."""

        destination = destination.with_suffix(destination.suffix or ".mp3")
        _LOGGER.info("Downloading %s", episode.audio_url)
        with requests.get(episode.audio_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with destination.open("wb") as out_file:
                shutil.copyfileobj(resp.raw, out_file)
        return destination

    def _load_model(self) -> WhisperModel:
        device = self.device or ("cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") else "cpu")
        _LOGGER.info(
            "Loading faster-whisper model '%s' on device '%s' (compute=%s)",
            self.model_size,
            device,
            self.compute_type,
        )
        return WhisperModel(
            self.model_size,
            device=device,
            compute_type=self.compute_type,
        )

    def transcribe_episode(self, model: WhisperModel, audio_path: Path) -> str:
        """Return the concatenated transcript for *audio_path*."""

        segments, _ = model.transcribe(
            str(audio_path),
            language=self.language,
            beam_size=self.beam_size,
            temperature=self.temperature,
            vad_filter=self.vad_filter,
            chunk_size=self.chunk_size,
        )

        lines = [segment.text.strip() for segment in segments if segment.text]
        return "\n".join(line for line in lines if line)

    def write_transcript(self, episode: Episode, transcript: str) -> Path:
        target = self.output_dir / f"{episode.slug()}.txt"
        _LOGGER.info("Writing transcript: %s", target)
        target.write_text(transcript.strip() + "\n", encoding="utf-8")
        return target

    def transcribe(self, max_episodes: Optional[int] = None, skip_existing: bool = True) -> list[Path]:
        """Process the feed and return written transcript paths."""

        root = self.fetch_feed()
        episodes = list(self.iter_episodes(root))
        if max_episodes is not None:
            episodes = episodes[:max_episodes]

        written: list[Path] = []
        model: Optional[WhisperModel] = None

        try:
            for episode in episodes:
                target_path = self.output_dir / f"{episode.slug()}.txt"
                if skip_existing and target_path.exists():
                    _LOGGER.info("Skipping %s; transcript already exists", episode.title)
                    written.append(target_path)
                    continue

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as temp_file:
                    temp_path = Path(temp_file.name)
                    self.download_episode(episode, temp_path)

                    if model is None:
                        model = self._load_model()

                    transcript = self.transcribe_episode(model, temp_path)
                written.append(self.write_transcript(episode, transcript))
        finally:
            if model is not None:
                # The WhisperModel does not expose an explicit close hook, but keeping
                # the reference in scope allows the GC to release GPU/CPU resources.
                del model

        return written


def transcribe_feed(
    feed_url: str,
    output_dir: Path | str,
    *,
    model_size: str = "base",
    language: Optional[str] = None,
    beam_size: int = 5,
    temperature: float = 0.0,
    vad_filter: bool = True,
    compute_type: str = "int8",
    device: Optional[str] = None,
    chunk_size: int = 30,
    max_episodes: Optional[int] = None,
    skip_existing: bool = True,
) -> list[Path]:
    """Convenience wrapper around :class:`FeedTranscriber`.

    Returns a list with the paths to any transcripts that were created.
    """

    transcriber = FeedTranscriber(
        feed_url=feed_url,
        output_dir=Path(output_dir),
        model_size=model_size,
        language=language,
        beam_size=beam_size,
        temperature=temperature,
        vad_filter=vad_filter,
        compute_type=compute_type,
        device=device,
        chunk_size=chunk_size,
    )
    return transcriber.transcribe(max_episodes=max_episodes, skip_existing=skip_existing)
