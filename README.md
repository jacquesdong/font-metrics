# font-metrics

查看等宽字体的排版度量，判断一款字体在编辑器里**中英文能否严格对齐**。

## 为什么需要它

在终端里对齐的中文表格，到了 IDE 编辑器里竖线却逐行漂移——这通常不是空格没补
够，而是字体问题：编辑器按字体的**真实字宽**排版，而常用编程字体（Monaco、
Menlo）不含中文字形，要回退到系统中文字体，回退后的汉字宽度并不等于两个英文
宽。终端则是固定字符网格，把宽字符强制塞进两个格子。

要在编辑器里也对齐，就得选用**自带中文、且汉字步进宽度恰好是英文两倍**的字体。
本工具直接读取字体文件，把这个比例和其他关键度量算出来。

## 依赖

- Python 3.8+
- [fontTools](https://github.com/fonttools/fonttools)（唯一第三方依赖）

项目用 [uv](https://docs.astral.sh/uv/) 管理：依赖以 [PEP 723](https://peps.python.org/pep-0723/)
内联元数据声明在脚本头部，锁定版本见 `font-metrics.py.lock`，**无需手动安装**，
`uv run` 会自动准备好环境：

```bash
# 安装 uv（macOS）
brew install uv

# 之后直接运行，首次会自动下载 fontTools
uv run ./font-metrics.py --size 12 MapleMono-CN-Regular.ttf
```

维护依赖：

```bash
# 修改依赖：先直接编辑脚本头部的 PEP 723 块，再重新锁定
uv lock --script font-metrics.py

# 升级 fontTools 到允许范围内的最新版
uv lock --script font-metrics.py --upgrade-package fonttools
```

不用 uv 也可以，照旧全局安装依赖后直接执行脚本：

```bash
pip install fonttools
# 或 macOS：
brew install fonttools
```

## 使用

```bash
# 1. 查看单个字体（--size 给出像素换算）
uv run ./font-metrics.py --size 12 MapleMono-CN-Regular.ttf

# 2. 对比两款字体，并给出等效字号换算
uv run ./font-metrics.py --size 12 'Maple Mono CN' 'Sarasa-SuperTTC.ttc:205'

# 3. 浏览 .ttc 合集里的子字体（480 个），--grep 支持正则
uv run ./font-metrics.py --list Sarasa-SuperTTC.ttc --grep 'Mono SC$'
```

已全局安装 fontTools 时，也可以省略 `uv run` 直接 `./font-metrics.py ...`。

字体参数支持三种写法：

- **绝对路径**：`~/Library/Fonts/MapleMono-CN-Regular.ttf`
- **文件名**：自动在 `~/Library/Fonts`、`/Library/Fonts`、`/System/Library/Fonts`、
  `/usr/local/share/fonts`、`/usr/share/fonts` 中查找
- **family 名**：如 `'Maple Mono CN'`、`'Sarasa Mono SC'`，自动扫描上述目录解析

`.ttc` 合集用 `文件:序号` 指定子字体（如 `Sarasa-SuperTTC.ttc:205`）；也可以用
`--index 序号`（注意放在位置参数**之前**）。

## 输出说明

```text
Maple Mono CN
  file: ~/Library/Fonts/MapleMono-CN-Regular.ttf  (UPM=1000)
  ASCII 'm' : 0.60em  7.2px
  CJK  '中' : 1.20em  14.4px
  '→'       : 0.60em  7.2px
  中/m ratio: 2.00  (CJK == 2 ASCII cells)
  xHeight    : 0.55em
  capHeight  : 0.73em
```

| 字段 | 含义 |
|---|---|
| `ASCII 'm'` | 一个英文字符的步进宽度（em） |
| `CJK '中'` | 一个汉字的步进宽度（em） |
| `中/m ratio` | 汉字与英文字宽之比；**2.00 才满足等宽对齐** |
| `→` | 箭头宽度，不同字体可能占 1 格或 2 格，表格含箭头时需注意 |
| `xHeight` | 小写字母高度，决定正文字号的主观大小 |
| `capHeight` | 大写字母高度 |

对比两款字体时还会输出等效字号，例如 Sarasa 在字号 14.4 时的英文格宽才与
Maple 12 相当。

## 实测数据（2026-10，macOS）

| 字体 | 英文宽 | 汉字宽 | 比例 | xHeight | `→` |
|---|---|---|---|---|---|
| Maple Mono CN | 0.60em | 1.20em | 2.00 | 0.55em | 0.60em（1 格） |
| Sarasa Mono SC | 0.50em | 1.00em | 2.00 | 0.52em | 1.00em（2 格） |
| Monaco + PingFang 回退 | 0.60em | ≈1.00em | ≈1.67 | — | — |

两款合格字体的安装：

```bash
brew install --cask font-maple-mono-cn      # family: Maple Mono CN
brew install --cask font-sarasa-gothic      # family: Sarasa Mono SC
```

编辑器配置（Trae / VS Code `settings.json`）：

```jsonc
"editor.fontFamily": "'Maple Mono CN', Menlo, Monaco, monospace",
"editor.fontSize": 12,
```

## 项目结构

单文件工具，无打包，依赖通过 PEP 723 内联声明 + uv 锁定：

```text
font-metrics/
├── font-metrics.py       # 脚本本体（头部含 PEP 723 依赖声明）
├── font-metrics.py.lock  # uv 锁定的依赖版本
├── .gitignore
├── README.md             # 本文件
└── NOTES.md              # 字体文件格式与解析笔记
```

## 延伸阅读

- [NOTES.md](./NOTES.md)：SFNT/TTF/TTC 结构、cmap/hmtx 解析流程、踩坑记录
- [OpenType 规范](https://learn.microsoft.com/en-us/typography/opentype/spec/)
- [fontTools 文档](https://fonttools.readthedocs.io/)
