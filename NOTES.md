# NOTES — 字体文件是怎么解析的

记录排查「IDE 中英文表格对不齐」过程中学到的字体格式知识。脚本本体见
[font-metrics.py](./font-metrics.py)，用法见 [README](./README.md)。

---

## 1. 结论速查

- 编辑器按字体**真实步进宽度**（advance width）排版；终端（xterm.js）用固定
  字符网格，把宽字符强制占 2 格——两者规则不同，所以终端对齐 ≠ 编辑器对齐。
- Monaco/Menlo **不含中文字形**，中文回退到 PingFang，回退后汉字 ≈ 1em，而
  两个英文格是 2×0.6em = 1.2em，比例只有约 1.67，必然错位。
- 合格的中文等宽字体满足 **CJK advance == 2 × ASCII advance**：Maple Mono CN
  （0.60/1.20em）、Sarasa Mono SC（0.50/1.00em）实测均为 2.00。
- 同字号下两款合格字体大小可以差很多：英文格宽 0.60 vs 0.50，差 17%。
- `→`（U+2192）在 Maple 里占 1 个英文格，在 Sarasa 里占 2 格——**比例合格不
  代表每个符号宽度一致**，表格含此类符号时要单独查。

---

## 2. SFNT 容器：TTF / OTF 的骨架

TTF 和 OTF 都是 **SFNT 容器**：开头一个 offset table，后面跟着若干张「表」
（table），每张表有自己的 tag（4 字节）、偏移和长度。

```text
偏移  长度  内容
0     4     sfVersion：0x00010000 (TrueType) 或 'OTTO' (CFF/OTF)
4     2     numTables
6     2     searchRange
8     2     entrySelector
10    2     rangeShift
12    16*N  table directory，每项：tag(4) + checksum(4) + offset(4) + length(4)
```

解析度量只需要这几张表：

| 表 | 作用 | 本工具用到的字段 |
|---|---|---|
| `head` | 字体全局信息 | `unitsPerEm`（典型 1000 或 2048）、`indexToLocFormat` |
| `hhea` | 水平排版头 | `numberOfHMetrics`（hmtx 里完整记录条数） |
| `OS/2` | 跨平台排版度量 | `sxHeight`、`sCapHeight`、`sTypoAscender/Descender` |
| `cmap` | 码点 → 字形 ID | 查 U+006D、U+4E2D、U+2192 |
| `hmtx` | 字形 → 步进宽度 | 每条记录 `(advanceWidth, lsb)` |
| `name` | 名称字符串 | nameID 1 = family，4 = full name，16 = 排版族名 |
| `maxp` | 字体容量 | `numGlyphs`（手工解析时用） |

### 单位换算

所有度量以 **font unit**（设计单位）存储，换算两步：

```text
em 值   = font_units / unitsPerEm
像素值  = em 值 × font_size_px
```

例：Maple `unitsPerEm = 1000`，`m` 的 advance = 600 → 0.60em；字号 12px 时
= 7.2px。

---

## 3. 查一个字符的宽度：cmap → hmtx

### 3.1 cmap：码点到字形 ID

`cmap` 表内是若干个 encoding subtable（按 platformID / encodingID 区分）。
Windows Unicode（platform 3, encoding 1）最通用，优先选它。常见两种子表格式：

- **format 4**：只覆盖 BMP（U+0000–U+FFFF），分段编码。每段有 startCode、
  endCode、idDelta、idOffset；映射结果是
  `gid = glyphOffset + idDelta (mod 65536)`，`idOffset == 0` 时
  `gid = codepoint + idDelta`。delta 是有符号 16 位整数，偏移要按当前实际
  地址算（spec 里的 trick，手写解析极易错）。
- **format 12**：覆盖全部 Unicode（含 emoji 等增补平面），直接是
  `(startCharCode, endCharCode, startGlyphCode)` 三元组，线性/分段查找。

BMP 内的中英文用 format 4 足够；想要通用（emoji、生僻字）要支持 format 12。

### 3.2 hmtx：字形 ID 到步进宽度

`hmtx` 前 `numberOfHMetrics` 条是完整记录 `advanceWidth(U16) + lsb(I16)`；
之后的字形共用最后一条 advance，只存 `lsb(I16)`：

