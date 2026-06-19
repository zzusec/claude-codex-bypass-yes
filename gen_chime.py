import wave, struct, math

SR = 44100
# 钟/风铃的非谐波泛音比(金属质感的来源)
RATIOS = [1.0, 2.76, 5.40, 8.93]
AMPS   = [1.0, 0.6, 0.4, 0.25]

def gen(path, base, tau, dur, amp=0.75):
    n = int(SR * dur)
    norm = sum(AMPS)
    out = bytearray()
    for i in range(n):
        t = i / SR
        env = math.exp(-t / tau)          # 指数衰减(余音)
        atk = min(1.0, t / 0.004)          # 4ms 起音,避免爆音
        s = 0.0
        for r, a in zip(RATIOS, AMPS):
            s += a * math.sin(2 * math.pi * base * r * t)
        s = s / norm * env * atk * amp
        if s > 1.0: s = 1.0
        if s < -1.0: s = -1.0
        out += struct.pack('<h', int(s * 32767))
    w = wave.open(path, 'w')
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(bytes(out)); w.close()

# 三个风铃变体:明亮 / 温润长余音 / 极清脆短
gen('/tmp/chime_a.wav', 2640, 0.45, 1.4)   # a 明亮风铃
gen('/tmp/chime_b.wav', 1760, 0.70, 1.8)   # b 温润、余音长
gen('/tmp/chime_c.wav', 3520, 0.30, 1.0)   # c 极清脆、短
print("generated: chime_a / chime_b / chime_c")
