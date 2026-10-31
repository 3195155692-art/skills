#!/usr/bin/env python3
"""Generate the neural-trace motif used as the deck's single repeating visual element.

Three transparent PNGs:
  wave_dark.png   bright cyan trace for dark pages
  wave_light.png  quiet navy trace for light pages
  wave_mark.png   the small mark that sits in every content-page header

The trace is deterministic (fixed seeds), so regenerating gives the same deck. Replace the
signal or the colour if the subject calls for a different motif — the point is one element
repeated everywhere, not this particular waveform.

Usage:
    python3 make_motif.py --out ../assets [--rgb 2F,B8,C6]
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys

from PIL import Image, ImageDraw


def _envelope(i: int, n: int, pad: float = 0.06) -> float:
    """Fade the trace at both ends so it never butts hard against an edge."""
    t = i / (n - 1)
    if t < pad:
        return math.sin(math.pi * 0.5 * (t / pad)) ** 1.5
    if t > 1 - pad:
        return math.sin(math.pi * 0.5 * ((1 - t) / pad)) ** 1.5
    return 1.0


def _signal(n: int, seed: int) -> list[float]:
    """Deterministic EEG-ish trace: slow drift + ripple + a few sharp transients."""
    rng = random.Random(seed)
    spikes = [
        (rng.uniform(0.05, 0.95), rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 1.0))
        for _ in range(14)
    ]
    out = []
    for i in range(n):
        t = i / (n - 1)
        v = (
            0.55 * math.sin(2 * math.pi * 1.6 * t + 0.4)
            + 0.30 * math.sin(2 * math.pi * 4.3 * t + 1.9)
            + 0.18 * math.sin(2 * math.pi * 9.1 * t + 3.1)
            + 0.10 * math.sin(2 * math.pi * 17.0 * t + 0.7)
            + 0.06 * math.sin(2 * math.pi * 41.0 * t + 2.2) * math.sin(2 * math.pi * 0.9 * t)
        )
        for pos, sign in spikes:
            d = abs(t - pos)
            if d < 0.010:
                v += sign * (1.0 - d / 0.010) ** 2 * 1.9
        out.append(v * _envelope(i, n))
    return out


def draw_trace(path, width, height, rgb, peak_alpha, lines, dpi=220):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    mid = height / 2.0
    for idx, (seed, amp_scale, alpha_scale) in enumerate(lines):
        raw = _signal(width, seed=seed)
        peak = max(abs(v) for v in raw) or 1.0
        # normalise so a transient never clips against the canvas edge
        vals = [v / peak * amp_scale for v in raw]
        pts = [(x, mid + v * (height * 0.45)) for x, v in enumerate(vals)]
        alpha = max(6, min(255, int(peak_alpha * alpha_scale)))
        draw.line(pts, fill=(rgb[0], rgb[1], rgb[2], alpha), width=3 if idx == 0 else 2,
                  joint="curve")
    img.save(path, dpi=(dpi, dpi))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "..", "assets"))
    ap.add_argument("--rgb", default="2F,B8,C6", help="accent colour as R,G,B hex (default cyan)")
    ap.add_argument("--ink", default="17,52,7A", help="quiet colour as R,G,B hex for light pages")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    accent = tuple(int(v, 16) for v in args.rgb.split(","))
    quiet = tuple(int(v, 16) for v in args.ink.split(","))

    draw_trace(os.path.join(out, "wave_dark.png"), 3000, 560, accent, 205,
               [(11, 1.00, 1.00), (77, 0.62, 0.38), (131, 0.40, 0.26)])
    draw_trace(os.path.join(out, "wave_light.png"), 3000, 560, quiet, 95,
               [(11, 1.00, 1.00), (77, 0.58, 0.45)])
    draw_trace(os.path.join(out, "wave_mark.png"), 1080, 300, accent, 200,
               [(23, 0.95, 1.00)])

    for name in sorted(os.listdir(out)):
        if name.endswith(".png"):
            print(f"  {name:18s} {os.path.getsize(os.path.join(out, name)):>7d} bytes")
    print("written to", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
