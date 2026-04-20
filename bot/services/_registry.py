"""Simple service registry for global singletons accessible across modules.

main.py sets these references after services are initialized.
miniapp.py reads them to trigger actions (e.g. refresh monitor after adding a trader).

All attributes default to None — callers MUST check for None before use.
"""

from typing import Optional, Any

# Set by main.py after init
monitor: Optional[Any] = None  # MultiMasterMonitor
engine: Optional[Any] = None  # CopyTradeEngine
position_manager: Optional[Any] = None
strategy_executor: Optional[Any] = None
