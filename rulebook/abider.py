from functools import wraps
from itertools import chain
from .util import *

class RuleAbider(object):
    def __init__(self):
        self._rbk_trackers = set()
    def __setattr__(self, name, val):
        # TODO: track setters (set_*)
        ## if isinstance(val, list): #TODO
        ##     val =
        super().__setattr__(name, val)
        if not name.startswith('_'):
            self._changed(name)
    def _changed(self, sub):
        if isinstance(sub, str): sub = ('attr', sub)
        for tracker in self._rbk_trackers:
            tracker((self,) + sub)

class AbideWrapper(RuleAbider):
    def __init__(self, obj):
        self.obj = obj
        raise NotImplementedError



