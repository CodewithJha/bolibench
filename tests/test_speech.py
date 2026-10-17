import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from bolibench import cli, speech
from bolibench.adapters import AdapterError, Call, FakeAgentAdapter, Reply
from bolibench.evaluate import evaluate
from bolibench.models import AdapterInfo, CaseContext
from bolibench.runner import run_case
from bolibench.sandbox import OrderSandbox
from bolibench.speech import ElevenLabsSTT, ElevenLabsTTS, SpeechAdapter, Transcript, elevenlabs_from_env
from bolibench.store import load_case

SUITE = Path(__file__).parent.parent / "suites" / "orders"
SCRIPT = Path(__file__).parent.parent / "examples" / "scripts" / "ambiguous-previous-order.json"
CASE = load_case(SUITE / "awadhi-cancel-yesterday.json")
KEY = "sk_test_SECRET_9f8e7d"
GOOD = [[Call(tool="list_orders"), Call(tool="cancel_order", args={"order_id": "ORD-401"}), Reply(text="हो गया")]]


@dataclass
class FakeTTS:
    calls: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=lambda: {"provider": "fake", "voice": "v1"})
    suffix: str = ".bin"

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        return text.encode()


@dataclass
class FakeSTT:
    garble: dict[str, str] = field(default_factory=dict)  # mis-hearings: original -> heard
    config: dict[str, Any] = field(default_factory=lambda: {"provider": "fake"})

    def transcribe(self, audio: bytes) -> Transcript:
        text = audio.decode()
        return Transcript(text=self.garble.get(text, text), language="hin")


@dataclass
class Listening:
    """Records what the inner agent was told, then replays the fake script."""

    inner: FakeAgentAdapter
    heard: list[str] = field(default_factory=list)

    @property
    def info(self) -> AdapterInfo:
        return self.inner.info

    exposes_tool_calls = True

    def respond(self, turn: int, utterance: str, context: CaseContext, sandbox: OrderSandbox) -> str:
        self.heard.append(utterance)
        return self.inner.respond(turn, utterance, context, sandbox)


def test_round_trip_runs_real_case_and_records_evidence() -> None:
    tts, inner = FakeTTS(), Listening(FakeAgentAdapter(GOOD))
    adapter = SpeechAdapter(inner, tts, FakeSTT())
    record = run_case(CASE, adapter)
    assert evaluate(CASE, record).verdict == "pass"
    assert tts.calls == CASE.turns and inner.heard == CASE.turns
    assert record.adapter.name == "speech+fake-scripted"
    assert record.adapter.config["speech"] == {"tts": tts.config, "stt": {"provider": "fake"}}
    [ev] = adapter.turns
    audio = CASE.turns[0].encode()
    assert (ev.turn, ev.utterance, ev.transcript.text, ev.transcript.language) == (0, CASE.turns[0], CASE.turns[0], "hin")
    assert ev.audio_bytes == len(audio) and len(ev.audio_sha256) == 64 and ev.audio_file is None
    assert ev.tts_s is not None and ev.tts_s >= 0 and ev.stt_s >= 0
    assert adapter.asr_text == CASE.turns[0] and adapter.last_turn == ev


def test_misheard_transcript_reaches_agent_uncorrected() -> None:
    heard = "ऊ वाला order जउन परसों मँगाए रहेन, ओका रद्द कइ दें।"  # कल -> परसों
    inner = Listening(FakeAgentAdapter(GOOD))
    adapter = SpeechAdapter(inner, FakeTTS(), FakeSTT({CASE.turns[0]: heard}))
    record = run_case(CASE, adapter)
    assert inner.heard == [heard] and adapter.asr_text == heard
    assert record.turns[0].user_input == CASE.turns[0]  # the case text, not the transcript
    assert adapter.turns[0].utterance == CASE.turns[0] and adapter.turns[0].transcript.text == heard


