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
    def _changed(self, sub):
        if isinstance(sub, str): sub = ('attr', sub)
        for tracker in ( chain(self._rbk_trackers.get(sub, {}).values(),
                               self._rbk_trackers.get(None, {}).values()) ):
            tracker()
    def track(self, sub, handler, ident=None):
        if isinstance(sub, str): sub = ('attr', sub)
        if ident is None:
            self._rbk_last_id += 1
            ident = self._rbk_last_id
        self._rbk_trackers.setdefault(sub, {})[ident] = handler
        return ident

    def untrack(self, sub, ident):
        if isinstance(sub, str): sub = ('attr', sub)
        try:
            del self._rbk_trackers.get(sub, {})[ident]
        except KeyError:
            pass

class AbideWrapper(RuleAbider):
    def __init__(self, obj):
        self.obj = obj
        raise NotImplementedError



