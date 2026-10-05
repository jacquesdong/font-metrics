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
import contextlib
import logging
import os
import sys

logger = logging.getLogger("font-metrics")


class FontError(Exception):
    """用户可纠正的字体错误（参数格式、子字体序号、文件无法打开）。

    与程序内部 bug 区分：main 捕获后只报一行，默认不打 traceback。
    """


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
    """Split a 'font:index' suffix (index is a non-negative integer).

    >>> split_index("Sarasa.ttc:205")
    ('Sarasa.ttc', 205)
    >>> split_index("font.ttf")
    ('font.ttf', None)
    >>> split_index("a:b:205")  # 多个冒号时取最右一个
    ('a:b', 205)
    >>> split_index(":205")     # 冒号前为空：不是序号后缀
    (':205', None)
    >>> split_index("x.ttc:")   # 序号为空
    ('x.ttc:', None)
    >>> try:  # 负数：显式报错而非静默当成文件名
    ...     split_index("x.ttc:-1")
    ... except FontError as e:
    ...     print(str(e))
    font subfont index must be a non-negative integer: '-1'
    """
    head, sep, tail = spec.rpartition(":")
    if head and sep and tail.isdigit():
        return head, int(tail)
    if head and sep and tail.startswith("-") and tail[1:].isdigit():
        raise FontError("font subfont index must be a non-negative integer: %r" % tail)
    return spec, None


def choose_face(matches):
    """从同一家族的多个面孔 (path, index, subfamily) 中选出 bare family 名
    所指的面孔：唯一命中直接返回；否则按惯例取唯一的 Regular/Normal；
    没有或不止一个 Regular 时抛 FontError 让用户显式指定。

    >>> choose_face([("a.ttc", 0, "Regular")])
    ('a.ttc', 0, 'Regular')
    >>> choose_face([("a.ttc", 0, "Bold"), ("a.ttc", 7, "Regular")])
    ('a.ttc', 7, 'Regular')
    >>> try:  # 没有 Regular：不猜，报错
    ...     choose_face([("a.ttc", 0, "Bold"), ("a.ttc", 1, "Italic")])
    ... except FontError as e:
    ...     print(str(e).splitlines()[0])
    ambiguous font family with 2 faces; specify one with ':index':
    >>> try:  # 两个 Regular（如两个目录各装一份）：同样不猜
    ...     choose_face([("a.ttc", 0, "Regular"), ("b.ttc", 0, "Normal")])
    ... except FontError as e:
    ...     print(str(e).splitlines()[0])
    ambiguous font family with 2 faces; specify one with ':index':
    """
    if len(matches) == 1:
        return matches[0]

    def is_regular(m):
        return (m[2] or "").strip().lower() in ("regular", "normal")

    regulars = [m for m in matches if is_regular(m)]
    if len(regulars) == 1:
        return regulars[0]

    lines = ["ambiguous font family with %d faces; specify one with ':index':" % len(matches)]
    for path, index, subfamily in matches:
        loc = path if index is None else "%s:%d" % (path, index)
        lines.append("  %s (%s)" % (loc, subfamily or "?"))
    raise FontError("\n".join(lines))


@contextlib.contextmanager
def open_face(path, index=None):
    """打开一个 lazy TTFont 并保证底层文件句柄关闭（供 with 使用）。

    直接把路径交给 fontTools 时，若构造失败（典型：ttc 序号越界，
    SFNTReader 抛错前已 open 文件），句柄挂在半成品 reader 上、调用方拿不回
    对象，只能等 GC 回收并泄漏 ResourceWarning。这里由我们持有文件流：
    无论构造成功还是抛错，with 退出时都会关闭。
    """
    from fontTools.ttLib import TTFont

    with open(path, "rb") as stream:
        kwargs = {"fontNumber": index} if index is not None else {}
        yield TTFont(stream, lazy=True, **kwargs)


