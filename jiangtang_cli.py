#!/usr/bin/env python3
"""书院编审工具入口，等价于 python -m jiangtang.cli。

显式加入脚本所在目录，使 python3 -I 隔离运行时仍能导入本包。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jiangtang.cli import main

if __name__ == "__main__":
    sys.exit(main())