```python
if gid < number_of_h_metrics:
    advance = u16(hmtx + gid*4)
else:
    advance = advance_of_last_full_record
    lsb     = i16(...)
```

等宽字体里 ASCII 字形的 advance 全部相同；CJK 等宽字体把汉字 advance 设计成
ASCII 的两倍——这就是「2:1 对齐」的本质。

### 3.3 OS/2 里的小写字高

`sxHeight` / `sCapHeight` 是 OS/2 **version 2 起**才有，手工读要确认版本号；
在记录内的偏移分别是 86 和 88（各 2 字节有符号整数）。

---

## 4. name 表：字体到底叫什么

`name` 表是一组 `(platformID, encodingID, languageID, nameID, length, offset)`
记录，字符串存在 storage area。规则：

- platform 3（Windows）：字符串 **UTF-16-BE**；platform 1：Mac Roman。
- 常用 nameID：**1** Font Family、2 Subfamily、4 Full Name、6 PostScript 名、
  **16** Typographic Family（可变字重合集里 family 名可能带字重后缀，真正的族
  名在 16；Maple Mono CN 的 nameID 16 为空，直接用 1）。
- IDE `editor.fontFamily` 要填的就是 nameID 1（或 16）的字符串，**不是文件名**。

---

## 5. TTC 合集与 SuperTTC

`.ttc` 是多个 SFNT 字体的合集，头部 `ttcf` + 字体数量 + 每个子字体的偏移表：

```text
'ttcf' + version(4) + numFonts(4) + offset[numFonts] + (可选) DSIG...
```

更纱黑体的 `Sarasa-SuperTTC.ttc` 把全部字重×宽度×语言塞在一起，共 **480** 个
子字体，且共享大量表数据（文件内偏移对子字体有效）。

注意：同一个 family 名在 SuperTTC 里出现多次（如 `Sarasa Mono SC` 出现在
205/253/397/445），对应不同字宽变体或 hint 版本，用 `list` 子命令看序号时要注意
区分；Regular 简体常规版取 205 可得到预期度量。

---

## 6. 编辑器为什么会错位：字体回退机制

字体解析栈（以 macOS + Trae/VS Code 为例）：

```text
editor.fontFamily = "Monaco, Menlo, ..."
        │
        ├─ 'm'   → Monaco 有此字形 → advance 0.60em
        └─ '中'   → Monaco 无此字形（cmap 里没有 U+4E2D）
                     → 按回退链找下一个字体
                     → PingFang SC → advance ≈ 1.00em
```

关键点：**回退字体的字宽不参与「2 格」约定**。Monaco 两个英文格 = 1.20em，
PingFang 汉字 = 1.00em，即一个汉字在编辑器里约 1.67 个英文宽。按「中文=2」
补空格时，每出现一个汉字就欠 0.33 格误差，行数越多竖线漂移越大。`→`、`·` 等
符号同样可能命中回退字体。

**终端为什么没问题**：xterm.js 先按 Unicode 宽字符属性（见下节）决定字符占
1 格还是 2 格，再把字形绘制进固定宽度的格子里（字体渲染宽度可以溢出/被压缩，
网格不变）。所以终端只需要字体「能显示」，不要求真实字宽严格 2:1。

根治办法是让**同一款字体同时覆盖中英文**且设计为 2:1（Maple Mono CN、Sarasa
Mono SC、Noto Sans Mono CJK SC、Cica 等），此时不触发回退。

---

## 7. Unicode East Asian Width：够用但不等价于渲染宽度

Python `unicodedata.east_asian_width(c)` 把字符分为：

| 类别 | 含义 | 典型字符 |
|---|---|---|
| W / F | 宽 / 全宽，终端占 2 格 | 汉字、全角标点 `（）：` |
| Na / H | 窄 / 半宽，占 1 格 | ASCII、半角假名 |
| A | 歧义，宽度由上下文定 | `→`、`·`、很多技术符号 |
| N | 中性 | 普通拉丁扩展 |

这正是终端判断宽窄的依据，但它有两个局限：

