#!/usr/bin/env python3
"""Guitar / bass fretboard diagram generator.

Draws a fretboard as PNG or JPG and labels each position with either the
note name (C D E F G A B) or numbered notation / 簡譜 (1-7, movable do).

Examples:
    python fretboard.py -o guitar_c.png
    python fretboard.py --instrument bass4 --labels jianpu --key G -o bass_g.png
    python fretboard.py --scale pentatonic-minor --key A --frets 15 -o am_penta.jpg
    python fretboard.py --tuning "D2 A2 D3 G3 B3 E4" --scale all -o dropd.png
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- music data

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Degree names relative to the key tonic, indexed by semitone distance.
JIANPU_SHARP = ["1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7"]
JIANPU_FLAT = ["1", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7"]
# Mixed spelling most players use (b3, b6, b7, #4 ...).
JIANPU_MIXED = ["1", "b2", "2", "b3", "3", "4", "#4", "5", "b6", "6", "b7", "7"]

NOTE_TO_PC = {
    "C": 0, "B#": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
    "FB": 4, "F": 5, "E#": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8,
    "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11,
}

SCALES = {
    "all": list(range(12)),
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic-minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic-minor": [0, 2, 3, 5, 7, 9, 11],
    "pentatonic-major": [0, 2, 4, 7, 9],
    "pentatonic-minor": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
}

# Tunings are listed from the lowest (thickest) string to the highest.
INSTRUMENTS = {
    "guitar": "E2 A2 D3 G3 B3 E4",
    "guitar7": "B1 E2 A2 D3 G3 B3 E4",
    "bass4": "E1 A1 D2 G2",
    "bass5": "B0 E1 A1 D2 G2",
    "bass6": "B0 E1 A1 D2 G2 C3",
    "ukulele": "G4 C4 E4 A4",
}

INLAYS = [3, 5, 7, 9, 15, 17, 19, 21]
DOUBLE_INLAYS = [12, 24]


def parse_note(text):
    """'E2' -> MIDI number, 'Bb' -> pitch class (octave optional)."""
    t = text.strip()
    i = len(t)
    while i > 0 and (t[i - 1].isdigit() or t[i - 1] == "-"):
        i -= 1
    name, octave = t[:i], t[i:]
    key = name[:1].upper() + name[1:].upper()
    if key not in NOTE_TO_PC:
        raise ValueError(f"unknown note: {text!r}")
    pc = NOTE_TO_PC[key]
    return pc + 12 * (int(octave) + 1) if octave else pc


def parse_tuning(text):
    return [parse_note(n) for n in text.replace(",", " ").split()]


# ---------------------------------------------------------------- drawing

FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "arialbd.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


THEMES = {
    "light": dict(
        bg="#ffffff", board="#f3e2c3", fret="#9a9a9a", nut="#2b2b2b",
        string="#555555", inlay="#d8c39e", text="#222222",
        dot="#2f6db5", dot_text="#ffffff", root="#d1452f", root_text="#ffffff",
        other="#ffffff", other_text="#555555", other_edge="#aaaaaa",
    ),
    "dark": dict(
        bg="#1c1c1e", board="#3b2a1d", fret="#b8b8b8", nut="#e8e2d0",
        string="#d8d0c0", inlay="#5a4430", text="#eeeeee",
        dot="#4c8fe0", dot_text="#ffffff", root="#e85d43", root_text="#ffffff",
        other="#2c2c2e", other_text="#bbbbbb", other_edge="#777777",
    ),
}


def fret_positions(frets, fret_w, spacing):
    """x offset of each fret wire, measured from the nut."""
    if spacing == "equal":
        return [i * fret_w for i in range(frets + 1)]
    # Real proportions (each fret is 2^(1/12) shorter), normalised so the
    # whole board is as wide as the equal-spacing version.
    pos = [1 - 2 ** (-i / 12) for i in range(frets + 1)]
    # Keep the narrowest (highest) fret at least 60% of fret_w so labels fit.
    scale = max(frets * fret_w / pos[-1], 0.6 * fret_w / (pos[-1] - pos[-2]))
    return [p * scale for p in pos]


def label_for(midi, key_pc, mode, accidental):
    pc = midi % 12
    if mode == "note":
        return (FLAT_NAMES if accidental == "flat" else SHARP_NAMES)[pc]
    if mode == "jianpu":
        table = {"sharp": JIANPU_SHARP, "flat": JIANPU_FLAT}.get(accidental, JIANPU_MIXED)
        return table[(pc - key_pc) % 12]
    if mode == "octave":
        names = FLAT_NAMES if accidental == "flat" else SHARP_NAMES
        return f"{names[pc]}{midi // 12 - 1}"
    raise ValueError(mode)


def draw(args):
    tuning = parse_tuning(args.tuning or INSTRUMENTS[args.instrument])
    if any(n < 12 for n in tuning):
        raise SystemExit("tuning notes need an octave number, e.g. E2 A2 D3")
    key_pc = parse_note(args.key) % 12
    scale = set((key_pc + s) % 12 for s in SCALES[args.scale])
    theme = THEMES[args.theme]
    k = args.zoom

    n_str = len(tuning)
    fret_w, gap = 72 * k, 44 * k
    r = int(15 * k)                 # note dot radius
    left = 70 * k                   # room for open-string labels + nut
    top = (70 if args.title else 30) * k
    bottom = 50 * k                 # fret numbers
    right = 30 * k
    xs = fret_positions(args.frets, fret_w, args.spacing)
    board_w = xs[-1]
    board_h = (n_str - 1) * gap
    W = int(left + board_w + right)
    H = int(top + board_h + bottom)

    img = Image.new("RGB", (W, H), theme["bg"])
    d = ImageDraw.Draw(img)
    f_dot = load_font(int(13 * k))
    f_small = load_font(int(14 * k))
    f_title = load_font(int(22 * k))

    def X(x):  # mirror horizontally for left-handed players
        return W - (left + x) if args.lefty else left + x

    def string_y(i):  # i = 0 is the lowest string, drawn at the bottom
        return top + (n_str - 1 - i) * gap

    pad = gap * 0.45
    x0, x1 = sorted((X(0), X(board_w)))
    d.rectangle([x0, top - pad, x1, top + board_h + pad], fill=theme["board"])

    # inlays
    # inlay dots sit between strings, never on one
    mid = top + (round((board_h / gap - 1) / 2) + 0.5) * gap if n_str > 1 else top
    for f in range(1, args.frets + 1):
        cx = X((xs[f - 1] + xs[f]) / 2)
        ir = 7 * k
        if f in INLAYS:
            d.ellipse([cx - ir, mid - ir, cx + ir, mid + ir], fill=theme["inlay"])
        elif f in DOUBLE_INLAYS:
            for cy in (mid - gap, mid + gap):
                d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=theme["inlay"])

    # frets, nut
    for f in range(1, args.frets + 1):
        x = X(xs[f])
        d.line([x, top - pad, x, top + board_h + pad], fill=theme["fret"], width=max(2, int(3 * k)))
    nx = X(0)
    d.line([nx, top - pad, nx, top + board_h + pad], fill=theme["nut"], width=int(8 * k))

    # strings (thicker for lower strings)
    for i in range(n_str):
        y = string_y(i)
        w = max(1, int((1 + (n_str - 1 - i) * 0.5) * k))
        d.line([X(0), y, X(board_w), y], fill=theme["string"], width=w)

    # fret numbers
    for f in range(1, args.frets + 1):
        cx = X((xs[f - 1] + xs[f]) / 2)
        d.text((cx, top + board_h + pad + 16 * k), str(f), fill=theme["text"], font=f_small, anchor="mm")

    # notes
    for i, open_midi in enumerate(tuning):
        y = string_y(i)
        for f in range(0, args.frets + 1):
            midi = open_midi + f
            pc = midi % 12
            in_scale = pc in scale
            if not in_scale and not args.show_all:
                continue
            if f == 0:
                cx = X(-left * 0.5)
            else:
                cx = X((xs[f - 1] + xs[f]) / 2)
            if not in_scale:
                fill, txt, edge = theme["other"], theme["other_text"], theme["other_edge"]
            elif pc == key_pc and (args.labels == "jianpu" or args.highlight_root):
                fill, txt, edge = theme["root"], theme["root_text"], None
            else:
                fill, txt, edge = theme["dot"], theme["dot_text"], None
            d.ellipse([cx - r, y - r, cx + r, y + r], fill=fill, outline=edge, width=max(1, int(k)))
            d.text((cx, y), label_for(midi, key_pc, args.labels, args.accidental),
                   fill=txt, font=f_dot, anchor="mm")

    if args.title:
        d.text((W / 2, 32 * k), args.title, fill=theme["text"], font=f_title, anchor="mm")

    ext = os.path.splitext(args.output)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(args.output, "JPEG", quality=95)
    else:
        img.save(args.output, "PNG")
    return args.output


def default_title(args):
    inst = args.tuning or args.instrument
    labels = {"note": "Note names", "jianpu": "Jianpu (1 = %s)" % args.key, "octave": "Notes + octave"}
    scale = "chromatic" if args.scale == "all" else f"{args.key} {args.scale}"
    return f"{inst}  |  {scale}  |  {labels[args.labels]}"


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate guitar / bass fretboard diagrams (PNG/JPG).")
    p.add_argument("-o", "--output", default="fretboard.png", help="output file (.png / .jpg)")
    p.add_argument("-i", "--instrument", choices=INSTRUMENTS, default="guitar",
                   help="preset tuning (default: guitar)")
    p.add_argument("-t", "--tuning", help='custom tuning, low to high, e.g. "D2 A2 D3 G3 B3 E4"')
    p.add_argument("-f", "--frets", type=int, default=12, help="number of frets (default 12)")
    p.add_argument("-l", "--labels", choices=["note", "jianpu", "octave"], default="note",
                   help="note = C D E..., jianpu = 簡譜 1-7, octave = C4 style")
    p.add_argument("-k", "--key", default="C", help="key / tonic, used as '1' in jianpu (default C)")
    p.add_argument("-s", "--scale", choices=SCALES, default="major",
                   help="which notes to show (default major; 'all' = every note)")
    p.add_argument("--show-all", action="store_true",
                   help="also show notes outside the scale as hollow dots")
    p.add_argument("--accidental", choices=["sharp", "flat", "auto"], default="auto",
                   help="spell accidentals with # or b (auto: # for notes, mixed for jianpu)")
    p.add_argument("--highlight-root", action="store_true",
                   help="colour the tonic in note mode too (always on for jianpu)")
    p.add_argument("--spacing", choices=["equal", "real"], default="equal",
                   help="equal-width frets or real fret proportions")
    p.add_argument("--theme", choices=THEMES, default="light")
    p.add_argument("--lefty", action="store_true", help="mirror for left-handed players")
    p.add_argument("--zoom", type=float, default=2.0, help="image scale factor (default 2)")
    p.add_argument("--title", default=None, help="title text ('' for none; default auto)")
    args = p.parse_args(argv)

    if not 1 <= args.frets <= 36:
        p.error("--frets must be between 1 and 36")
    if args.accidental == "auto" and args.labels != "jianpu":
        args.accidental = "flat" if args.key in ("F", "Bb", "Eb", "Ab", "Db", "Gb") else "sharp"
    if args.title is None:
        args.title = default_title(args)
    try:
        out = draw(args)
    except ValueError as e:
        p.error(str(e))
    print(f"saved {out}")


if __name__ == "__main__":
    sys.exit(main())
