"""Tools the model can ask us to run.

Unlike a provider's hosted tool — where the provider does the work and hands
back results — everything here executes in this process. That is the whole
difference: we own the loop, the cost, and the failure modes.
"""

from .web_search import SEARCH_TOOL_SCHEMA, web_search

__all__ = ["SEARCH_TOOL_SCHEMA", "web_search"]
