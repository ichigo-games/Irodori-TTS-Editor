"""Read-only adapter to the installed Irodori runtime. Loaded only on first use."""
import os
import sys
from pathlib import Path


class IrodoriEngine:
    def __init__(self):
        self.runtime = None

    def generate(self, text, reference, scale, seed, path):
        sys.dont_write_bytecode = True
        engine_home = os.environ.get('IRODORI_HOME', r'E:\Irodori-TTS')
        if engine_home not in sys.path:
            sys.path.insert(0, engine_home)
        from irodori_tts.inference_runtime import (
            InferenceRuntime, RuntimeKey, SamplingRequest, download_hf_checkpoint, save_wav,
        )
        if self.runtime is None:
            self.runtime = InferenceRuntime.from_key(RuntimeKey(
                checkpoint=str(download_hf_checkpoint('Aratako/Irodori-TTS-v4.1-Small')),
                model_device='cuda', codec_device='cuda',
            ))
        result = self.runtime.synthesize(SamplingRequest(
            text=text, ref_wav=reference, duration_scale=scale, seed=seed,
            num_steps=40, cfg_scale_text=3.0, cfg_scale_speaker=5.0,
        ))
        save_wav(Path(path), result.audio, result.sample_rate)
        return result.used_seed
