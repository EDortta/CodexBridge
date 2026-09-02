"""The executor's forge module -- where a `FORGE_OPERATION` actually talks to
a real code-forge, once something wires it in (that wiring is B3, not this
package). Structured as a package, mirroring `agent/codex_bridge_agent/runners/`
(`base.py` plus one file per implementation), so `gitlab.py`/`forgejo.py` can
be added later without reopening `github.py`.
"""

from __future__ import annotations
