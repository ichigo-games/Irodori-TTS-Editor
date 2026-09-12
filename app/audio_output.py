"""Build playback/export WAVs without changing the original synthesized audio."""
import hashlib
import os
import uuid
from pathlib import Path


def output_audio(source, pause_ms):
    source = Path(source)
    if not pause_ms:
        return source
    import numpy as np
    import soundfile as sf
    stat = source.stat()
    key = hashlib.sha256(f'{source.name}:{stat.st_mtime_ns}:{stat.st_size}:{pause_ms}'.encode()).hexdigest()
    cache = source.parent / 'padded'
    cache.mkdir(exist_ok=True)
    target = cache / f'{key}.wav'
    if target.exists():
        return target
    temp = cache / f'{uuid.uuid4().hex}.wav'
    try:
        with sf.SoundFile(source) as audio:
            with sf.SoundFile(temp, mode='w', samplerate=audio.samplerate, channels=audio.channels,
                              format='WAV', subtype=audio.subtype) as out:
                for block in audio.blocks(blocksize=65536, dtype='float64', always_2d=True):
                    out.write(block)
                remaining = (audio.samplerate * pause_ms + 500) // 1000
                silence = np.zeros((65536, audio.channels), dtype=np.float64)
                while remaining:
                    count = min(remaining, len(silence))
                    out.write(silence[:count])
                    remaining -= count
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
