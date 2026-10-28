"""Regression checks for video-only second pass of joint H3 AV latents."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

import torch
import comfy.nested_tensor


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hutx_second_pass_audio_test"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
preserve = importlib.import_module(f"{PACKAGE}.second_pass_audio").preserve_first_pass_audio


def latent(video, audio, *, video_mask=None, audio_mask=None, mode=None):
    value = {"samples": comfy.nested_tensor.NestedTensor((video, audio))}
    if video_mask is not None or audio_mask is not None:
        value["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    if mode is not None:
        value["gh_h3_audio_mode"] = mode
    return value


class SecondPassAudioTests(unittest.TestCase):
    def test_preserves_first_pass_audio_and_selected_video_without_mutation(self):
        video = torch.zeros((1, 24, 2, 2, 2))
        audio = torch.ones((1, 32, 2, 3))
        first = latent(video, audio, mode="native")
        selected = latent(video + 2, audio + 3, mode="lock_source")
        result = preserve(first, selected)
        self.assertTrue(torch.equal(result["samples"].unbind()[0], video + 2))
        self.assertTrue(torch.equal(result["samples"].unbind()[1], audio))
        self.assertEqual(result["gh_h3_audio_mode"], "native")
        self.assertTrue(torch.equal(selected["samples"].unbind()[1], audio + 3))
        self.assertTrue(torch.equal(first["samples"].unbind()[0], video))

    def test_preserves_audio_mask_and_selected_video_mask(self):
        video = torch.zeros((1, 24, 2, 2, 2))
        audio = torch.ones((1, 32, 2, 3))
        first = latent(video, audio, video_mask=torch.ones_like(video),
                       audio_mask=torch.zeros_like(audio))
        selected = latent(video + 2, audio + 3, video_mask=torch.full_like(video, 0.5),
                          audio_mask=torch.ones_like(audio))
        result = preserve(first, selected)
        masks = result["noise_mask"].unbind()
        self.assertTrue(torch.equal(masks[0], selected["noise_mask"].unbind()[0]))
        self.assertTrue(torch.equal(masks[1], first["noise_mask"].unbind()[1]))

    def test_rejects_audio_timeline_change(self):
        video = torch.zeros((1, 24, 2, 2, 2))
        first = latent(video, torch.zeros((1, 32, 2, 3)))
        selected = latent(video, torch.zeros((1, 32, 2, 4)))
        with self.assertRaisesRegex(ValueError, "audio latent shapes differ"):
            preserve(first, selected)


if __name__ == "__main__":
    unittest.main()