1. 它描述的是**约定**，不是字体文件里的真实 advance——渲染宽度必须读 hmtx。
2. A（歧义）字符在不同字体里设计不同：`→` 在 Maple 中 advance = 0.60em
   （1 格），在 Sarasa 中 = 1.00em（2 格），East Asian Width 无法告诉你答案。

---

## 8. 踩坑记录

1. **`TTCollection` 全量加载 SuperTTC 被 OOM kill（exit 137）**。480 个字体
   全展开内存爆炸。正确姿势是 `TTFont(path, fontNumber=i, lazy=True)` 只加载
   一个子字体；合集数量用
   `TTFont(path, fontNumber=0, lazy=True).reader.numFonts` 获取。
2. **`hhea.advanceWidthMax` 不能当作某字符宽度**。它是全字体最大步进，在
   SuperTTC 里还可能读到与目标子字体无关的缩放数据（一度读出 29.7em 的离谱
   值）。要查具体字符，永远走 `cmap → hmtx`。
3. **手写二进制 parser 的 cmap format 4 坑**：idOffset 非零时，字形位置要用
   “读这个 U16 时的绝对文件偏移”计算，且最后还要加 idDelta 取模。CJK 结果
   一度算成 0.20em，就是 delta 处理错了。结论：学习格式值得手写一次，生产
   代码直接用 fontTools。
4. **OS/2 字段偏移记错**：xHeight 在 86 而非 88，capHeight 才是 88；第一次
   读出来全 0 就是偏移错位。
5. **argparse：`nargs='*'` 的位置参数中间不能插选项**。
   `prog a --index 1 b` 会报 `unrecognized arguments: b`。两种解法：选项放
   前面，或给位置参数设计 `file:index` 后缀语法（本工具采用后者）。
6. **字体 cask 名要核实**：霞鹜文楷等宽在 Homebrew 只有 TC 版
   （`font-lxgw-wenkai-mono-tc`），简体环境会出繁体字形；Maple 的中文版叫
   `font-maple-mono-cn`。给安装命令前先 `brew search` 验证。
7. **OS/2 v0/v1 上 `sxHeight`/`sCapHeight` 属性根本不存在**。字段是 v2 才加的，
   fontTools 对旧表不会创建对应属性，直接 `os2.sxHeight` 抛 `AttributeError`
   （macOS 自带 Arial Unicode MS 即 OS/2 v1）；极少数字体还可能完全没有 OS/2
   表，`f["OS/2"]` 会 KeyError。正确姿势是 `f.get("OS/2")` +
   `getattr(os2, "sxHeight", None)`，并读 `os2.version` 区分「无表」与「旧表」。

---

## 9. fontTools 常用片段

```python
from fontTools.ttLib import TTFont

# 单字体
f = TTFont("MapleMono-CN-Regular.ttf", lazy=True)
upm = f["head"].unitsPerEm                # 1000
cmap = f.getBestCmap()                     # {codepoint: glyphName}
advance = f["hmtx"][cmap[0x4E2D]][0]       # 1200 -> 1.20em
xheight = f["OS/2"].sxHeight              # 550（仅 OS/2 v2+；旧表要用
                                          #  getattr(f.get("OS/2"), "sxHeight", None)）
family = f["name"].getDebugName(1)         # 'Maple Mono CN'

# TTC 合集：只打开第 i 个子字体
f = TTFont("Sarasa-SuperTTC.ttc", fontNumber=i, lazy=True)

# 合集里有多少子字体
n = TTFont(path, fontNumber=0, lazy=True).reader.numFonts
```

---

## 10. 相关字体清单（macOS, Homebrew）

| Cask | family 名 | 特点 |
|---|---|---|
| `font-maple-mono-cn` | Maple Mono CN | JetBrains Mono 风格，0.6em 宽格，字形大 |
| `font-sarasa-gothic` | Sarasa Mono SC | Iosevka 西文 + 思源黑体，0.5em 紧凑 |
| `font-noto-sans-mono-cjk-sc` | Noto Sans Mono CJK SC | Google 官方，观感中立 |
| `font-cica-without-emoji` | Cica | 日文向、自带图标字形 |

```bash
brew install --cask font-maple-mono-cn font-sarasa-gothic
```
