import builtins
from .abider import  *
from .util import *
import weakref

import logging
logger = logging.getLogger(__name__)

class ObjectInfo:
    def __init__(self, ctx, obj):
        self.obj = weakref.ref(obj)
        self.ctx = ctx
        self.value_set = {}

class ObjectWrapper:
    def __init__(self, ctx, obj):
        self.__dict__['_rbk_info'] = ctx._info(obj)
        self.__dict__['_rbk_ctx'] = ctx
        self.__dict__['_rbk_obj'] = obj
        if self._rbk_obj is None: raise RuntimeError('Object no longer exists')

    @property
    def _rbk_info(self):
        return self.ctx._info(obj)

    def __getattr__(self, name):
        # TODO uncommited values (from value sets in self._rbk_info)
        # TODO track getters (get_*)
        logger.debug("REPORT_READ %s %s", self._rbk_obj, name)
        self._rbk_ctx._report_read((self._rbk_obj, 'attr', name))
        val = getattr(self._rbk_obj, name)
        # This condition serves two purposes:
        #  (1) ObjectWrapper creates (via ObjectInfo) a weakref to the object, so
        #      it has to be weakref-able.
        #  (2) Types missing __weakref__ are usually simple ones like 'int'.
        #      No point in wrapping those.
        if hasattr(val, '__weakref__'):
            return ObjectWrapper(self._rbk_ctx, val)
        else:
            return val

    def __iter__(self):
        self._rbk_ctx._report_read((self._rbk_obj, 'iter', None))
        return map(partial(ObjectWrapper, self._rbk_ctx), iter(self._rbk_obj))

    def __contains__(self, key):
        self._rbk_ctx._report_read((self._rbk_obj, 'item', key))
        return key in self._rbk_obj

    def __setattr__(self, name, val):
        return setattr(self._rbk_obj, name, val)

    # TODO: More Magic. (implement delegation of magic methods)
    #       http://code.activestate.com/recipes/252151-generalized-delegates-and-proxies/

    def __repr__(self):
        return '<OW:%s at 0x%x>'%(self._rbk_obj, id(self))

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
        self._watchsets = {}
        self.ns = Namespace()
        self.nswrap = ObjectWrapper(self, self.ns)

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
        if isinstance(obj, ObjectWrapper): obj = obj._rbk_obj
        return self._info(obj).value_set.setdefault(tuple(sub), {})

    def add_value(self, target, val, prio, ident=None):
        if ident is None: ident = self.new_id()

        self._value_set(target)[ident] = (val, prio)
        self._value_set_changed(target)

        return ident

    def remove_value(self, target, ident):
        try:
            del self._value_set(target)[ident]
        except KeyError:
            return
        self._value_set_changed(target)

    def _set_value(self, target, val):
        obj, subtype, subname = target
        if isinstance(obj, ObjectWrapper): obj = obj._rbk_obj
        if subtype == 'attr':
            setattr(obj, subname, val)
        elif subtype == 'item':
            obj[subname] = val
        else:
            raise ValueError

    def _value_set_changed(self, target):
        if isinstance(target[0], ObjectWrapper): target = (target[0]._rbk_obj,) + target[1:]
        vals = self._value_set(target)
        logger.debug('VALSET %s %s', target, vals)

        if vals:
            eff = get_effective_value(vals)
            self._set_value(target, eff)
        else:
            # If the value set is empty, the resulting value is undefined
            # (pretty much like a floating line in a circuit).
            # Currently, the last value set is kept but this may change.
            pass

    ### }}} ###

    ### READ TRACKING {{{ ###

    def tracked_eval(self, expr):
        """Evaluates an expression (wrapped in a lambda by ``rulebook.compiler.Compiler._wrap_lambda``),
        recording its dependencties. Returns the tuple (value, depends)."""
        with self.track_reads() as deps:
            val = expr()
        if isinstance(val, ObjectWrapper):
            val = val._rbk_obj
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

    def add_watchset(self, watches, func, ident=None):
        logger.debug('ADD_WATCHSET %s %s %s', watches, func, ident)
        if ident is None: ident = self.new_id()
        if ident in self._watchsets: self.remove_watchset(ident)
        subwatches = []
        for (obj, subtype, subname) in watches:
            subwatches.append((weakref.ref(obj), subtype, subname, obj.track((subtype, subname), func)))
        self._watchsets[ident] = subwatches


    def remove_watchset(self, ident):
        if ident not in self._watchsets: return
        for objref, subtype, subname, subwatch_id in self._watchsets[ident]:
            obj = objref()
            if obj is None: continue
            if subtype == 'attr':
                obj.untrack(subname, subwatch_id)
            else:
                raise NotImplementedError
        del self._watchsets[ident]

    ### }}} ###

class Namespace(RuleAbider):
    def __getattr__(self, name):
        return getattr(builtins, name)
    def __repr__(self):
        return 'N'

