import wave, struct, math

SR = 44100

def gen_du(path, freq, harmonics=False, beep=0.13, gap=0.07, amp=0.6):
    """合成"嘟嘟"两声:低频正弦、柔和、短促,中间留一点间隔。"""
    n_beep = int(SR * beep)
    n_gap = int(SR * gap)

    def beep_bytes():
        b = bytearray()
        for i in range(n_beep):
            t = i / SR
            env = math.exp(-t / (beep * 0.55))
            atk = min(1.0, t / 0.006)
            rel = min(1.0, (n_beep - i) / (0.012 * SR))
            s = math.sin(2 * math.pi * freq * t)
            if harmonics:
                s = (s + 0.25 * math.sin(2 * math.pi * 2 * freq * t)) / 1.25
            v = s * env * atk * rel * amp
            v = 1.0 if v > 1 else (-1.0 if v < -1 else v)
            b += struct.pack('<h', int(v * 32767))
        return b

    out = bytearray()
    out += beep_bytes()
    out += b'\x00\x00' * n_gap
    out += beep_bytes()

    w = wave.open(path, 'w')
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(bytes(out)); w.close()

gen_du('/tmp/du_a.wav', 620)
gen_du('/tmp/du_b.wav', 500)
gen_du('/tmp/du_c.wav', 740, harmonics=True)
print("generated du_a / du_b / du_c")
