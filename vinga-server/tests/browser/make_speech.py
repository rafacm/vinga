"""Write `speech.wav`, the sentence the browser lane's fake microphone
says, from the utterance the simulator ships.

The lane needs real speech rather than a tone: the page asks for noise
suppression, as it should, and a steady tone is exactly what a noise
suppressor is built to remove. The packaged utterance is a Piper
sentence ("Hello, can you hear me?") whose provenance is recorded
beside it in `src/vinga_server/simulator/data/utterance.json`, so this
decodes that rather than committing audio of unknown origin. Run it
from `vinga-server/` when the packaged utterance changes:

    uv run python -m tests.browser.make_speech

The lane composes the microphone's whole loop (this sentence, the
silences between) at run time from this file, with the standard
library alone, so the timing it depends on is read in the lane rather
than baked into a recording.
"""

import wave
from pathlib import Path

from vinga_server.audio.opus import OpusDecoder
from vinga_server.simulator.utterance import packaged

SPEECH = Path(__file__).with_name("speech.wav")


def main() -> None:
    utterance = packaged()
    decoder = OpusDecoder(sample_rate=utterance.sample_rate)
    pcm = b"".join(decoder.decode(packet) for packet in utterance.packets)
    with wave.open(str(SPEECH), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(utterance.sample_rate)
        out.writeframes(pcm)
    print(f"wrote {SPEECH} ({len(pcm) // 2} samples at {utterance.sample_rate} Hz)")


if __name__ == "__main__":
    main()
