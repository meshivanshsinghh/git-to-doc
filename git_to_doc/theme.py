"""Terminal theme for git-to-doc — classic green-on-black, minimal.

A single small palette shared by the CLI, renderer and compare tool so the
look stays consistent. Everything is green-family; red is reserved for genuine
errors. No emoji, no boxes — just text, dim dividers and one accent colour.
"""

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"   # body / success
BRIGHT = "\033[92m"   # accent — headers, key content
RED    = "\033[31m"   # errors only

WIDTH = 58


def c(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes, always resetting at the end."""
    return "".join(codes) + text + RESET


def rule(width: int = WIDTH) -> str:
    """A dim full-width divider."""
    return c("  " + "─" * width, DIM)


def section(label: str, width: int = WIDTH) -> str:
    """A minimal header: 'LABEL ─────────────' in bright green."""
    label = label.upper()
    dashes = "─" * max(2, width - len(label) - 1)
    return c(f"  {label} {dashes}", BOLD, BRIGHT)


def ok(text: str) -> str:
    return c(f"  ✓ {text}", GREEN)


def err(text: str) -> str:
    return c(f"  ✗ {text}", RED)


def dim(text: str) -> str:
    return c(f"  {text}", DIM)
