"""Speech-to-text and text-to-speech behind small provider interfaces.

STT: local faster-whisper (free, CPU) or OpenAI. TTS: the visitor's browser (Web Speech API, free,
voices depend on the device) or OpenAI. Switching is a configuration change (STT_PROVIDER, TTS_PROVIDER).
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.config import Settings, get_settings
from app.errors import AppError, PayloadTooLarge, ServiceUnavailable, UnsupportedMedia

ALLOWED_AUDIO = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
}
MAX_AUDIO_BYTES = 5 * 1024 * 1024


@dataclass
class Transcript:
    text: str
    language: str | None
    duration_seconds: float
    provider: str


@dataclass
class Speech:
    audio: bytes
    media_type: str
    provider: str


def validate_audio(data: bytes, content_type: str) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if base not in ALLOWED_AUDIO:
        raise UnsupportedMedia("Unsupported audio format.")
    if len(data) > MAX_AUDIO_BYTES:
        raise PayloadTooLarge("Audio clips are limited to 5 MB.")
    if len(data) < 512:
        raise AppError("The recording is empty.")
    return base


SAMPLE_RATE = 16_000


def decode_audio(audio: bytes) -> np.ndarray:
    """Any browser recording (webm/opus, ogg, wav, mp3, m4a) -> 16 kHz mono float32 samples.

    Decoding here, with PyAV directly, keeps the provider independent of the audio helpers bundled with
    faster-whisper (whose PyAV call broke with PyAV 19)."""
    import av

    chunks: list[np.ndarray] = []
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            if not container.streams.audio:
                raise AppError("The recording contains no audio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(container.streams.audio[0]):
                chunks.extend(f.to_ndarray() for f in resampler.resample(frame))
            chunks.extend(f.to_ndarray() for f in resampler.resample(None))
    except AppError:
        raise
    except Exception as exc:
        raise AppError("The recording could not be decoded.") from exc
    if not chunks:
        raise AppError("The recording is empty.")
    return np.concatenate(chunks, axis=1).reshape(-1).astype(np.float32) / 32768.0


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, content_type: str, language_hint: str | None) -> Transcript: ...


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, language: str) -> Speech | None:
        """Audio, or None when the client should speak the text itself."""
        ...


class LocalWhisperSTT:
    name = "local_whisper"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self._settings.whisper_model,
                    device="cpu",
                    compute_type="int8",
                    download_root=os.path.join(self._settings.model_cache_dir, "whisper"),
                    cpu_threads=2,
                )
        return self._model

    def _run(self, audio: bytes, language_hint: str | None) -> Transcript:
        samples = decode_audio(audio)
        if len(samples) > self._settings.max_audio_seconds * SAMPLE_RATE:
            raise PayloadTooLarge(f"Recordings are limited to {self._settings.max_audio_seconds} seconds.")
        model = self._load()
        hint = language_hint.split("-")[0] if language_hint in ("en", "fr", "ar", "ar-tn") else None
        segments, info = model.transcribe(samples, language=hint, beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(text, info.language, round(info.duration, 2), self.name)

    async def transcribe(self, audio: bytes, content_type: str, language_hint: str | None) -> Transcript:
        try:
            return await asyncio.to_thread(self._run, audio, language_hint)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("The recording could not be decoded.") from exc


class OpenAISTT:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        key = settings.voice_api_key.get_secret_value() or settings.llm_primary_api_key.get_secret_value()
        if not key:
            raise ServiceUnavailable("STT_PROVIDER=openai needs VOICE_API_KEY or LLM_PRIMARY_API_KEY.")
        self._client = AsyncOpenAI(api_key=key)
        self._model = settings.openai_stt_model

    async def transcribe(self, audio: bytes, content_type: str, language_hint: str | None) -> Transcript:
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(
            content_type, "wav"
        )
        kwargs = {"language": language_hint.split("-")[0]} if language_hint else {}
        result = await self._client.audio.transcriptions.create(
            model=self._model, file=(f"audio.{ext}", audio, content_type), **kwargs
        )
        return Transcript(result.text.strip(), language_hint, 0.0, self.name)


class DisabledSTT:
    name = "disabled"

    async def transcribe(self, audio: bytes, content_type: str, language_hint: str | None) -> Transcript:
        raise ServiceUnavailable("Voice input is disabled on this server.")


class BrowserTTS:
    name = "browser"

    async def synthesize(self, text: str, language: str) -> Speech | None:
        return None


class OpenAITTS:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        key = settings.voice_api_key.get_secret_value() or settings.llm_primary_api_key.get_secret_value()
        if not key:
            raise ServiceUnavailable("TTS_PROVIDER=openai needs VOICE_API_KEY or LLM_PRIMARY_API_KEY.")
        self._client = AsyncOpenAI(api_key=key)
        self._model, self._voice = settings.openai_tts_model, settings.openai_tts_voice

    async def synthesize(self, text: str, language: str) -> Speech | None:
        response = await self._client.audio.speech.create(
            model=self._model, voice=self._voice, input=text[:4000], response_format="mp3"
        )
        return Speech(response.content, "audio/mpeg", self.name)


@lru_cache(maxsize=1)
def get_stt() -> STTProvider:
    settings = get_settings()
    return {"local_whisper": LocalWhisperSTT, "openai": OpenAISTT}.get(settings.stt_provider, lambda s: DisabledSTT())(
        settings
    )


@lru_cache(maxsize=1)
def get_tts() -> TTSProvider:
    settings = get_settings()
    return OpenAITTS(settings) if settings.tts_provider == "openai" else BrowserTTS()
