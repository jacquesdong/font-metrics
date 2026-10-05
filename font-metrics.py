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
  font-metrics.py info MapleMono-CN-Regular.ttf
  font-metrics.py info Sarasa-SuperTTC.ttc:205 --size 12
  font-metrics.py compare "Maple Mono CN" "Sarasa-SuperTTC.ttc:205" --size 12
  font-metrics.py list Sarasa-SuperTTC.ttc

Fonts may be given as a file path, a family name, or a bare file name from
the usual macOS font directories. Run with uv (fontTools is fetched from the
PEP 723 metadata above):  uv run ./font-metrics.py info FONT
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger("font-metrics")

FONT_DIRS = [
    os.path.expanduser("~/Library/Fonts"),
    "/Library/Fonts",
    "/System/Library/Fonts",
    "/usr/local/share/fonts",
    "/usr/share/fonts",
]

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


def load_font(spec, default_index):
    """Resolve a font spec (with optional ':index' suffix) and measure it."""
    _, explicit = split_index(spec)
    r = resolve_font(spec)
    path, found_idx = r if isinstance(r, tuple) else (r, None)
    index = explicit if explicit is not None else (found_idx or default_index)
    return measure(path, index)


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


CMD_LIST    = "list"
CMD_INFO    = "info"
CMD_COMPARE = "compare"


def build_parser():
    parser = argparse.ArgumentParser(description="Inspect monospace font metrics.")
    parser.add_argument("--debug", action="store_true",
                        help="print tracebacks for font files skipped while scanning")
    command_parser = parser.add_subparsers(dest="command", required=True)

    parser_list = command_parser.add_parser(CMD_LIST, help="list subfonts of a .ttc collection")
    parser_list.add_argument("ttc", metavar="TTC",
        help="path or file name of a .ttc collection")
    parser_list.add_argument("--grep", help="filter output by regex")

    parser_info = command_parser.add_parser(CMD_INFO, help="show metrics of one font")
    parser_info.add_argument("font", help="font path, file name or family name")
    parser_info.add_argument("--index", type=int, default=0,
        help="subfont index for .ttc (default 0)")
    parser_info.add_argument("--size", type=float, default=0,
        help="font size in px for pixel columns")

    parser_compare = command_parser.add_parser(CMD_COMPARE, help="compare two fonts at a font size")
    parser_compare.add_argument("fonts", nargs=2, metavar="FONT",
        help="two fonts to compare (path, file name or family name)")
    parser_compare.add_argument("--size", type=float, required=True,
        help="font size in px (required)")

    return parser


def setup_logging(args):
    # 只控制自家 font-metrics logger，root 保持 WARNING。handler 放行 DEBUG，
    # 由各 logger 的级别决定是否输出：--debug 时仅我们的 logger 降到 DEBUG，
    # 第三方库（如 fontTools）维持 WARNING，不会被顺带打开。
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)
    logger.setLevel(logging.DEBUG if args.debug else logging.WARNING)


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        import fontTools  # noqa: F401
    except ImportError:
        die("fontTools is required: run with 'uv run ./font-metrics.py' or 'pip install fonttools'")

    setup_logging(args)

    if args.command == CMD_LIST:
        path = resolve_font(args.ttc)
        if not path.endswith(".ttc"):
            die("list expects a .ttc collection")
        list_subfonts(path, args.grep)
    elif args.command == CMD_INFO:
        print_info(load_font(args.font, args.index), args.size)
    elif args.command == CMD_COMPARE:
        infos = [load_font(spec, 0) for spec in args.fonts]
        print_info(infos[0], args.size)
        print()
        print_info(infos[1], args.size)
        print()
        compare(infos[0], infos[1], args.size)
    else:
        # 你是不是新增子命令，但漏了处理
        raise RuntimeError("unhandled command: %r" % args.command)


if __name__ == "__main__":
    main()
