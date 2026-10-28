# CosyVoice example reference voices

Source: https://github.com/FunAudioLLM/CosyVoice
Upstream files: `asset/zero_shot_prompt.wav` (A), `asset/cross_lingual_prompt.wav` (B).
Imported from this installation's pinned CosyVoice checkout. Original repository license is included in LICENSE-CosyVoice.txt (Apache-2.0).

Modification: converted to signed PCM16 WAV; original sampling rate, duration and channel count preserved. These are upstream demonstration reference recordings, not native CosyVoice3 speaker IDs. No user recordings are bundled.

A uses the reference transcript from upstream example.py. B uses the existing offline reference transcription path. New dialogue is synthesized by the existing local zero-shot adapter. Labels deliberately do not claim a celebrity, profession or an unverified voice characteristic.

PCM16 SHA256:
- a.wav: 3c7fde5179ad8d84cf45afa9541b149ff689f867c586fe08c9dfce7368a7f1fb
- b.wav: 353a7715c2e4811f4045658b29d1ce67ecad5120e09de10ce890f1763aab486c
