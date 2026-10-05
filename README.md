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
uv run ./font-metrics.py info MapleMono-CN-Regular.ttf
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

三个子命令对应三种动作，`-h` 可查看各自参数：

```bash
# info：查看单个字体（--size 给出像素换算，可选）
uv run ./font-metrics.py info MapleMono-CN-Regular.ttf
uv run ./font-metrics.py info Sarasa-SuperTTC.ttc:205 --size 12

# compare：对比两款字体并给出等效字号换算（--size 必填）
uv run ./font-metrics.py compare 'Maple Mono CN' 'Sarasa-SuperTTC.ttc:205' --size 12

# list：浏览 .ttc 合集里的子字体（480 个），--grep 支持正则
uv run ./font-metrics.py list Sarasa-SuperTTC.ttc --grep 'Mono SC$'
```

已全局安装 fontTools 时，也可以省略 `uv run` 直接 `./font-metrics.py ...`。

字体参数支持三种写法：

- **绝对路径**：`~/Library/Fonts/MapleMono-CN-Regular.ttf`
- **文件名**：自动在 `~/Library/Fonts`、`/Library/Fonts`、`/System/Library/Fonts`、
  `/usr/local/share/fonts`、`/usr/share/fonts` 中查找
- **family 名**：如 `'Maple Mono CN'`、`'Sarasa Mono SC'`，自动扫描上述目录解析

`.ttc` 合集里的子字体统一用 `文件:序号` 后缀指定（如 `Sarasa-SuperTTC.ttc:205`），
info 和 compare 通用；序号先用 `list` 子命令查。compare 对比两个不同子字体时
后缀各自跟随自己的文件（如 `X.ttc:205 X.ttc:445`），这也是不设 `--index`
选项的原因——单个选项无法分别作用于两个字体参数。

按 family 名查找时，工具会扫描所有字体目录并静默跳过无法解析的文件；若报
`cannot find font` 但你认为字体已在目录里，加 `--debug` 可看到每个被跳过文件的
路径和异常堆栈（`--debug` 是全局参数，放在子命令**之前**）：

```bash
uv run ./font-metrics.py --debug info 'My Family Name'
```

`--debug` 只输出我们自己的诊断（字体文件路径 + 堆栈），fontTools 内部的表解析
日志会被压制，默认不加时完全静默。

## 调试（Trae / VS Code）

本项目是 PEP 723 单文件脚本，没有 `.venv`，而 `uv run --script` 又不允许
debugpy 替换启动命令，因此调试通过一个解释器包装脚本解决，配置已在
`.vscode/launch.json` 中：

- 按 **F5**（或运行面板选「Python Debugger: uv run font-metrics.py」）即可断点
  调试，参数通过弹窗输入（`pickArgs`）。
- `"python"` 指向 [scripts/debug-python.sh](./scripts/debug-python.sh)：它先
  `uv export --script` 从 `font-metrics.py.lock` 导出**锁版本**依赖清单，再用
  `uv run --with-requirements ... --with debugpy python` 启动，所以调试环境与
  平时 `uv run` 完全一致，仅额外注入 debugpy。
- 首次启动会构建一次缓存环境（几秒），之后秒起。
- 前提：编辑器已安装 Python（debugpy）扩展；`scripts/debug-python.sh` 需保留
  可执行权限（`chmod +x`，仓库内已设置）。

不想用包装脚本时，也可手动启动 debugpy 监听端口，再让编辑器 Attach：

```bash
uv run --no-project --with fonttools --with debugpy python -m debugpy \
  --listen 5678 --wait-for-client font-metrics.py info Menlo.ttc --size 12
```

然后在编辑器里用「Attach（端口 5678）」接入。

## 开发

提交前的检查用 [just](https://github.com/casey/just)（`brew install just`）：

```bash
just            # 列出配方
just lint       # ruff 语法级/拼写级检查
just format     # ruff 自动格式化
just test       # 运行脚本内 doctest（系统 python，无需 fontTools）
just check      # 提交门禁：lint + 格式检查 + doctest
just lock       # 改完脚本头部 PEP 723 依赖后重新锁定
just upgrade    # fontTools 升级到允许范围内的最新版
```

项目刻意不设 pyproject.toml、不建 `.venv`：ruff 通过 `uv tool run` 临时拉取并把版本
钉死在 [Justfile](./Justfile) 命令里（`ruff@0.16.10`），不污染项目目录；
lint 规则显式写在 [ruff.toml](./ruff.toml)（`E4/E7/E9/F` + `BLE001/S112`），不跟随 ruff
默认规则集漂移——脚本里刻意统一的 `%` 格式化（UP031）不属于错误；扫描坏字体时
吞掉的宽泛 except 已用 `--debug` 下的 `logger.debug(exc_info=True)` 记录，故
BLE001/S112 以单码加入规则集。格式化同样走 ruff（`just format`）。

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
├── ruff.toml             # ruff lint 规则
├── Justfile              # just 任务入口（lint / lock / upgrade / check）
├── scripts/
│   └── debug-python.sh   # 调试用解释器包装（供 launch.json 使用）
├── .vscode/launch.json   # F5 调试配置
├── .gitignore
├── README.md             # 本文件
└── NOTES.md              # 字体文件格式与解析笔记
```

## 延伸阅读

- [NOTES.md](./NOTES.md)：SFNT/TTF/TTC 结构、cmap/hmtx 解析流程、踩坑记录
- [OpenType 规范](https://learn.microsoft.com/en-us/typography/opentype/spec/)
- [fontTools 文档](https://fonttools.readthedocs.io/)
