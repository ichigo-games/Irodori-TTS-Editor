"""Read-only adapter to the installed Irodori runtime. Loaded only on first use."""
import os
import sys
from pathlib import Path


def resolve_checkpoint(download):
    local = os.environ.get('IRODORI_CHECKPOINT')
    if local:
        path = Path(local)
        if not path.is_file():
            raise FileNotFoundError(f'固定モデルが見つかりません: {path}')
        return str(path)
    return str(download(os.environ.get('IRODORI_HF_CHECKPOINT', 'Aratako/Irodori-TTS-v4.1-Small')))


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
                checkpoint=resolve_checkpoint(download_hf_checkpoint),
                model_device='cuda', codec_device='cuda',
            ))
        result = self.runtime.synthesize(SamplingRequest(
            text=text, ref_wav=reference, duration_scale=scale, seed=seed,
            num_steps=40, cfg_scale_text=3.0, cfg_scale_speaker=5.0,
        ))
        save_wav(Path(path), result.audio, result.sample_rate)
        return result.used_seed
