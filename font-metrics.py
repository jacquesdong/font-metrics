#!/usr/bin/env python3
# encoding=utf-8
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "fonttools",
# ]
# ///
"""Inspect monospace font metrics.

Shows the metrics that decide whether CJK text lines up in an editor:
ASCII advance, CJK advance, their ratio (2.00 means CJK == two ASCII cells),
x-height, cap-height and the advance of the arrow glyph.

Examples:
  font-metrics.py MapleMono-CN-Regular.ttf
  font-metrics.py --list Sarasa-SuperTTC.ttc
  font-metrics.py Sarasa-SuperTTC.ttc:205 MapleMono-CN-Regular.ttf
  font-metrics.py --size 12 "Maple Mono CN" "Sarasa-SuperTTC.ttc:205"

Fonts may be given as a file path, a family name, or a bare file name from
the usual macOS font directories. Run with uv (fontTools is fetched from the
PEP 723 metadata above):  uv run ./font-metrics.py FONT
"""

import argparse
import logging
import os
import sys

FONT_DIRS = [
    os.path.expanduser("~/Library/Fonts"),
    "/Library/Fonts",
    "/System/Library/Fonts",
    "/usr/local/share/fonts",
    "/usr/share/fonts",
]

logger = logging.getLogger("font-metrics")

# codepoint, label
PROBES = [
    (0x6D, "ASCII 'm'"),
    (0x4E2D, "CJK  '中'"),
    (0x2192, "'→'"),
]


def split_index(spec):
    """Split a 'font:index' suffix (index is a non-negative integer)."""
    head, sep, tail = spec.rpartition(":")
    if head and sep and tail.isdigit():
        return head, int(tail)
    return spec, None


def resolve_font(spec):
    """Turn a path / file name / family name into (path, index_hint)."""
    spec, _ = split_index(spec)
    if os.path.isfile(spec):
        return spec
    if os.path.splitext(spec)[1]:
        for d in FONT_DIRS:
            p = os.path.join(d, spec)
            if os.path.isfile(p):
                return p
    seen = set()
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            path = os.path.join(d, name)
            if not os.path.isfile(path) or path in seen:
                continue
            seen.add(path)
            try:
                from fontTools.ttLib import TTFont
            except ImportError:
                die("fontTools is required: run with 'uv run ./font-metrics.py' or 'pip install fonttools'")
            if name.endswith(".ttc"):
                try:
                    n = TTFont(path, fontNumber=0, lazy=True).reader.numFonts
                except Exception:
                    logger.debug("skip %s: cannot read font count", path, exc_info=True)
                    continue
                for i in range(n):
                    try:
                        f = TTFont(path, fontNumber=i, lazy=True)
                        fam = f["name"].getDebugName(1)
                    except Exception:
                        logger.debug("skip %s #%d: cannot read name", path, i, exc_info=True)
                        fam = None
                    if fam == spec:
                        return path, i
            else:
                try:
                    fam = TTFont(path, lazy=True)["name"].getDebugName(1)
                except Exception:
                    logger.debug("skip %s: cannot read name", path, exc_info=True)
                    fam = None
                if fam == spec:
                    return path
    die("cannot find font: %s" % spec)


def die(msg):
    print("font-metrics: %s" % msg, file=sys.stderr)
    sys.exit(1)


def list_subfonts(path, pattern=None):
    import re
    from fontTools.ttLib import TTFont
    rx = None
    if pattern:
        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            pass
    f0 = TTFont(path, fontNumber=0, lazy=True)
    n = f0.reader.numFonts
    for i in range(n):
        f = TTFont(path, fontNumber=i, lazy=True)
        name = f["name"].getDebugName(1) or "?"
        if rx is None:
            ok = pattern is None or pattern.lower() in name.lower()
        else:
            ok = bool(rx.search(name))
        if ok:
            print("%4d  %s" % (i, name))


