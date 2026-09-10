"""The Silero endpointer: real model for the silence path, a scripted
detector for the timing bookkeeping (real speech detection is verified
against hardware, not synthesizable in a unit test)."""

from vinga_server.config.models import ProviderConfig
from vinga_server.providers import build_entry
from vinga_server.providers.silero import SileroEndpointer, SileroVad

WINDOW_BYTES = 1024  # 512 samples at 16 kHz, Silero's fixed window
WINDOW_MS = 32


class ScriptedDetector:
    """Stands in for the Silero model: answers the scripted speech
    probabilities in order, then silence forever."""

    def __init__(self, probs: list[float]) -> None:
        self._probs = iter(probs)
        self.resets = 0

    def __call__(self, window: bytes) -> float:
        return next(self._probs, 0.0)

    def reset(self) -> None:
        self.resets += 1

    def chunk_bytes(self) -> int:
        return WINDOW_BYTES

    def chunk_samples(self) -> int:
        return WINDOW_BYTES // 2


def scripted_endpointer(
    probs: list[float], detector: "ScriptedDetector | None" = None, **kwargs: float
) -> SileroEndpointer:
    """An endpointer whose model answers the probabilities the test
    wrote down.

    White-box, deliberately, and the only reach-in in this file. The
    ONNX model is loaded inside the endpointer, from a file the test
    lane does not ship, and the state machine under test is the one that
    reads its probabilities: what a window was scored is the input, and
    an endpointer takes audio rather than scores. Handed back rather
    than read off again, so the one test that asks the model what it was
    told holds the object it planted.
    """
    endpointer = SileroEndpointer(
        threshold=kwargs.get("threshold", 0.5),
        trailing_silence_ms=kwargs.get("trailing_silence_ms", 700.0),
        max_utterance_ms=kwargs.get("max_utterance_ms", 10_000.0),
    )
    endpointer._detector = detector if detector is not None else ScriptedDetector(probs)
    return endpointer


def feed_windows(endpointer: SileroEndpointer, count: int) -> list[bool]:
    return [endpointer.feed(b"\x00" * WINDOW_BYTES) for _ in range(count)]


async def test_the_registry_builds_silero_with_options() -> None:
    provider = await build_entry(
        "vad", "ears", ProviderConfig.model_validate({"type": "silero", "threshold": 0.6})
    )
    assert isinstance(provider, SileroVad)
    assert isinstance(provider.new_endpointer(), SileroEndpointer)


def test_real_model_silence_never_ends_an_utterance_that_never_began() -> None:
    endpointer = SileroVad(0.5, 700.0, 10_000.0).new_endpointer()
    # Five seconds of digital silence through the real model.
    assert not any(endpointer.feed(b"\x00" * WINDOW_BYTES * 5) for _ in range(31))


def test_speech_start_is_reported_to_window_granularity() -> None:
    silence_windows = 10
    endpointer = scripted_endpointer([0.0] * silence_windows + [0.9] * 5)
    feed_windows(endpointer, silence_windows)
    assert endpointer.speech_start() is None
    feed_windows(endpointer, 5)
    assert endpointer.speech_start() == silence_windows * WINDOW_BYTES
    endpointer.reset()
    assert endpointer.speech_start() is None


def test_speech_ms_counts_speech_windows_to_window_granularity() -> None:
    # 5 silent windows, 10 speech, 5 silent, 5 speech: only the 15
    # speech windows count, whatever came between them.
    endpointer = scripted_endpointer([0.0] * 5 + [0.9] * 10 + [0.0] * 5 + [0.9] * 5)
    assert endpointer.speech_ms() == 0.0
    feed_windows(endpointer, 25)
    assert endpointer.speech_ms() == 15 * WINDOW_MS
    endpointer.reset()
    assert endpointer.speech_ms() == 0.0


def test_speech_then_trailing_silence_ends_the_utterance() -> None:
    speech_windows = 20  # 640 ms of speech
    endpointer = scripted_endpointer([0.9] * speech_windows)
    assert not any(feed_windows(endpointer, speech_windows))
    decisions = feed_windows(endpointer, 30)
    assert any(decisions)
    ended_after_ms = (decisions.index(True) + 1) * WINDOW_MS
    assert 700 <= ended_after_ms <= 800


def test_a_short_pause_does_not_end_the_utterance() -> None:
    # 320 ms of speech, a 320 ms pause, then more speech.
    endpointer = scripted_endpointer([0.9] * 10 + [0.0] * 10 + [0.9] * 10)
    assert not any(feed_windows(endpointer, 30))


def test_droning_on_hits_the_utterance_cap() -> None:
    endpointer = scripted_endpointer([0.9] * 100, max_utterance_ms=1000.0)
    decisions = feed_windows(endpointer, 40)
    assert any(decisions)
    assert (decisions.index(True) + 1) * WINDOW_MS <= 1024


