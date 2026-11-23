# Builds the Juggernaut sound set from CC0 sources (OpenGameArt) with Blender's audaspace (aud).
# Run: blender --factory-startup -b --python build_sfx.py -- <source_dir> <out_dir>
# Output: 44.1 kHz mono 16-bit WAV files (3D-positioned in game).
# Every intermediate result is baked into an in-memory buffer: streamed readers cannot seek reliably.
import sys, os
import aud
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], argv[1]
os.makedirs(OUT, exist_ok=True)
RATE = 44100


def bake(snd):
    data = snd.data()
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] > 1:
        data = data.mean(axis=1, keepdims=True)
    return aud.Sound.buffer(np.ascontiguousarray(data, dtype=np.float32), RATE)


def load(name):
    return bake(aud.Sound(os.path.join(SRC, name)).rechannel(1).resample(RATE, True))


def P(snd, factor):            # pitch + speed change (tape style)
    return bake(snd.pitch(factor).resample(RATE, True))


def TS(snd, stretch, pitch):   # independent time stretch and pitch
    return bake(snd.timeStretchPitchScale(stretch, pitch))


def F(snd, low=None, high=None):
    if low: snd = snd.lowpass(low)
    if high: snd = snd.highpass(high)
    return bake(snd)


def mix(*parts):
    """parts: (sound, gain, delay_seconds)"""
    arrays = []
    for snd, gain, delay in parts:
        d = snd.data()
        d = d[:, 0] if d.ndim > 1 else d
        arrays.append(np.concatenate([np.zeros(int(delay * RATE), np.float32), d * gain]))
    n = max(len(a) for a in arrays)
    out = np.zeros(n, np.float32)
    for a in arrays:
        out[:len(a)] += a
    return aud.Sound.buffer(out[:, None], RATE)


def shape(snd, length=None, fade_in=0.0, fade_out=0.0):
    d = snd.data()
    d = (d[:, 0] if d.ndim > 1 else d).copy()
    if length:
        d = d[:int(length * RATE)]
    n = len(d)
    if fade_in > 0:
        k = min(n, int(fade_in * RATE)); d[:k] *= np.linspace(0, 1, k)
    if fade_out > 0:
        k = min(n, int(fade_out * RATE)); d[n - k:] *= np.linspace(1, 0, k)
    return aud.Sound.buffer(d[:, None].astype(np.float32), RATE)


def save(snd, name, peak_db=-1.0):
    d = snd.data()
    d = d[:, 0] if d.ndim > 1 else d
    peak = float(np.max(np.abs(d))) or 1.0
    d = d * ((10 ** (peak_db / 20)) / peak)
    out = aud.Sound.buffer(d[:, None].astype(np.float32), RATE)
    path = os.path.join(OUT, name + ".wav")
    out.write(path, RATE, aud.CHANNELS_MONO, aud.FORMAT_S16, aud.CONTAINER_WAV, aud.CODEC_PCM)
    print("wrote", name, round(len(d) / RATE, 3), "s", flush=True)


stomp = load("stomp.flac")
squeeze = load("roboticsqueeze.flac")
clank = load("clank1.wav")

# ---- synthesis helpers (numpy) for the weight the CC0 recordings lack
def arr(snd):
    d = snd.data(); return (d[:, 0] if d.ndim > 1 else d).astype(np.float32)


def buf(x):
    return aud.Sound.buffer(np.ascontiguousarray(x, dtype=np.float32)[:, None], RATE)


def onepole_lp(x, fc):
    a = np.exp(-2 * np.pi * fc / RATE); y = np.empty_like(x); acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc; y[i] = acc
    return y


def lp(x, fc, order=2):
    for _ in range(order): x = onepole_lp(x, fc)
    return x


def hp(x, fc):
    return x - lp(x, fc, 1)


def sub_thump(rng, f0, f1, glide, decay, length):
    t = np.arange(int(length * RATE)) / RATE
    f = f1 + (f0 - f1) * np.exp(-t / glide)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    env = (1 - np.exp(-t / 0.003)) * np.exp(-t / decay)
    return (np.sin(phase) * env).astype(np.float32)


def body_hit(rng, decay, cutoff, length):
    t = np.arange(int(length * RATE)) / RATE
    n = rng.standard_normal(len(t)).astype(np.float32)
    return lp(n, cutoff, 3) * np.exp(-t / decay) * 6


def place(x, delay, total):
    out = np.zeros(total, np.float32); k = int(delay * RATE)
    m = min(len(x), total - k); out[k:k + m] += x[:m]; return out


def glue(x, drive=1.6):
    return np.tanh(x * drive) / np.tanh(drive)


rng = np.random.default_rng(7)
clunk = arr(load("lightclunk1.wav"))

def resonator(x, f, decay):
    # two-pole resonant filter: a struck low "drum" mode (the ground and the suit's mass ringing)
    r = np.exp(-1.0 / (decay * RATE)); c = 2 * r * np.cos(2 * np.pi * f / RATE); y = np.zeros_like(x); y1 = y2 = 0.0
    for i in range(len(x)):
        y0 = x[i] + c * y1 - r * r * y2; y[i] = y0; y2, y1 = y1, y0
    return y * (1 - r)