class NamespaceOverlay(object):
    def __init__(self, base, overlay):
        super().__init__()
        self._base = base
        self._overlay = overlay

    def __getattr__(self, name):
        if name.startswith('_'): raise AttributeError(name)
        if name in self._overlay:
            return self._overlay[name]
        else:
            return getattr(self._base, name)

    def __setattr__(self, name, value):
        if name.startswith('_'): return super().__setattr__(name, value)
        if name in self._overlay:
            #self._overlay[name] = value
            raise AttributeError("Cannot change overlaid attribute %s"%name)
        else:
            setattr(self._base, name, value)
        #self._changed(name)

class Directive(WithFields):
    def __init__(self, ctx, *args, **kw):
        super().__init__(*args, **kw)
        self.ctx = ctx
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
            self._on_changed(activating=True)
        else:
            self.body.set_active(False)
            if self.orelse:
                self.orelse.set_active(False)
            self.ctx.remove_watchset(id(self))

    def _on_changed(self, *a, activating=False):
        if not (self.active or activating): return
        val, deps = self.ctx.tracked_eval(self.cond)
        val = bool(val)
        logger.debug('IFCHG %s %s', self, val)
        self.body.set_active(val)
        if self.orelse:
            self.orelse.set_active(not val)
        self.ctx.add_watchset(deps,    self._on_changed, id(self))

class For(Directive):
    FIELDS_REQ = ['iter', 'body_factory']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cur_items = {}

    def _set_active(self, active):
        if active:
            self._on_changed(activating=True)
        else:
            self.ctx.remove_watchset(id(self))
            self._set_items([])

    def _on_changed(self, *a, activating=False):
        if not (self.active or activating): return
        val, deps = self.ctx.tracked_eval(self.iter)
        if isinstance(val, RuleAbider):
            deps.append((val, 'iter', None))

        self._set_items(val)
        self.ctx.add_watchset(deps,    self._on_changed, id(self))


    def _set_items(self, items):
        by_id = { id(x): x for x in items }
        new_ids = set(by_id.keys())
        old_ids = set(self.cur_items.keys())

        added = new_ids - old_ids
        removed = old_ids - new_ids

        for add_id in added:
            item = by_id[add_id]
            body = self.body_factory(item)
            body.set_active(True)
            self.cur_items[add_id] = item, body

        for rm_id in removed:
            item, body = self.cur_items[rm_id]
            body.set_active(False)
            del self.cur_items[rm_id]



class EnterLeave(Directive):
    FIELDS_REQ = ['event', 'body']

    def _set_active(self, active):
        if active == (self.event == 'enter'):
            self.body()

class Assign(Directive):
    FIELDS_REQ = [ 'obj', 'subtype', 'subval', 'rhs', 'prio' ]
    cur_obj = None

    def _set_active(self, active):
        logger.debug('%s %s', 'ACTIVATE' if active else 'DEACTIVATE', self)
        if active:
            self._on_changed()
        else:
            self._unset()

    def _unset(self):
        logger.debug('UNSET %s', self)
        if self.cur_obj is None: return
        cur_obj = self.cur_obj()
        if cur_obj is None: return
        target = (cur_obj, self.subtype, self.subval)
        logger.debug('UNSET2 %s', target)
        self.ctx.remove_value(target, id(self))
        self.ctx.remove_watchset((id(self), 'obj'))
        self.ctx.remove_watchset((id(self), 'rhs'))
        self.cur_obj = None

    def _on_changed(self, *a):
        obj, objdeps = self.ctx.tracked_eval(self.obj)
        val, deps    = self.ctx.tracked_eval(self.rhs)

        if self.cur_obj is None: cur_obj = None
        else: cur_obj = self.cur_obj()

        logger.debug('CHANGED %s %s %s', self, cur_obj, obj)

        if obj is not cur_obj:
            # LHS changed, we must remove the attribute from the old object
            # in addition to setting it on the new one
            self._unset()

        target = (obj, self.subtype, self.subval)
        self.ctx.add_value(target, val, self.prio or 0, id(self))
        self.ctx.add_watchset(objdeps, self._on_changed, (id(self), 'obj'))
        self.ctx.add_watchset(deps,    self._on_changed, (id(self), 'rhs'))
        self.cur_obj = weakref.ref(obj)

class _LambdaWithSource:
    """A helper for more helpful repr() of rulebook lambdas when debugging.

    When your rulebook contains::

        obj.x = 42 prio 5

    it allows you to see the directive object as::

        Assign(<L:N.obj>, 'attr', 'x', <L:42>, 5)

    instead of::

        Assign(<function init.<locals>.<lambda> at 0x7f6025392620>, 'attr',
                     'x', <function init.<locals>.<lambda> at 0x7f60253926a8>, 5)
    """
    def __init__(self, func, src):
        self.func = func
        self.src = src
    def __call__(self, *a, **kw):
        return self.func(*a, **kw)
    def __repr__(self):
        return '<L:%s>' % self.src