def test_odd_sized_chunks_are_buffered_into_whole_windows() -> None:
    endpointer = scripted_endpointer([0.9] * 4, trailing_silence_ms=64.0)
    # 6 windows of audio arrive in ragged pieces: 4 speech + 2 silence.
    ragged = b"\x00" * (WINDOW_BYTES * 6)
    for start in range(0, len(ragged), 700):
        ended = endpointer.feed(ragged[start : start + 700])
    assert ended is True


def test_reset_forgets_speech_and_resets_the_model_state() -> None:
    detector = ScriptedDetector([0.9] * 10)
    endpointer = scripted_endpointer([0.9] * 10, detector)
    feed_windows(endpointer, 10)
    endpointer.reset()
    assert detector.resets == 1
    assert not any(feed_windows(endpointer, 40))


# --- forgetting the audio without forgetting the utterance (#456) ------
#
# `reset` bundles two things a session sometimes wants separately: the
# model's recurrent state, which carries the assistant's own playback
# echo into the pause a user answers in, and the endpointer's own
# accounting, which belongs to whatever the user is in the middle of
# saying. `forget_audio` is the first half alone.

# The trailing-silence budget, in whole windows: 700 ms of silence after
# speech ends an utterance, and 700 / 32 is a little under 22, so 22
# sub-threshold windows in a row is what it takes.
BUDGET_WINDOWS = 22

# What a mid-speech reset actually costs, measured by replaying an
# utterance the server heard through the committed model and resetting
# the detector in the middle of it (#70): one 32 ms window under the
# threshold, then back over it and climbing.
MEASURED_REWARM_WINDOWS = 1


class RewarmingDetector:
    """A model that needs a run of windows to find speech again after
    its state is cleared, which is the one cost a recurrent detector's
    reset has. Speech before the reset, `windows` of sub-threshold
    scores after it, then speech again."""

    def __init__(self, windows: int) -> None:
        self._windows = windows
        self._cold = 0
        self.resets = 0

    def __call__(self, window: bytes) -> float:
        if self._cold > 0:
            self._cold -= 1
            return 0.0
        return 0.9

    def reset(self) -> None:
        self.resets += 1
        self._cold = self._windows

    def chunk_bytes(self) -> int:
        return WINDOW_BYTES

    def chunk_samples(self) -> int:
        return WINDOW_BYTES // 2


def test_forgetting_the_audio_clears_the_model_and_keeps_the_accounting() -> None:
    """The split the fix rests on: the detector goes back to knowing
    nothing, and every number the endpointer keeps stays where it was.

    An utterance in progress therefore survives a reply ending under it
    (#80): the speech already heard still counts, the speech-start
    offset still points at where it began, and the trailing-silence
    window picks up where it stood rather than from zero.
    """
    detector = ScriptedDetector([0.9] * 10 + [0.0] * 100)
    endpointer = scripted_endpointer([], detector)
    feed_windows(endpointer, 10)

    endpointer.forget_audio()

    assert detector.resets == 1
    assert endpointer.speech_ms() == 10 * WINDOW_MS
    assert endpointer.speech_start() == 0
    # And the utterance still ends on its own trailing silence, which is
    # what a `reset()` here would have made unreachable: with no speech
    # remembered, silence counts toward nothing at all.
    assert any(feed_windows(endpointer, BUDGET_WINDOWS))


def test_a_mid_speech_forget_costs_far_less_than_the_trailing_silence_budget() -> None:
    """The margin, rather than a probability.

    A recurrent model scores low for a moment after its state is
    cleared, and long enough of that would look like the trailing
    silence that ends an utterance. The claim is not that the re-warm
    is free; it is that it is roughly one window against a budget of
    roughly twenty-two, so a reply ending in the middle of a sentence
    cannot endpoint it.
    """
    for rewarm in (MEASURED_REWARM_WINDOWS, MEASURED_REWARM_WINDOWS * 10):
        detector = RewarmingDetector(rewarm)
        endpointer = scripted_endpointer([], detector)
        feed_windows(endpointer, 5)
        endpointer.forget_audio()
        assert not any(feed_windows(endpointer, rewarm + 5)), (
            f"a re-warm of {rewarm} windows ended the utterance"
        )

    # And what it would take to break that: a re-warm as long as the
    # whole budget, which is the distance the measurement leaves.
    detector = RewarmingDetector(BUDGET_WINDOWS)
    endpointer = scripted_endpointer([], detector)
    feed_windows(endpointer, 5)
    endpointer.forget_audio()
    assert any(feed_windows(endpointer, BUDGET_WINDOWS))
