"""Python 入口。由 bin/modelrc 选定解释器后 exec 进来，不要直接执行。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modelrc.cli import main  # noqa: E402

raise SystemExit(main())
