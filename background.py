"""
Runs blocking work (Scryfall requests, image downloads) on Qt's thread pool so
the window never freezes, then delivers the result back on the GUI thread.
"""

# Imports
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

# Tasks still in flight. Holding a reference here keeps each task's signal
# object alive until its result has been delivered.
_active = set()


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as error:  # surfaced to the UI instead of dying silently in a thread
            self.signals.failed.emit(str(error) or type(error).__name__)
        else:
            self.signals.succeeded.emit(result)


def run(fn, *args, on_success, on_error=None):
    # Calls fn(*args) on a worker thread. on_success(result) / on_error(message)
    # run on the GUI thread. Pass bound methods of widgets for the callbacks --
    # Qt drops the delivery automatically if that widget has been destroyed.
    task = _Task(fn, args)
    _active.add(task)
    task.signals.succeeded.connect(on_success)
    if on_error is not None:
        task.signals.failed.connect(on_error)
    task.signals.succeeded.connect(lambda _: _active.discard(task))
    task.signals.failed.connect(lambda _: _active.discard(task))
    task.setAutoDelete(False)
    QThreadPool.globalInstance().start(task)