def resolve_font(spec):
    """Turn a path / file name / family name into path, or (path, index).

    family 名命中多个面孔时由 choose_face 选 Regular，选不出就报错。
    若 spec 带显式 ':index' 但该序号子字体的 family 名与所请求的不符
    （典型：合集里相邻位置是另一个 family），抛 FontError 而不是静默
    返回错字体的度量。命中横跨多个文件时（各合集序号各自独立），按序号
    对号入座到真正包含该 family 的文件，而不是死守第一个命中文件。
    """
    spec_name, spec_index = split_index(spec)
    if os.path.isfile(spec_name):
        return spec_name
    if os.path.splitext(spec_name)[1]:
        for d in FONT_DIRS:
            p = os.path.join(d, spec_name)
            if os.path.isfile(p):
                return p

    try:
        from fontTools.ttLib import TTLibError
    except ImportError:
        die("fontTools is required: run with 'uv run ./font-metrics.py' or 'pip install fonttools'")

    # (path, index_or_None, subfamily)：spec_name 是用户请求的 family 名，
    # family 是每个子字体 name 表里实际读到的 family 名
    matches = []
    seen = set()
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            path = os.path.join(d, entry)
            if not os.path.isfile(path) or path in seen:
                continue

            seen.add(path)

            if entry.endswith(".ttc"):
                try:
                    with open_face(path, 0) as probe:
                        n = probe.reader.numFonts
                except Exception:
                    logger.debug("skip %s: cannot read font count", path, exc_info=True)
                    continue
                for i in range(n):
                    try:
                        with open_face(path, i) as face:
                            name_table = face["name"]
                            family, subfamily = name_table.getDebugName(1), name_table.getDebugName(2)
                    except Exception:
                        logger.debug("skip %s #%d: cannot read name", path, i, exc_info=True)
                        family = subfamily = None
                    if family == spec_name:
                        matches.append((path, i, subfamily))
            else:
                try:
                    with open_face(path) as face:
                        name_table = face["name"]
                        family, subfamily = name_table.getDebugName(1), name_table.getDebugName(2)
                except Exception:
                    logger.debug("skip %s: cannot read name", path, exc_info=True)
                    family = subfamily = None
                if family == spec_name:
                    matches.append((path, None, subfamily))

    if not matches:
        die("cannot find font: %s" % spec_name)

    if spec_index is not None:
        # 显式序号：扫描已逐个读过各子字体的 name 表，命中元组 (path, index, ...)
        # 本身就证明该序号在此文件中属于所请求 family，按序号对号入座即可。
        # 各合集序号各自独立、matches 可能横跨多个文件，不能死守 matches[0] 所在
        # 的文件去开 spec_index——那会拿别的文件张冠李戴，甚至把存在的序号误报越界。
        # 单体字体（index is None）只占 #0 一个位置。
        for path, found, _subfamily in matches:
            slot = 0 if found is None else found
            if slot == spec_index:
                return path, spec_index

        # #spec_index 不属于任何命中文件里的该 family：列出 family 实际位置。
        # 只有一个命中文件时补开一次该序号，说明这个位置实际属于谁；越界/损坏
        # （TTLibError）照旧交给 measure 报合法范围。跨文件时不猜用户指的是哪份。
        multi_file = len({p for p, _, _ in matches}) > 1
        first_path = matches[0][0]
        actual_family = None
        if not multi_file:
            try:
                with open_face(first_path, spec_index) as check:
                    actual_family = check["name"].getDebugName(1)
            except TTLibError:
                return first_path, spec_index

        def face_loc(path, index, subfamily):
            sub = subfamily or "?"
            if index is None:
                return "%s (%s, only #0)" % (path, sub)
            if multi_file:
                return "%s:#%d (%s)" % (path, index, sub)
            return "#%d (%s)" % (index, sub)

        locs = ", ".join(face_loc(p, i, s) for p, i, s in matches)
        if actual_family is not None and actual_family != spec_name:
            raise FontError(
                "subfont #%d in %s is %r, not %r; %r found at %s" % (spec_index, first_path, actual_family, spec_name, spec_name, locs)
            )
        raise FontError("subfont #%d is not a face of %r; %r found at %s" % (spec_index, spec_name, spec_name, locs))

    # 未指定序号：bare family 名按惯例指 Regular，多面孔时提示一行（不静默）
    chosen = choose_face(matches)
    if len(matches) > 1:
        loc = chosen[0] if chosen[1] is None else "%s:%d" % (chosen[0], chosen[1])
        print(
            "font-metrics: note: %d faces of %r found; using %s (%s), add ':index' to pick another"
            % (len(matches), spec_name, loc, chosen[2]),
            file=sys.stderr,
        )
    path, found_index, _ = chosen
    return path if found_index is None else (path, found_index)


