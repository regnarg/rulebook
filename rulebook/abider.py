from functools import wraps
from itertools import chain
from .util import *

class RuleAbider(object):
    def __init__(self):
        self._rbk_trackers = {}
        self._rbk_last_id = 0
    def __setattr__(self, name, val):
        # TODO: track setters (set_*)
        ## if isinstance(val, list): #TODO
        ##     val =
        super().__setattr__(name, val)
        if not name.startswith('_'):
            self._changed(name)
    def _changed(self, name):
        debug(self, '_changed', name, self._rbk_trackers)
        for tracker in ( chain(self._rbk_trackers.get(name, {}).values(),
                               self._rbk_trackers.get(None, {}).values()) ):
            tracker(self, name)
    def track(self, name, handler, ident=None):
        if ident is None:
            self._rbk_last_id += 1
            ident = self._rbk_last_id
        debug(self, 'track', name)
        self._rbk_trackers.setdefault(name, {})[ident] = handler
        return ident

    def untrack(self, name, ident):
        try:
            del self._rbk_trackers.get(name, {})[ident]
        except KeyError:
            pass

class AbideWrapper(RuleAbider):
    def __init__(self, obj):
        self.obj = obj
        raise NotImplementedError



