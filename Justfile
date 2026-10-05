# 本仓库的任务入口。产品形态是 PEP 723 单文件脚本（无 pyproject.toml、
# 无 .venv），所以开发工具不装进项目环境，而用 uv tool run 临时拉取并钉住版本。
#   just            列出配方
#   just check      提交前的门禁（lint + format 检查）
#   just lint       ruff 语法级/拼写级检查（规则见 ruff.toml）
#   just format     ruff 自动格式化（行宽 136，配置见 ruff.toml）
#   just lock       修改依赖后重新锁定（先编辑脚本头部 PEP 723 块）
#   just upgrade    把 fontTools 升级到允许范围内的最新版
#   just run ...    运行脚本（多词 family 名需双层引号，见下）

# 列出配方（just 不带参数时跑的就是它）
default:
	@just --list

# 规则集显式写在 ruff.toml，不跟 ruff 默认规则漂移；版本钉在命令里
lint *args:
	uv tool run ruff@0.16.10 check {{args}} font-metrics.py

# 自动格式化（宽度等配置见 ruff.toml [format]）
format *args:
	uv tool run ruff@0.16.10 format {{args}} font-metrics.py

# 修改依赖：先编辑 font-metrics.py 头部的 dependencies，再跑这个
lock:
	uv lock --script font-metrics.py

# 升级 fontTools 到允许范围内的最新版
upgrade:
	uv lock --script font-metrics.py --upgrade-package fonttools

# 提交前的门禁：lint + 格式检查（format --check 不改文件，只验证是否已格式化）
check: lint (format "--check")

# 运行 font-metrics.py。多词 family 名需双层引号：just run info "'Maple Mono CN'"
# （just 的 {{args}} 不会保留引号，直接 just run info 'Maple Mono CN' 会被拆成三个参数）
run *args:
	uv run ./font-metrics.py {{args}}
