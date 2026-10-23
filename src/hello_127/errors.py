"""The two failures a command can raise. Grammar errors need no class."""


class ReadinessError(Exception):
    """Something the run needed was missing, found before the first write."""


class RuntimeFailure(Exception):
    """A run that stopped partway, after the first write."""
