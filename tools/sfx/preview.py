# Renders an in-game-like preview of the suit sounds (no game needed): walk, run, sprint, turns, jumps,
# discharge and power-up, mixed with the same volumes and cooldowns JugSound.cs uses.
# Run: python preview.py <sfx_dir> <out_dir>
import sys, os, glob, numpy as np, scipy.io.wavfile as w
SFX, OUT = sys.argv[1], sys.argv[2]
R = 44100
clips = {os.path.splitext(os.path.basename(p))[0]: w.read(p)[1].astype(np.float32) / 32768 for p in glob.glob(os.path.join(SFX, "*.wav"))}
rng = np.random.default_rng(3)
events, marks = [], []


def pick(prefix):
    names = sorted(k for k in clips if k.startswith(prefix)); return names[rng.integers(len(names))]


def play(t, prefix, vol, jitter=0.06):
    events.append((t, pick(prefix), vol, 1 + rng.uniform(-jitter, jitter)))


def mark(t, text): marks.append((t, text))


t = 1.0
servo_ready = 0.0


def servo(t):
    global servo_ready
    if t >= servo_ready: play(t, "servo_", 0.5, 0.05); servo_ready = t + 1.6


def steps(t, seconds, interval, vol=1.0):
    end = t + seconds
    while t < end: play(t, "step_heavy", vol); t += interval * rng.uniform(0.96, 1.04)
    return end


mark(t, "walk (start: servo)"); servo(t); t = steps(t + 0.15, 4.0, 0.58)
t += 1.0; mark(t, "run"); servo(t); t = steps(t + 0.15, 4.0, 0.40)
t += 1.0; mark(t, "sprint with two sharp turns"); servo(t); s = t + 0.15
steps(s, 6.0, 0.34); servo(s + 2.0); servo(s + 4.0); t = s + 6.0
for k in range(3):
    t += 1.2; mark(t, f"jump {k + 1}"); play(t, "servo_jump", 0.9, 0.05)
    air = 0.75 + 0.15 * k; play(t + air, "land_heavy", min(1.0, 0.6 + air * 0.5), 0.04)
    t += air
t += 1.5; mark(t, "power down (no cells)"); play(t, "power_down", 1.0, 0)
t += 2.0; mark(t, "walking discharged (creaks)"); e = t + 5.0; ready = 0
while t < e:
    play(t, "step_heavy", 0.85)
    if rng.random() < 0.35 and t >= ready: play(t + 0.05, "creak", 0.7); ready = t + 1.2
    t += 0.62
t += 1.0; mark(t, "power up (cell inserted)"); play(t, "power_up", 1.0, 0)
t += 2.5

out = np.zeros(int(t * R) + R, np.float32)
for at, name, vol, pitch in events:
    x = clips[name]; idx = np.arange(0, len(x) - 1, pitch); y = np.interp(idx, np.arange(len(x)), x) * vol
    k = int(at * R); out[k:k + len(y)] += y[:len(out) - k]
os.makedirs(OUT, exist_ok=True)
w.write(os.path.join(OUT, "juggernaut_preview.wav"), R, (np.clip(out, -1, 1) * 32767).astype(np.int16))

# every sound once, 1.2 s apart, in the same order as the list file
names = sorted(clips); sheet = []; pos = 0.5
for n in names: sheet.append((pos, n)); pos += len(clips[n]) / R + 1.2
o2 = np.zeros(int(pos * R), np.float32)
for at, n in sheet: k = int(at * R); o2[k:k + len(clips[n])] += clips[n]
w.write(os.path.join(OUT, "juggernaut_all_sounds.wav"), R, (np.clip(o2, -1, 1) * 32767).astype(np.int16))

with open(os.path.join(OUT, "timeline.txt"), "w", encoding="utf-8") as f:
    f.write("juggernaut_preview.wav\n")
    for at, text in marks: f.write(f"  {int(at // 60)}:{at % 60:05.2f}  {text}\n")
    f.write("\njuggernaut_all_sounds.wav (each sound once)\n")
    for at, n in sheet: f.write(f"  {int(at // 60)}:{at % 60:05.2f}  {n}\n")
print("preview", round(len(out) / R, 1), "s; peak", round(20 * np.log10(np.abs(out).max()), 1), "dB")