def test_audio_dir_saves_hash_named_audio_and_reuses_it(tmp_path: Path) -> None:
    tts = FakeTTS()
    first = SpeechAdapter(FakeAgentAdapter(GOOD), tts, FakeSTT(), audio_dir=tmp_path / "audio")
    run_case(CASE, first)
    second = SpeechAdapter(FakeAgentAdapter(GOOD), tts, FakeSTT(), audio_dir=tmp_path / "audio")
    run_case(CASE, second)
    assert tts.calls == CASE.turns  # synthesized once
    [a], [b] = first.turns, second.turns
    assert a.audio_file == b.audio_file and a.audio_sha256 == b.audio_sha256
    assert a.tts_s is not None and b.tts_s is None
    assert [p.name for p in (tmp_path / "audio").iterdir()] == [Path(a.audio_file or "").name]
    assert Path(a.audio_file or "").suffix == ".bin" and Path(a.audio_file or "").read_bytes() == CASE.turns[0].encode()
    other_voice = FakeTTS(config={"provider": "fake", "voice": "v2"})
    run_case(CASE, SpeechAdapter(FakeAgentAdapter(GOOD), other_voice, FakeSTT(), audio_dir=tmp_path / "audio"))
    assert other_voice.calls == CASE.turns  # a different voice is a different cache key


def test_speech_failure_is_an_error_verdict_not_fail() -> None:
    class DeadTTS(FakeTTS):
        def synthesize(self, text: str) -> bytes:
            raise AdapterError("elevenlabs tts HTTP 429: Too many requests")

    adapter = SpeechAdapter(FakeAgentAdapter(GOOD), DeadTTS(), FakeSTT())
    record = run_case(CASE, adapter)
    assert record.execution_error == "AdapterError: elevenlabs tts HTTP 429: Too many requests"
    assert evaluate(CASE, record).verdict == "error" and adapter.turns == [] and adapter.asr_text is None


def test_failed_cache_write_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def disk_full(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        SpeechAdapter(FakeAgentAdapter(GOOD), FakeTTS(), FakeSTT(), audio_dir=tmp_path)._speak("hi")
    assert list(tmp_path.iterdir()) == []


def test_text_only_run_never_imports_speech(tmp_path: Path) -> None:
    argv = ["run", str(SUITE / "ambiguous-previous-order.json"), "--scripts", str(SCRIPT), "--output", str(tmp_path)]
    code = f"import sys; from bolibench.cli import main; assert main({argv!r}) == 0; assert 'bolibench.speech' not in sys.modules"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELEVENLABS_")}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- ElevenLabs clients against an in-process stub -------------------------------------------------


@dataclass
class Stub:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    reply: Callable[[str, bytes], bytes] | None = None  # (path, request body) -> response body, instead of `body`
    requests: list[tuple[str, dict[str, str], bytes]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def stub() -> Iterator[Stub]:
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = self.rfile.read(int(self.headers["Content-Length"]))
            state.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, request))
            time.sleep(state.delay)
            body = state.body if state.reply is None else state.reply(self.path, request)
            self.send_response(state.status)
            for k, v in state.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def tts(stub: Stub, **kw: Any) -> ElevenLabsTTS:
    return ElevenLabsTTS(KEY, "VoiceABC123", base_url=stub.url, **kw)


def stt(stub: Stub, **kw: Any) -> ElevenLabsSTT:
    return ElevenLabsSTT(KEY, base_url=stub.url, **kw)


def test_tts_request_and_audio(stub: Stub) -> None:
    stub.body = b"ID3fake-mp3"
    assert tts(stub, seed=7).synthesize("Kurta वाला order cancel करो") == b"ID3fake-mp3"
    [(path, headers, body)] = stub.requests
    assert path == "/v1/text-to-speech/VoiceABC123?output_format=mp3_44100_128"
    assert headers["xi-api-key"] == KEY and headers["content-type"] == "application/json"
    assert json.loads(body) == {"text": "Kurta वाला order cancel करो", "model_id": "eleven_multilingual_v2", "seed": 7}


