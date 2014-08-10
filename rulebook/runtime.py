from .abider import  *
from .util import *
import weakref

class ObjectInfo:
    def __init__(self, ctx, obj):
        self.obj = weakref.ref(obj)
        self.ctx = ctx
        self.value_set = {}

class ObjectWrapper:
    def __init__(self, ctx, obj):
        self._rbk_info = ctx._info(obj)
        self._rbk_ctx = ctx
        self._rbk_obj = obj
        if self._rbk_obj is None: raise RuntimeError('Object no longer exists')

    @property
    def _rbk_info(self):
        return self.ctx._info(obj)

    def __getattr__(self, name):
        # TODO uncommited values (from value sets in self._rbk_info)
        # TODO track getters (get_*)
        self.ctx._report_read((self._rbk_obj, 'attr', name))
        return ObjectWrapper(self.ctx, getattr(self._rbk_obj, name))

    def __setattr__(self, name, val):
        return setattr(self._rbk_obj, name, val)

    # TODO: More Magic. (implement delegation of magic methods)
    #       http://code.activestate.com/recipes/252151-generalized-delegates-and-proxies/

def get_effective_value(vals):
    """Given a value set, computes the effective value, i.e. the one
    with highest priority. If more values have the same priority, the
    result is undefined."""
    # TODO: relative values
    return  max(vals.values(), key=lambda x: x[1])[0]

class Context:
    def __init__(self):
        self._last_id = 0
        self._object_info = weakref.WeakKeyDictionary()
        self._readtrack_stack = []

    def _info(self, obj):
        try:
            return self._object_info[obj]
        except KeyError:
            self._object_info[obj] = r = ObjectInfo(self, obj)
            return r

    def new_id(self):
        self._last_id += 1
        return self._last_id

    ### VALUE SET MANIPULATION {{{ ###

    def _value_set(self, target):
        obj, *sub = target
        return self._info(obj).value_set.setdefault(sub, {})

    def add_value(self, target, val, prio, ident=None):
        if ident is None: ident = self.new_id()

        self._value_set(target)[ident] = (val, prio)
        self._value_set_changed(target)

        return ident

    def remove_value(self, target, ident):
        try:
            del self_value_set(target)[ident]
        except KeyError:
            return
        self._value_set_changed(target)

    def _set_value(self, target, val):
        obj, subtype, subname = target
        if subtype == 'attr':
            setattr(obj, subname, val)
        elif subtype == 'item':
            obj[subname] = val
        else:
            raise ValueError

    def _value_set_changed(self, target):
        vals = self._value_set(target)
        eff = get_effective_value(vals)
        self._set_value(target, eff)

    ### }}} ###

    ### READ TRACKING {{{ ###

    def tracked_eval(self, expr):
        """Evaluates an expression (wrapped in a lambda by ``rulebook.compiler.Compiler._wrap_lambda``),
        recording its dependencties. Returns the tuple (value, depends)."""
        with ReadTracker() as deps:
            val = expr()
        return val, deps

    def _report_read(self, event):
        if self._readtrack_stack:
            self._readtrack_stack[-1].append(event)

    class _ReadTrackingContext:
        def __init__(self, ctx):
            self.ctx = ctx
        def __enter__(self):
            lst = []
            self.ctx._readtrack_stack.append(lst)
            return lst
        def __exit__(self, *a):
            self.ctx._readtrack_stack.pop()
    def track_reads(self):
        return self._ReadTrackingContext(self)

    ### }}} ###

    ### CHANGE TRACKING (WATCHES) {{{ ###

    ### }}} ###

class Namespace(RuleAbider):
    pass

class Wrapper(object):
    pass

class Directive(WithFields):
    def __init__(self, ctx, *args, **kw):
        super().__init__(*args, **kw)
        self.active = False
    def set_active(self, active):
        active = bool(active)
        if self.active == active: return
        self._set_active(active)
        self.active = active

# Try to keep fields names in sync with the AST!

class Block(Directive):
    FIELDS_REQ = ['body']
    def _set_active(self, active):
        for directive in self.body:
            directive.set_active(active)


class If(Directive):
    FIELDS_REQ = ['cond', 'body']
    FIELDS_OPT = ['orelse']
    def _set_active(self, active):
        if active:
            val, deps = tracked_eval(self.cond)
            self.body.set_active(val)
            if self.orelse:
                self.orelse.set_active(not val)
        else:
            self.body.set_active(False)
            if self.orelse:
                self.orelse.set_active(False)

class Assign(Directive):
    FIELDS_REQ = [ 'obj', 'subtype', 'subval', 'rhs', 'prio' ]

    def _set_active(self, active):
        if active:
            self._on_changed()
        else:
            self.ctx.remove_value(target, id(self))
            self.ctx.remove_watches((id(self), 'obj'))
            self.ctx.remove_watches((id(self), 'rhs'))

    def _on_changed(self, *a):
        obj, objdeps = self.ctx.tracked_eval(self.obj)
        val, deps    = self.ctx.tracked_eval(self.rhs)

        target = (self.obj, self.subtype, self.subval)
        self.ctx.add_value(target, val, prio, id(self))
        self.ctx.add_watches(obj_deps, self._on_changed, (id(self), 'obj'))
        self.ctx.add_watches(deps,     self._on_changed, (id(self), 'rhs'))
