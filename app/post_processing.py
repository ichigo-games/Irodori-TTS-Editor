"""Non-destructive EQ + peak control applied between the raw TTS WAV and playback/export.

Chain design: each enabled step transforms the float64 sample buffer in place.
Adding a future effect (De-esser, Compressor, Low/High cut, ...) means adding one
more step here; callers never need to change.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path


def _peaking_eq(samples, sr, frequency, gain_db, q):
    import numpy as np
    frequency = min(max(frequency, 20.0), sr / 2 - 1)
    q = max(q, 0.01)
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * frequency / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b0 = 1 + alpha * a
    b1 = -2 * cos_w0
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * cos_w0
    a2 = 1 - alpha / a
    b0, b1, b2, a1, a2 = (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

    # SciPy is supplied by the TTS environment; keep the existing fallback.
    try:
        from scipy.signal import lfilter
    except ImportError:
        pass
    else:
        return lfilter([b0, b1, b2], [1.0, a1, a2], samples)

    out = np.empty_like(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(samples)):
        x0 = samples[i]
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def _peak_control(samples, target_dbfs):
    import numpy as np
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0:
        return samples
    target_linear = 10 ** (target_dbfs / 20)
    if peak <= target_linear:
        return samples
    return samples * (target_linear / peak)


def _build_steps(pp):
    steps = []
    if pp.get('eq_enabled') and float(pp.get('gain_db', 0.0)) != 0:
        steps.append(('eq', float(pp.get('frequency', 3500.0)), float(pp.get('gain_db', 0.0)), float(pp.get('q', 1.0))))
    if pp.get('peak_enabled'):
        steps.append(('peak', float(pp.get('peak_dbfs', -1.0))))
    return steps


def process_audio(source, pp):
    """Apply the Post Processing chain described by `pp` to `source`, with caching.

    Returns `source` unchanged (no copy made) when no step is active.
    """
    source = Path(source)
    steps = _build_steps(pp or {})
    if not steps:
        return source

    import numpy as np
    import soundfile as sf

    stat = source.stat()
    key_data = f'{source.name}:{stat.st_mtime_ns}:{stat.st_size}:{json.dumps(steps, sort_keys=True)}'
    key = hashlib.sha256(key_data.encode()).hexdigest()
    cache = source.parent / 'processed'
    cache.mkdir(exist_ok=True)
    target = cache / f'{key}.wav'
    if target.exists():
        return target

    with sf.SoundFile(source) as audio:
        data = audio.read(dtype='float64', always_2d=True)
        sr = audio.samplerate
        subtype = audio.subtype

    for step in steps:
        if step[0] == 'eq':
            _, frequency, gain_db, q = step
            for ch in range(data.shape[1]):
                data[:, ch] = _peaking_eq(data[:, ch], sr, frequency, gain_db, q)
        else:
            _, peak_dbfs = step
            data = _peak_control(data, peak_dbfs)

    temp = cache / f'{uuid.uuid4().hex}.wav'
    try:
        sf.write(temp, data, sr, subtype=subtype, format='WAV')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