def test_stt_multipart_and_transcript(stub: Stub) -> None:
    stub.body = json.dumps({"text": "Kurta वाला order", "language_code": "hin", "language_probability": 0.91, "words": []}).encode()
    result = stt(stub, language="hin").transcribe(b"\x00mp3-bytes\xff")
    assert result == Transcript(text="Kurta वाला order", language="hin", language_probability=0.91)
    [(path, headers, body)] = stub.requests
    assert path == "/v1/speech-to-text" and headers["xi-api-key"] == KEY
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    for part in (b'name="model_id"\r\n\r\nscribe_v2\r\n', b'name="language_code"\r\n\r\nhin\r\n', b'name="tag_audio_events"\r\n\r\nfalse\r\n'):
        assert part in body
    assert b'filename="speech.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n\x00mp3-bytes\xff\r\n' in body


def test_stt_without_language_hint_lets_provider_detect(stub: Stub) -> None:
    stub.body = b'{"text": ""}'
    assert stt(stub).transcribe(b"x") == Transcript(text="")  # silence passes through as empty, not an error
    assert b"language_code" not in stub.requests[0][2]


def test_missing_config_fails_before_any_request(stub: Stub) -> None:
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY is not set"):
        elevenlabs_from_env({"ELEVENLABS_VOICE_ID": "v", "ELEVENLABS_BASE_URL": stub.url})
    with pytest.raises(ValueError, match="ELEVENLABS_VOICE_ID is not set"):
        elevenlabs_from_env({"ELEVENLABS_API_KEY": KEY, "ELEVENLABS_BASE_URL": stub.url})
    assert stub.requests == []
    env = {"ELEVENLABS_API_KEY": KEY, "ELEVENLABS_VOICE_ID": "v1", "ELEVENLABS_STT_LANGUAGE": "hin", "ELEVENLABS_TTS_MODEL": "eleven_v3"}
    t, s = elevenlabs_from_env(env)
    assert (t.model, t.voice_id, s.model, s.language, s.base_url) == ("eleven_v3", "v1", "scribe_v2", "hin", speech.API)


