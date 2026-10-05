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

import importlib.util
import os
import shutil
import tempfile
import unittest
import warnings

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection

# 扫描字体时产品代码刻意以 lazy 方式开 TTFont 且不逐个关闭（真实运行的既有行为），
# 合成用例大量创建/回收临时字体时会在 GC 阶段冒出 unclosed file 提示；
# 这些与被测断言无关，在回归进程内静音，避免淹没测试结果
warnings.filterwarnings("ignore", category=ResourceWarning)

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
        # unittest 的 TextTestRunner 进入 catch_warnings 后会把全部 Warning
        # 重置成 default（模块级 filter 失效），要在每个用例内重新压上
        warnings.filterwarnings("ignore", category=ResourceWarning)

    def tearDown(self):
        fm.FONT_DIRS = self._orig_dirs
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


if __name__ == "__main__":
    unittest.main()
