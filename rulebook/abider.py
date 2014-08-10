from functools import wraps

class RuleAbider(object):
    def __init__(self):
        self._trackers = {}
        self._last_id = 0
    def __setattr__(self, name, val):
        super().__setattr__(name, val)
        self._changed(name)
    def _changed(self, name):
        for tracker in ( self._trackers.get(name, [])
                        +self._trackers.get(None, []) ):
            tracker(self, name)
    def track(self, name, handler, ident=None):
        self._trackers.setdefault(name, {})[ident] = handler

    def untrack(self, name, ident):
        try:
            del self._trackers.get(name, {})[ident]
        except KeyError:
            pass

class AbideWrapper(RuleAbider):
    def __init__(self, obj):
        self.obj = obj
        raise NotImplementedError



