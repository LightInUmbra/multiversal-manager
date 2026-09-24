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
    progress = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as error:  # surfaced to the UI instead of dying silently in a thread
            outcome = (self.signals.failed, str(error) or type(error).__name__)
        else:
            outcome = (self.signals.succeeded, result)
        signal, value = outcome
        try:
            signal.emit(value)
        except RuntimeError:
            # The app is shutting down and the signal object is already gone -- nobody
            # is left to receive the result
            pass


def run(fn, *args, on_success, on_error=None, on_progress=None):
    # Calls fn(*args) on a worker thread. on_success(result) / on_error(message)
    # run on the GUI thread. Pass bound methods of widgets for the callbacks --
    # Qt drops the delivery automatically if that widget has been destroyed.
    # With on_progress, fn is also passed progress=callable; whatever fn calls it
    # with is handed to on_progress(value) on the GUI thread.
    task = _Task(fn, args, {})
    if on_progress is not None:
        task.kwargs["progress"] = task.signals.progress.emit
        task.signals.progress.connect(on_progress)
    _active.add(task)
    task.signals.succeeded.connect(on_success)
    if on_error is not None:
        task.signals.failed.connect(on_error)
    task.signals.succeeded.connect(lambda _: _active.discard(task))
    task.signals.failed.connect(lambda _: _active.discard(task))
    task.setAutoDelete(False)
    QThreadPool.globalInstance().start(task)
