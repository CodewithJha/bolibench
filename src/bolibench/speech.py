"""Speech in the loop: each user turn goes text -> TTS -> audio -> STT -> transcript -> inner adapter.

The inner adapter only ever sees the transcript, so the run measures whether the request survives a
speech round-trip and the agent still acts correctly. The evaluator is unchanged and stays the authority.
The audio is synthetic (TTS), not real speakers.
"""

import hashlib
import http.client
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from bolibench.adapters import AdapterError, AgentAdapter
from bolibench.models import AdapterInfo, CaseContext, SpeechTurn, Transcript
from bolibench.sandbox import OrderSandbox
from bolibench.webhook import LOCAL_HOSTS, _NoRedirect

API = "https://api.elevenlabs.io"
TTS_MODEL = "eleven_multilingual_v2"  # lists Hindi; the documented default of the TTS endpoint
STT_MODEL = "scribe_v2"
MAX_AUDIO = 5 * 1024 * 1024  # a one-turn utterance is tens of KB of mp3
MAX_JSON = 1024 * 1024
ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}")  # no leading dot: ".." would be a path segment


class TTS(Protocol):
    config: dict[str, Any]  # identifies the audio a text maps to; no credentials
    suffix: str  # audio file suffix, e.g. ".mp3"

    def synthesize(self, text: str) -> bytes: ...


class STT(Protocol):
    config: dict[str, Any]  # no credentials

    def transcribe(self, audio: bytes) -> Transcript: ...


@dataclass
class SpeechAdapter:
    """Wraps any AgentAdapter. Existing files in `audio_dir` are reused, so reruns hear identical audio."""

    inner: AgentAdapter
    tts: TTS
    stt: STT
    audio_dir: Path | None = None
    turns: list[SpeechTurn] = field(default_factory=list)  # current case only

    def __post_init__(self) -> None:
        if self.audio_dir is not None:
            self.audio_dir.mkdir(parents=True, exist_ok=True)

    @property
    def exposes_tool_calls(self) -> bool:
        return self.inner.exposes_tool_calls

    @property
    def info(self) -> AdapterInfo:  # read live: the inner info may change per case (webhook identity)
        base = self.inner.info
        speech = {"tts": self.tts.config, "stt": self.stt.config}
        return base.model_copy(update={"name": f"speech+{base.name}", "config": {**base.config, "speech": speech}})

    @property
    def last_turn(self) -> SpeechTurn | None:
        """Evidence of the turn just answered (read by the runner right after respond returns)."""
        return self.turns[-1] if self.turns else None

    @property
    def asr_text(self) -> str | None:
        """What the runner should record as TurnRecord.asr_text: the transcript the agent acted on."""
        return self.turns[-1].transcript.text if self.turns else None

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        if turn == 0:
            self.turns = []
        audio, tts_s, path = self._speak(utterance)
        start = time.monotonic()
        transcript = self.stt.transcribe(audio)
        self.turns.append(
            SpeechTurn(
                turn=turn,
                utterance=utterance,
                transcript=transcript,
                audio_bytes=len(audio),
                audio_sha256=hashlib.sha256(audio).hexdigest(),
                audio_file=None if path is None else str(path),
                tts_s=tts_s,
                stt_s=round(time.monotonic() - start, 3),
            )
        )
        return self.inner.respond(turn, transcript.text, context, sandbox)

    def _speak(self, text: str) -> tuple[bytes, float | None, Path | None]:
        path = None
        if self.audio_dir is not None:
            key = hashlib.sha256(json.dumps([self.tts.config, text], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            path = self.audio_dir / f"{key}{self.tts.suffix}"
            if path.exists():
                return path.read_bytes(), None, path
        start = time.monotonic()
        audio = self.tts.synthesize(text)
        elapsed = round(time.monotonic() - start, 3)
        if path is not None:
            tmp = path.with_name(path.name + ".tmp")
            try:
                tmp.write_bytes(audio)
                tmp.replace(path)  # a crash mid-write must not leave a truncated cache entry
            finally:
                tmp.unlink(missing_ok=True)
        return audio, elapsed, path


def _check(api_key: str, base_url: str, timeout: float) -> None:
    if not re.fullmatch(r"[\x21-\x7e]+", api_key):
        raise ValueError("ElevenLabs API key is empty or contains invalid characters")
    parts = urlsplit(base_url)
    if not (parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)):
        raise ValueError(f"ElevenLabs base URL must be https (http only for a local stub): {base_url!r}")
    if not timeout > 0:
        raise ValueError(f"timeout must be positive: {timeout}")


def _reason(body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):  # not JSON, or not an object
        detail = None
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):  # 422: [{"loc", "msg", "type"}, ...]
        detail = detail[0].get("msg")
    elif isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code")
    text = detail if isinstance(detail, str) else body.decode("utf-8", "replace")
    return " ".join(text.split())[:200] or "no detail"