@pytest.mark.parametrize(
    "kw",
    [
        {"api_key": ""},
        {"api_key": "has space"},
        {"voice_id": "../voices"},
        {"voice_id": ".."},
        {"base_url": "http://api.elevenlabs.io"},  # cleartext key off-host
        {"timeout": 0},
        {"output_format": "pcm_16000"},
    ],
)
def test_bad_tts_config_is_rejected(kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as e:
        ElevenLabsTTS(**({"api_key": KEY, "voice_id": "v1"} | kw))
    assert KEY not in str(e.value)


@pytest.mark.parametrize(
    "status,body,reason",
    [
        (401, b'{"detail": {"type": "authentication_error", "code": "invalid_api_key", "message": "Invalid API key"}}', "Invalid API key"),
        (429, b'{"detail": {"code": "rate_limit_exceeded", "message": "Too many requests"}}', "Too many requests"),
        (422, b'{"detail": [{"loc": ["body", "text"], "msg": "Field required", "type": "missing"}]}', "Field required"),
        (500, b'{"detail": "internal error"}', "internal error"),
        (503, b"<html>\n  Service   Unavailable</html>", "<html> Service Unavailable</html>"),
        (302, b"", "no detail"),  # redirects are refused: they would carry the key elsewhere
    ],
)
def test_http_errors_become_adapter_errors(stub: Stub, status: int, body: bytes, reason: str) -> None:
    stub.status, stub.body = status, body
    stub.headers = {"Location": "http://example.com/steal"} if status == 302 else {}
    for call in (lambda: tts(stub).synthesize("hi"), lambda: stt(stub).transcribe(b"x")):
        with pytest.raises(AdapterError, match=f"HTTP {status}: ") as e:
            call()
        assert str(e.value).endswith(reason) and KEY not in str(e.value) and KEY not in repr(e.value)
    assert len(stub.requests) == 2  # one attempt each, no retries


def test_timeout_is_bounded(stub: Stub) -> None:
    stub.delay = 1.0
    start = time.monotonic()
    with pytest.raises(AdapterError, match="elevenlabs tts request failed: .*timed out"):
        tts(stub, timeout=0.2).synthesize("hi")
    assert time.monotonic() - start < 0.9


def test_malformed_stt_reply(stub: Stub) -> None:
    for body in (b"not json", b'{"language_code": "hin"}', b'{"text": 5}'):
        stub.body = body
        with pytest.raises(AdapterError, match="elevenlabs stt malformed reply"):
            stt(stub).transcribe(b"x")


def test_oversized_and_empty_responses(stub: Stub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "MAX_AUDIO", 8)
    stub.body = b"123456789"
    with pytest.raises(AdapterError, match="elevenlabs tts response exceeds 8 bytes"):
        tts(stub).synthesize("hi")
    stub.body = b""
    with pytest.raises(AdapterError, match="elevenlabs tts returned no audio"):
        tts(stub).synthesize("hi")


def test_key_never_in_reprs_or_config(stub: Stub) -> None:
    t, s = tts(stub), stt(stub)
    adapter = SpeechAdapter(FakeAgentAdapter(GOOD), t, s)
    for text in (repr(t), repr(s), repr(adapter), str(t.config), str(s.config), adapter.info.model_dump_json()):
        assert KEY not in text


def official_api(path: str, body: bytes) -> bytes:
    """ElevenLabs as documented: TTS answers audio bytes, STT a JSON transcript. The stub's "mp3" carries the text."""
    if path.startswith("/v1/text-to-speech/"):
        return b"ID3" + json.loads(body)["text"].encode()
    audio = body.split(b"Content-Type: audio/mpeg\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
    return json.dumps({"language_code": "hin", "language_probability": 0.97, "text": audio[3:].decode(), "words": []}).encode()


def test_cli_speech_run_end_to_end_against_the_documented_api(stub: Stub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub.reply = official_api
    for name, value in {"ELEVENLABS_API_KEY": KEY, "ELEVENLABS_VOICE_ID": "VoiceABC123", "ELEVENLABS_BASE_URL": stub.url}.items():
        monkeypatch.setenv(name, value)
    case = load_case(SUITE / "ambiguous-previous-order.json")
    argv = ["run", str(SUITE / "ambiguous-previous-order.json"), "--scripts", str(SCRIPT), "--speech", "elevenlabs", "--speech-audio-dir", str(tmp_path / "audio")]
    for run in ("first", "rerun"):
        assert cli.main([*argv, "--output", str(tmp_path / run)]) == 0
    tts_path = "/v1/text-to-speech/VoiceABC123?output_format=mp3_44100_128"
    assert [p for p, _, _ in stub.requests] == [tts_path, "/v1/speech-to-text"] * len(case.turns) + ["/v1/speech-to-text"] * len(case.turns)
    assert all(h["xi-api-key"] == KEY for _, h, _ in stub.requests)
    for run, cached in (("first", False), ("rerun", True)):
        [artifact] = (tmp_path / run).glob("*/ambiguous-previous-order.json")
        raw = json.loads(artifact.read_text(encoding="utf-8"))
        assert raw["evaluation"]["verdict"] == "pass" and [t["asr_text"] for t in raw["run"]["turns"]] == case.turns
        assert [t["speech"]["tts_s"] is None for t in raw["run"]["turns"]] == [cached] * len(case.turns)
        assert raw["run"]["adapter"]["config"]["speech"]["stt"] == {"provider": "elevenlabs", "model": "scribe_v2", "language": None}
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.skipif(
    not (os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID") and os.environ.get("BOLIBENCH_LIVE") == "1"),
    reason="LIVE, costs credits: needs ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID and BOLIBENCH_LIVE=1",
)
def test_live_elevenlabs_round_trip() -> None:
    t, s = elevenlabs_from_env()
    adapter = SpeechAdapter(FakeAgentAdapter(GOOD), t, s)
    record = run_case(CASE, adapter)
    assert record.execution_error is None
    [ev] = adapter.turns
    assert ev.audio_bytes > 0 and ev.transcript.text.strip()
    print(f"\nutterance:  {ev.utterance}\ntranscript: {ev.transcript.text}\nlanguage:   {ev.transcript.language} ({ev.transcript.language_probability})")
