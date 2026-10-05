#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "fonttools",
# ]
# ///
"""resolve_font 显式序号的集成回归测试。

与脚本内 doctest 的分工：
- doctest 覆盖 split_index / choose_face 等纯函数，系统 python 即可跑，无需 fontTools；
- 本文件要用 FontBuilder 合成带 name 表的 ttf/ttc 并真实开文件，必须在脚本的
  PEP 723 环境里运行：uv run ./tests/test_resolve_font.py
  （依赖版本由 tests/test_resolve_font.py.lock 锁定，随仓库一起提交）。

核心回归：family 名命中横跨多个合集文件、各合集序号各自独立时，显式 ':index'
必须对号入座到真正包含该 family 的文件，不能死守 matches[0] 所在文件。
"""

import contextlib
import gc
import importlib.util
import io
import os
import shutil
import tempfile
import unittest
import warnings

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection

# 注意：产品代码必须显式 close 打开的 lazy TTFont；各用例在 setUp 里把
# ResourceWarning 升级为异常，任何句柄泄漏都会让回归直接失败

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module():
    spec = importlib.util.spec_from_file_location("font_metrics", os.path.join(REPO_ROOT, "font-metrics.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fm = load_module()


def make_font(family, subfamily):
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef"])
    fb.setupCharacterMap({})
    fb.setupGlyf({".notdef": TTGlyphPen(None).glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": subfamily})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    return fb.font


def save_ttc(path, fonts):
    coll = TTCollection()
    coll.fonts = fonts
    coll.save(path)


class ResolveFontIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fm-tests-")
        self._orig_dirs = fm.FONT_DIRS
        # unittest 的 TextTestRunner 进入 catch_warnings 后会重置过滤器，
        # 必须在每个用例内注册：常规析构路径上漏关 lazy TTFont 会立刻报错。
        # 注意 GC 析构时抛的警告只会 unraisable、变不成失败，因此另由
        # track_opened_files 两个哨兵对 closed 做确定性断言兜底
        warnings.filterwarnings("error", category=ResourceWarning)

    def tearDown(self):
        fm.FONT_DIRS = self._orig_dirs
        gc.collect()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def font_dir(self, name):
        # 每个合集独占一个目录：扫描顺序由 FONT_DIRS 决定，不依赖 os.listdir 顺序
        d = os.path.join(self.tmp, name)
        os.mkdir(d)
        return d

    def test_cross_file_index_uses_file_owning_slot(self):
        # Fam 位于 a.ttc:0 与 b.ttc:1；':1' 必须解析到 b.ttc，而不是去 a.ttc 开 #1
        da, db = self.font_dir("a"), self.font_dir("b")
        a = os.path.join(da, "a.ttc")
        b = os.path.join(db, "b.ttc")
        save_ttc(a, [make_font("Fam", "Regular"), make_font("Other", "Regular")])
        save_ttc(b, [make_font("Other2", "Regular"), make_font("Fam", "Bold")])
        fm.FONT_DIRS = [da, db]

        self.assertEqual(fm.resolve_font("Fam:1"), (b, 1))
        self.assertEqual(fm.resolve_font("Fam:0"), (a, 0))

        # 端到端：measure 实际读到的就是 b.ttc:1
        info = fm.load_font("Fam:1")
        self.assertEqual((info["path"], info["index"], info["name"]), (b, 1, "Fam"))

    def test_wrong_index_multi_file_lists_all_locations(self):
        da, db = self.font_dir("a"), self.font_dir("b")
        a = os.path.join(da, "a.ttc")
        b = os.path.join(db, "b.ttc")
        save_ttc(a, [make_font("Fam", "Regular"), make_font("Other", "Regular")])
        save_ttc(b, [make_font("Other2", "Regular"), make_font("Fam", "Bold")])
        fm.FONT_DIRS = [da, db]

        with self.assertRaises(fm.FontError) as ctx:
            fm.resolve_font("Fam:5")
        msg = str(ctx.exception)
        self.assertIn("not a face of 'Fam'", msg)
        self.assertIn(a, msg)
        self.assertIn(b, msg)

    def test_single_collection_wrong_slot_names_neighbor(self):
        d = self.font_dir("c")
        c = os.path.join(d, "c.ttc")
        save_ttc(c, [make_font("Fam", "Regular"), make_font("Neighbor", "Regular")])
        fm.FONT_DIRS = [d]

        with self.assertRaises(fm.FontError) as ctx:
            fm.resolve_font("Fam:1")
        msg = str(ctx.exception)
        self.assertIn("'Neighbor', not 'Fam'", msg)
        self.assertIn("#0 (Regular)", msg)

    def test_single_collection_out_of_range_deferred_to_measure(self):
        # 唯一命中文件时越界序号仍交给 measure 报合法范围（resolve 不重复报错）
        d = self.font_dir("d")
        path = os.path.join(d, "d.ttc")
        save_ttc(path, [make_font("Fam", "Regular"), make_font("Neighbor", "Regular")])
        fm.FONT_DIRS = [d]

        self.assertEqual(fm.resolve_font("Fam:5"), (path, 5))
        with self.assertRaises(fm.FontError) as ctx:
            fm.load_font("Fam:5")
        self.assertIn("valid 0..1", str(ctx.exception))

    def test_duplicate_installs_same_index_first_wins(self):
        # 两个目录各装一份、Fam 都在 #1：沿用首个命中，不报错
        da, db = self.font_dir("d1"), self.font_dir("d2")
        d1 = os.path.join(da, "d.ttc")
        d2 = os.path.join(db, "d.ttc")
        save_ttc(d1, [make_font("OtherX", "Regular"), make_font("Fam", "Bold")])
        save_ttc(d2, [make_font("OtherY", "Regular"), make_font("Fam", "Italic")])
        fm.FONT_DIRS = [da, db]

        self.assertEqual(fm.resolve_font("Fam:1"), (d1, 1))

    def test_standalone_font_only_slot_zero(self):
        d = self.font_dir("s")
        path = os.path.join(d, "c.ttf")
        make_font("Fam", "Regular").save(path)
        fm.FONT_DIRS = [d]

        self.assertEqual(fm.resolve_font("Fam:0"), (path, 0))
        with self.assertRaises(fm.FontError) as ctx:
            fm.resolve_font("Fam:1")
        self.assertIn("only #0", str(ctx.exception))

    def test_bare_family_without_index_still_picks_regular(self):
        da, db = self.font_dir("a"), self.font_dir("b")
        a = os.path.join(da, "a.ttc")
        b = os.path.join(db, "b.ttc")
        save_ttc(a, [make_font("Fam", "Regular"), make_font("Other", "Regular")])
        save_ttc(b, [make_font("Other2", "Regular"), make_font("Fam", "Bold")])
        fm.FONT_DIRS = [da, db]

        self.assertEqual(fm.resolve_font("Fam"), (a, 0))

    def test_list_subfonts_closes_every_open(self):
        # list 要开一次 #0 拿总数、再逐个子字体开一次；漏关任意一个都会触发哨兵
        d = self.font_dir("l")
        path = os.path.join(d, "l.ttc")
        save_ttc(path, [make_font("Fam", "Regular"), make_font("Neighbor", "Regular")])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fm.list_subfonts(path)
        lines = buf.getvalue().splitlines()
        self.assertEqual(lines, ["   0  Fam", "   1  Neighbor"])

    @contextlib.contextmanager
    def track_opened_files(self):
        # 记录上下文内所有 open() 出来的文件流；退出后调用方断言全部已关。
        # 不靠 ResourceWarning——它在 GC 析构里抛时只是 unraisable，无法让用例失败；
        # 直接检查 closed 才是确定性的关闭语义断言
        import builtins

        created = []
        real_open = builtins.open

        def tracking_open(file, *args, **kwargs):
            f = real_open(file, *args, **kwargs)
            created.append(f)
            return f

        builtins.open = tracking_open
        try:
            yield created
        finally:
            builtins.open = real_open

    def test_open_face_closes_stream_on_success(self):
        d = self.font_dir("o1")
        path = os.path.join(d, "o.ttc")
        save_ttc(path, [make_font("Fam", "Regular"), make_font("Other", "Regular")])

        with self.track_opened_files() as opened:
            with fm.open_face(path, 0) as f:
                self.assertEqual(f["name"].getDebugName(1), "Fam")
        self.assertTrue([f for f in opened if "rb" in f.mode])
        self.assertTrue(all(f.closed for f in opened), [f.closed for f in opened])

    def test_open_face_closes_stream_when_constructor_fails(self):
        # ttc 序号越界：fontTools 构造 TTFont 抛错前已自行 open 文件，
        # 半成品 reader 拿不回；open_face 必须靠自持文件流保证不留开口
        from fontTools.ttLib import TTLibError

        d = self.font_dir("o2")
        path = os.path.join(d, "o.ttc")
        save_ttc(path, [make_font("Fam", "Regular"), make_font("Other", "Regular")])

        with self.track_opened_files() as opened:
            with self.assertRaises(TTLibError):
                with fm.open_face(path, 9):
                    pass
        self.assertTrue([f for f in opened if "rb" in f.mode])
        self.assertTrue(all(f.closed for f in opened), [f.closed for f in opened])


if __name__ == "__main__":
    unittest.main()