def load_font(spec):
    """Resolve a font spec (with optional ':index' suffix) and measure it."""
    _, explicit = split_index(spec)
    r = resolve_font(spec)
    path, found_index = r if isinstance(r, tuple) else (r, None)
    index = explicit if explicit is not None else (found_index or 0)
    return measure(path, index)


def xheight_na(info):
    """解释 x-height/cap-height 为何缺失：无 OS/2 表，或表版本低于引入该字段的 v2。"""
    v = info["os2ver"]
    return "(n/a, no OS/2 table)" if v is None else "(n/a, OS/2 v%d < 2)" % v


def measure(path, index):
    from fontTools.ttLib import TTLibError

    opened = False
    try:
        with open_face(path, index) as f:
            opened = True
            # 非合集字体只有一个子字体，fontTools 对其传 fontNumber 会静默忽略；
            # 合集 reader 带 numFonts，单体 SFNTReader 没有，据此拦下越界序号，
            # 避免单体字体被错误标注成 [#N]（:0 对单体合法，不拦）
            if index and getattr(f.reader, "numFonts", None) is None:
                raise FontError("subfont #%d not found in %s (not a font collection, only #0 is valid)" % (index, path))

            upm = f["head"].unitsPerEm
            cmap = f.getBestCmap()
            hmtx = f["hmtx"]
            # sxHeight/sCapHeight 是 OS/2 v2 才有的字段，老字体（v0/v1）甚至可能没有 OS/2 表
            os2 = f.get("OS/2")

            def adv(cp):
                return hmtx[cmap[cp]][0] if cp in cmap else None

            def metric(attr):
                return getattr(os2, attr, None) if os2 is not None else None

            name = f["name"].getDebugName(1)
            info = {
                "name": name,
                "path": path,
                "index": index,
                "upm": upm,
                "os2ver": getattr(os2, "version", None),
                "xheight": metric("sxHeight"),
                "capheight": metric("sCapHeight"),
            }
            for cp, label in PROBES:
                a = adv(cp)
                info[label] = a
            return info
    except TTLibError as e:
        if opened:
            # 已成功打开、读表阶段才失败：不是序号问题，保持原样上抛
            raise
        # 序号越界（ttc 才有多个子字体）：打开 #0 拿总数，给出合法范围
        try:
            with open_face(path, 0) as probe:
                n = probe.reader.numFonts
        except TTLibError:
            raise FontError("cannot open font %s: %s" % (path, e))
        raise FontError("subfont #%d not found in %s (valid 0..%d)" % (index, path, n - 1))


def die(msg):
    print("font-metrics: %s" % msg, file=sys.stderr)
    sys.exit(1)


def list_subfonts(path, pattern=None):
    import re

    rx = None
    if pattern:
        try:
            rx = re.compile(pattern, re.I)
        except re.error:
            pass
    with open_face(path, 0) as f0:
        n = f0.reader.numFonts
    for i in range(n):
        with open_face(path, i) as f:
            name = f["name"].getDebugName(1) or "?"
            if rx is None:
                ok = pattern is None or pattern.lower() in name.lower()
            else:
                ok = bool(rx.search(name))
            if ok:
                print("%4d  %s" % (i, name))


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
        print("  中/m ratio: %.2f  %s" % (az / am, "(CJK == 2 ASCII cells)" if round(az / am, 2) == 2.00 else ""))
    for key, label in (("xheight", "xHeight"), ("capheight", "capHeight")):
        v = info[key]
        text = "%.2fem" % (v / info["upm"]) if v else xheight_na(info)
        print("  %-10s: %s" % (label, text))


