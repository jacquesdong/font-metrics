#!/bin/sh

# debugpy 专用解释器包装：按 font-metrics.py 的 PEP 723 锁文件提供依赖，
# 并注入 debugpy，供 .vscode/launch.json 的 "python" 字段使用。
# 等价于 `uv run --script font-metrics.py`，但允许 debugpy 覆盖启动命令。
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REQS=$(mktemp "${TMPDIR:-/tmp}/font-metrics-reqs.XXXXXX")
trap 'rm -f "$REQS"' EXIT

# 原理
# 1. `uv export --script` 从`font-metrics.py.lock` 导出 带锁版本 的依赖清单（临时文件，用完即删）；
uv export --script "$DIR/font-metrics.py" --format requirements-txt --quiet -o "$REQS"
# 2. `uv run --no-project --with-requirements <锁清单> --with debugpy python "$@"` 启动解释器——版本与平时`uv run` 完全一致，额外注入调试器；
exec uv run --no-project --with-requirements "$REQS" --with debugpy python "$@"
# 3. `launch.json` 的 `"python"` 指向该包装脚本，debugpy 把它当解释器启动，断点、`stopOnEntry` 、`pickArgs` 行为和原来一致。
