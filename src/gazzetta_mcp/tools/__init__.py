"""Thin MCP wrappers around ``GazzettaService``. Only this package and server.py know FastMCP."""

from .gazzetta import register
from .novita import register_novita
from .scadenze import register_scadenze
from .vigente import register_vigente

__all__ = ["register", "register_novita", "register_scadenze", "register_vigente"]