def _post(what: str, url: str, data: bytes, headers: dict[str, str], timeout: float, limit: int) -> bytes:
    """One attempt, no retries, no redirects (they would carry the key elsewhere)."""
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
    if urlsplit(url).hostname in LOCAL_HOSTS:
        handlers.append(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        try:
            response = urllib.request.build_opener(*handlers).open(request, timeout=timeout)
        except urllib.error.HTTPError as e:  # an HTTPError is also the response
            response = e
        with response:
            status, body = response.status, response.read(limit + 1)
    except (OSError, http.client.HTTPException) as e:  # URLError and timeouts are OSErrors
        raise AdapterError(f"{what} request failed: {e}") from e
    if status != 200:
        raise AdapterError(f"{what} HTTP {status}: {_reason(body[:4096])}")
    if len(body) > limit:
        raise AdapterError(f"{what} response exceeds {limit} bytes")
    return body


@dataclass(frozen=True)
class ElevenLabsTTS:
    api_key: str = field(repr=False)
    voice_id: str
    model: str = TTS_MODEL
    output_format: str = "mp3_44100_128"  # mp3 only: the STT upload is sent as audio/mpeg
    seed: int | None = None  # provider-side best-effort determinism
    timeout: float = 30.0
    base_url: str = API
    suffix = ".mp3"

    def __post_init__(self) -> None:
        _check(self.api_key, self.base_url, self.timeout)
        if not ID.fullmatch(self.voice_id) or not ID.fullmatch(self.model):
            raise ValueError(f"bad ElevenLabs voice or model id: {self.voice_id!r}, {self.model!r}")
        if not re.fullmatch(r"mp3_\d+_\d+", self.output_format):
            raise ValueError(f"output_format must be an mp3_<rate>_<kbps> format: {self.output_format!r}")

    @property
    def config(self) -> dict[str, Any]:
        return {"provider": "elevenlabs", "model": self.model, "voice": self.voice_id, "output_format": self.output_format, "seed": self.seed}

    def synthesize(self, text: str) -> bytes:
        url = f"{self.base_url.rstrip('/')}/v1/text-to-speech/{self.voice_id}?output_format={self.output_format}"
        body: dict[str, Any] = {"text": text, "model_id": self.model}
        if self.seed is not None:
            body["seed"] = self.seed
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
        audio = _post("elevenlabs tts", url, json.dumps(body, ensure_ascii=False).encode(), headers, self.timeout, MAX_AUDIO)
        if not audio:
            raise AdapterError("elevenlabs tts returned no audio")
        return audio


class _ScribeReply(BaseModel):  # extra fields (words, timings, ...) are ignored
    text: str
    language_code: str | None = None
    language_probability: float | None = None


@dataclass(frozen=True)
class ElevenLabsSTT:
    api_key: str = field(repr=False)
    model: str = STT_MODEL
    language: str | None = None  # ISO 639-1/3 hint, e.g. "hin"; None = provider auto-detects
    timeout: float = 60.0
    base_url: str = API

    def __post_init__(self) -> None:
        _check(self.api_key, self.base_url, self.timeout)
        if not ID.fullmatch(self.model) or not re.fullmatch(r"[a-z]{2,3}", self.language or "xx"):
            raise ValueError(f"bad ElevenLabs STT model or language: {self.model!r}, {self.language!r}")

    @property
    def config(self) -> dict[str, Any]:
        return {"provider": "elevenlabs", "model": self.model, "language": self.language}

    def transcribe(self, audio: bytes) -> Transcript:
        fields = {"model_id": self.model, "tag_audio_events": "false"}
        if self.language:
            fields["language_code"] = self.language
        boundary = secrets.token_hex(16)
        data = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
        data += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()
        data += audio + f"\r\n--{boundary}--\r\n".encode()
        headers = {"xi-api-key": self.api_key, "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}
        body = _post("elevenlabs stt", f"{self.base_url.rstrip('/')}/v1/speech-to-text", data, headers, self.timeout, MAX_JSON)
        try:
            reply = _ScribeReply.model_validate_json(body)
        except ValidationError as e:
            raise AdapterError(f"elevenlabs stt malformed reply: {e.errors()[0]['msg']}") from e
        return Transcript(text=reply.text, language=reply.language_code, language_probability=reply.language_probability)


def elevenlabs_from_env(env: Mapping[str, str] = os.environ) -> tuple[ElevenLabsTTS, ElevenLabsSTT]:
    """Validate the whole config before any network call; raises ValueError naming the problem, never the key."""
    key = env.get("ELEVENLABS_API_KEY", "")
    voice = env.get("ELEVENLABS_VOICE_ID", "")
    if not key:
        raise ValueError("ELEVENLABS_API_KEY is not set")
    if not voice:
        raise ValueError("ELEVENLABS_VOICE_ID is not set (a voice id from your ElevenLabs voice library)")
    base = env.get("ELEVENLABS_BASE_URL", API)
    tts = ElevenLabsTTS(key, voice, model=env.get("ELEVENLABS_TTS_MODEL", TTS_MODEL), base_url=base)
    stt = ElevenLabsSTT(key, model=env.get("ELEVENLABS_STT_MODEL", STT_MODEL), language=env.get("ELEVENLABS_STT_LANGUAGE") or None, base_url=base)
    return tts, stt