def compare(a, b, size):
    am = a["ASCII 'm'"] / a["upm"]
    bm = b["ASCII 'm'"] / b["upm"]
    print("Comparison at fontSize %gpx:" % size)
    print("  ASCII cell: %s %.1fpx | %s %.1fpx (ratio %.2f)" % (a["name"], am * size, b["name"], bm * size, bm / am))
    match = "  for %s to match %s @%g: size %.1f (cell)" % (b["name"], a["name"], size, size * am / bm)
    # x-height 需要双方都有（OS/2 v2+）才能算 ratio 和等效字号，否则各报各的
    if a["xheight"] and b["xheight"]:
        ax = a["xheight"] / a["upm"]
        bx = b["xheight"] / b["upm"]
        print("  x-height  : %s %.1fpx | %s %.1fpx (ratio %.2f)" % (a["name"], ax * size, b["name"], bx * size, bx / ax))
        match += " / %.1f (x-height)" % (size * ax / bx)
    else:
        xa = "%.1fpx" % (a["xheight"] / a["upm"] * size) if a["xheight"] else xheight_na(a)
        xb = "%.1fpx" % (b["xheight"] / b["upm"] * size) if b["xheight"] else xheight_na(b)
        print("  x-height  : %s %s | %s %s" % (a["name"], xa, b["name"], xb))
    print(match)


# fmt: off
CMD_LIST    = "list"
CMD_INFO    = "info"
CMD_COMPARE = "compare"
# fmt: on


def cmd_list(args):
    path = resolve_font(args.ttc)
    if not path.endswith(".ttc"):
        die("list expects a .ttc collection")
    list_subfonts(path, args.grep)


def cmd_info(args):
    print_info(load_font(args.font), args.size)


def cmd_compare(args):
    infos = [load_font(spec) for spec in args.fonts]
    print_info(infos[0], args.size)
    print()
    print_info(infos[1], args.size)
    print()
    compare(infos[0], infos[1], args.size)


# 子命令注册表：新增子命令时除了在 build_parser 加 parser，还要在这里登记处理函数
COMMANDS = {
    CMD_LIST: cmd_list,
    CMD_INFO: cmd_info,
    CMD_COMPARE: cmd_compare,
}


def build_parser():
    parser = argparse.ArgumentParser(description="Inspect monospace font metrics.")
    parser.add_argument("--debug", action="store_true", help="print tracebacks if failed while scanning")
    command_parser = parser.add_subparsers(dest="command", required=True)

    parser_list = command_parser.add_parser(CMD_LIST, help="list subfonts of a .ttc collection")
    parser_list.add_argument("ttc", metavar="TTC", help="path or file name of a .ttc collection")
    parser_list.add_argument("--grep", help="filter output by regex")

    parser_info = command_parser.add_parser(CMD_INFO, help="show metrics of one font")
    parser_info.add_argument("font", metavar="FONT", help="font path, file name or family name")
    parser_info.add_argument("--size", type=float, default=0, help="font size in px for pixel columns")

    parser_compare = command_parser.add_parser(CMD_COMPARE, help="compare two fonts at a font size")
    parser_compare.add_argument("fonts", nargs=2, metavar="FONT", help="font path, file name or family name")
    parser_compare.add_argument("--size", type=float, required=True, help="font size in px (required)")

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

    handler = COMMANDS.get(args.command)
    if handler is None:
        # 走到这里说明新增了子命令却漏了在 COMMANDS 登记
        raise RuntimeError("unhandled command: %r" % args.command)

    try:
        handler(args)
    except FontError as e:
        # 默认只给一行错误；--debug 时打印完整堆栈定位问题
        logger.debug("failed to load font", exc_info=True)
        die(str(e))


if __name__ == "__main__":
    main()
