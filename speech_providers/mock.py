"""Audible test tone, explicitly NOT speech synthesis or a cloned voice."""
import math
import struct
from ..speech_validation import PCM, SpeechCancelled


class MockSpeechProvider:
    version = 'hutx-mock-pcm-v1'

    def synthesize(self, request, reference, cancel):
        # Delay makes running/cancel UI testable without any external service.
        if cancel.wait(0.2):
            raise SpeechCancelled('已取消。')
        seconds = min(60.0, max(0.25, len(request['text'].strip()) / (5 * request['speed'])))
        rate = 16000
        frequency = 440 if request['engine'] == 'local' else 550
        if request['voice'].endswith('demo-b'):
            frequency += 110
        data = bytearray()
        for i in range(round(seconds * rate)):
            if i % 4096 == 0 and cancel.is_set():
                raise SpeechCancelled('已取消。')
            envelope = min(1, i / 160, (seconds * rate - i) / 160)
            data.extend(struct.pack('<h', round(900 * envelope * math.sin(2 * math.pi * frequency * i / rate))))
        return PCM(bytes(data), rate)
