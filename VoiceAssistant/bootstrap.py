"""NEW (glue): make the vendored Pipecat source tree importable.

The vendored package lives at ``pipecat/src/pipecat``. Adding ``pipecat/src``
to ``sys.path`` lets the standalone app import it exactly as the upstream
project did, without installing a separate Pipecat distribution.
"""

import sys
from pathlib import Path

_VENDORED_SRC = Path(__file__).resolve().parent / "pipecat" / "src"

if str(_VENDORED_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDORED_SRC))