def measure(path, index):
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=index, lazy=True)
    upm = f["head"].unitsPerEm
    cmap = f.getBestCmap()
    hmtx = f["hmtx"]
    os2 = f["OS/2"]

    def adv(cp):
        return hmtx[cmap[cp]][0] if cp in cmap else None

    name = f["name"].getDebugName(1)
    info = {
        "name": name,
        "path": path,
        "index": index,
        "upm": upm,
        "xheight": os2.sxHeight,
        "capheight": os2.sCapHeight,
    }
    for cp, label in PROBES:
        a = adv(cp)
        info[label] = a
    f.close()
    return info


def print_info(info, size):
    print("%s" % info["name"])
    src = info["path"]
    if info["index"]:
        src += " [#%d]" % info["index"]
    print("  file: %s  (UPM=%d)" % (src, info["upm"]))
    for cp, label in PROBES:
        a = info[label]
        if a is None:
            print("  %-10s: (missing)" % label)
        else:
            extra = "  %.1fpx" % (a / info["upm"] * size) if size else ""
            print("  %-10s: %.2fem%s" % (label, a / info["upm"], extra))
    am, az = info["ASCII 'm'"], info["CJK  '中'"]
    if am and az:
        print("  中/m ratio: %.2f  %s" %
              (az / am, "(CJK == 2 ASCII cells)" if round(az / am, 2) == 2.00 else ""))
    print("  xHeight    : %.2fem" % (info["xheight"] / info["upm"]))
    print("  capHeight  : %.2fem" % (info["capheight"] / info["upm"]))


def compare(a, b, size):
    am = a["ASCII 'm'"] / a["upm"]
    bm = b["ASCII 'm'"] / b["upm"]
    ax = a["xheight"] / a["upm"]
    bx = b["xheight"] / b["upm"]
    print("Comparison at fontSize %gpx:" % size)
    print("  ASCII cell: %s %.1fpx | %s %.1fpx (ratio %.2f)" %
          (a["name"], am * size, b["name"], bm * size, bm / am))
    print("  x-height  : %s %.1fpx | %s %.1fpx (ratio %.2f)" %
          (a["name"], ax * size, b["name"], bx * size, bx / ax))
    print("  for %s to match %s @%g: size %.1f (cell) / %.1f (x-height)" %
          (b["name"], a["name"], size, size * am / bm, size * ax / bx))


def main():
    ap = argparse.ArgumentParser(description="Inspect monospace font metrics.")
    ap.add_argument("fonts", nargs="*", help="font path, file name or family name")
    ap.add_argument("--list", metavar="TTC", help="list subfonts of a .ttc collection")
    ap.add_argument("--grep", help="filter --list output by regex")
    ap.add_argument("--index", type=int, default=0, help="subfont index for .ttc (default 0)")
    ap.add_argument("--size", type=float, default=0, help="font size in px for pixel columns")
    ap.add_argument("--debug", action="store_true",
                    help="print tracebacks for font files skipped while scanning")
    args = ap.parse_args()

    try:
        import fontTools  # noqa: F401
    except ImportError:
        die("fontTools is required: run with 'uv run ./font-metrics.py' or 'pip install fonttools'")

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(message)s")
    # 我们只关心自家 font-metrics logger 的调试输出，fontTools 会把每个字体的
    # 表解析细节打成 DEBUG/INFO，压回 WARNING 以免 --debug 被内部噪音淹没。
    logging.getLogger("fontTools").setLevel(logging.WARNING)

    if args.list:
        path = resolve_font(args.list)
        if not path.endswith(".ttc"):
            die("--list expects a .ttc collection")
        list_subfonts(path, args.grep)
        return

    if not args.fonts:
        ap.print_help()
        sys.exit(1)

    if len(args.fonts) > 2:
        die("at most two fonts can be compared at once")

    infos = []
    for spec in args.fonts:
        _, explicit = split_index(spec)
        r = resolve_font(spec)
        path, found_idx = r if isinstance(r, tuple) else (r, None)
        idx = explicit if explicit is not None else (found_idx or args.index)
        infos.append(measure(path, idx))

    for i, info in enumerate(infos):
        if i:
            print()
        print_info(info, args.size)

    if len(infos) == 2 and args.size:
        print()
        compare(infos[0], infos[1], args.size)


if __name__ == "__main__":
    main()