# 1) heavy footsteps: a dead, non-ringing "boom" of a ton landing. No tonal parts at all (no resonators,
#    no metal recording): only noise-based impact layers with fast decays, so nothing rings.
for i in range(1, 7):
    L = int(0.5 * RATE); t = np.arange(L) / RATE
    n = lambda: rng.standard_normal(L).astype(np.float32)
    att = np.clip(t / 0.002, 0, 1)
    low = lp(n(), 140, 4) * att * np.exp(-t / 0.055) * 19          # the weight: low thump, ~45 ms
    mid = hp(lp(n(), 700, 3), 150) * att * np.exp(-t / 0.018) * 3  # the impact body, ~18 ms
    grit = hp(lp(n(), 2500, 2), 600) * np.exp(-t / 0.006) * 0.35  # contact with the ground, very short
    jolt = np.zeros(L, np.float32)                                # armour plates jolting a beat later (noise, no tone)
    k = int((0.07 + 0.01 * (i % 3)) * RATE); tt = t[:L - k]
    jolt[k:] = hp(lp(rng.standard_normal(L - k).astype(np.float32), 1200, 2), 250) * np.exp(-tt / 0.012) * 0.6
    x = hp(hp(low + mid + grit + jolt, 55), 55)
    x *= np.clip((0.5 - t) / 0.15, 0, 1)
    save(buf(x), f"step_heavy_{i}", peak_db=-12.0)

# 2) servos: short low hydraulic actuator (no whine) - a geared motor around 80-120 Hz with tooth roughness,
#    dark, ending in a short pneumatic hiss
for i, (fa, fb) in enumerate([(78, 112), (86, 120), (72, 104)], 1):
    D = 0.42; L = int(0.7 * RATE); t = np.arange(int(D * RATE)) / RATE
    f = fa + (fb - fa) * np.sin(np.pi * np.clip(t / D, 0, 1)) ** 0.7
    ph = 2 * np.pi * np.cumsum(f) / RATE
    motor = sum(np.sin(k * ph) / k ** 1.3 for k in range(1, 9))
    motor *= 1 + 0.35 * np.sign(np.sin(ph * 6))          # gear teeth roughness
    env = np.clip(t / 0.03, 0, 1) * np.clip((D - t) / 0.08, 0, 1)
    motor = lp((motor * env).astype(np.float32), 1400, 2)
    tn = np.arange(int(0.3 * RATE)) / RATE
    hiss = hp(lp(rng.standard_normal(len(tn)).astype(np.float32), 3500, 2), 900) * np.exp(-tn / 0.08)
    thunk = sub_thump(rng, 110, 75, 0.02, 0.04, 0.2)
    x = place(motor, 0, L) * 0.8 + place(hiss, D - 0.05, L) * 0.25 + place(thunk, D - 0.04, L) * 0.5
    save(buf(hp(hp(x, 70), 70)), f"servo_{i}", peak_db=-16.0)

# 3) jump: short sharp servo + frame clank
save(shape(mix((shape(F(TS(squeeze, 1.1, 0.85), low=6000), fade_out=0.2), 1.0, 0),
               (P(clank, 0.9), 0.6, 0.18)), length=0.9, fade_out=0.15), "servo_jump")

# 4) landing: the step recipe, longer and harder, high-passed so it is weight, not sub-bass; no metal clank
L = int(0.7 * RATE); t = np.arange(L) / RATE
nz = lambda m: rng.standard_normal(m).astype(np.float32)
att = np.clip(t / 0.002, 0, 1)
x = (lp(nz(L), 180, 4) * att * np.exp(-t / 0.06) * 12 + hp(lp(nz(L), 900, 3), 150) * att * np.exp(-t / 0.03) * 3.5
     + hp(lp(nz(L), 2500, 2), 600) * np.exp(-t / 0.008) * 0.4)
k = int(0.09 * RATE); x[k:] += hp(lp(nz(L - k), 1200, 2), 250) * np.exp(-t[:L - k] / 0.02) * 0.9
x = hp(hp(x, 90), 90) * np.clip((0.7 - t) / 0.2, 0, 1)
save(buf(x), "land_heavy", peak_db=-10.0)

# 6) discharged frame: dry creaks and rattles
save(P(load("squeakyclick1.wav"), 0.8), "creak_1")
save(P(load("squeakyclick2.wav"), 0.75), "creak_2")
save(F(P(load("rattle1.wav"), 0.8), low=6000), "creak_3")

# 7) power up / power down: darkened mechanical latch + a low motor spinning up / down (no high whine)
def spin(f_from, f_to, dur):
    t = np.arange(int(dur * RATE)) / RATE
    f = f_from + (f_to - f_from) * (t / dur) ** 0.6
    ph = 2 * np.pi * np.cumsum(f) / RATE
    m = sum(np.sin(k * ph) / k ** 1.5 for k in range(1, 7))
    env = np.clip(t / 0.05, 0, 1) * np.clip((dur - t) / 0.25, 0, 1)
    return hp(lp((m * env).astype(np.float32), 900, 2), 70)


for name, src, f0, f1, delay in [("power_up", "mechanical1.wav", 40, 120, 0.12), ("power_down", "mechanical2.wav", 120, 35, 0.0)]:
    latch = lp(arr(P(load(src), 0.85)), 2500, 2)
    motor = spin(f0, f1, 0.9)
    L = int(1.3 * RATE); x = place(latch, 0, L) * 0.6 + place(motor, delay, L) * 0.5
    t = np.arange(L) / RATE; x *= np.clip((1.3 - t) / 0.3, 0, 1)
    save(buf(hp(x, 60)), name, peak_db=-12.0 if name == "power_up" else -16.0)
print("ALL OK", flush=True)
