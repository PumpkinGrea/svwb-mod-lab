"""Small shared Qt worker used by the editor and backup manager."""
from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):
    success = Signal(object)
    failure = Signal(str)


class Work(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failure.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.success.emit(result)
