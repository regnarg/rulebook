import builtins
from .abider import  *
from .util import *
import weakref
import collections
from contextlib import contextmanager
from functools import partial

import logging
logger = logging.getLogger(__name__)

class ObjectWrapper:
    def __init__(self, ctx, obj):
        if isinstance(obj, ObjectWrapper):
            raise TypeError("Trying to wrap already wrapped object %r" % obj)
            #obj = obj._rbk_obj
        self.__dict__['_rbk_ctx'] = ctx
        self.__dict__['_rbk_obj'] = obj
        if self._rbk_obj is None: raise RuntimeError('Object no longer exists')

    def __getattr__(self, name):
        return self._rbk_ctx.read_value((self._rbk_obj, 'attr', name))

    def __getitem__(self, key):
        return self._rbk_ctx.read_value((self._rbk_obj, 'item', key))

    def __iter__(self):
        self._rbk_ctx._report_read((self._rbk_obj, 'iter', None))
        return map(partial(ObjectWrapper, self._rbk_ctx), iter(self._rbk_obj))

    def __contains__(self, key):
        self._rbk_ctx._report_read((self._rbk_obj, 'item', key))
        return key in self._rbk_obj

    def __setattr__(self, name, val):
        setattr(self._rbk_obj, name, val)

    def __setitem__(self, key, val):
        self._rbk_obj[key] = val

    # TODO: More Magic. (implement delegation of magic methods)
    #       http://code.activestate.com/recipes/252151-generalized-delegates-and-proxies/

    def __repr__(self):
        return '<OW:%s at 0x%x>'%(self._rbk_obj, id(self))

    # This is ugly. Is there a language with less horrible dynamic code creation?
    for _tmp_meth in ['__eq__', '__ne__', '__lt__', '__gt__', '__le__', '__ge__']:
        def _tmp_mkfunc(meth=_tmp_meth):
            def _tmp_func(self, other):
                a = self._rbk_obj
                if isinstance(other, ObjectWrapper): b = other._rbk_obj
                else: b = other
                return getattr(a, meth)(b)
            _tmp_func.__name__ = meth
            return _tmp_func
        locals()[_tmp_meth] = _tmp_mkfunc()
    del _tmp_meth, _tmp_mkfunc

def get_effective_value(vals):
    """Given a value set, computes the effective value, i.e. the one
    with highest priority. If more values have the same priority, the
    result is undefined."""
    lst = sorted(vals.values(), key=lambda x: -x[1])
    anchor = 0 # The highest priority non-relative value (with comb=None)
    while anchor < len(lst) and lst[anchor][2]:
        anchor += 1
    if lst[anchor][2]:
        ## TODO we should say which one :-D
        raise RuntimeError("Value set contains only relative values")
    val = lst[anchor][0]
    for (relval, _, comb) in reversed(lst[:anchor]):
        val = comb(val, relval)
    return val

class Context:
    # The maximum length of an event chain before the rulebook is considered oscillating
    # and an exception is raised.
    MAX_CHAIN = 1000
    # Types that don't need change tracking -- simple immutable builtin types
    UNTRACKED = (str, bool, int, tuple, frozenset, float, complex, type(None))
    def __init__(self):
        self._last_id = 0
        self._readtrack_stack = []

        self._valuesets = ObjectKeyDict()
        # Every time the value set is changed during a transaction, the effective
        # value is stored here. This has two purposes:
        # (1) Cache the effective value so that we don't have to traverse the whole
        #     value set for every in-transaction read.
        # (2) Keep a list of targets changed during the transaction which can be
        #     used to commit the changes.
        self._uncommitted = ObjectKeyDict()
        self._uncommitted_directives = ObjectKeyDict() # Used as a set, the values are ignored

        self._watchsets = {}
        self._watchers = ObjectKeyDict()
        self._queue = collections.deque()
        self._inhibit_cnt = ObjectKeyDict()

        self.in_transaction = False
        self._processing = False

        self.commit_hooks = []

        self.ns = Namespace()
        self.nswrap = ObjectWrapper(self, self.ns)

    def new_id(self):
        self._last_id += 1
        return self._last_id

    def _unwrap(self, obj):
        if isinstance(obj, ObjectWrapper):
            return obj._rbk_obj
        else:
            return obj

    def _wrap(self, obj):
        if isinstance(obj, ObjectWrapper):
            return obj
        elif isinstance(obj, RuleAbider):
            return ObjectWrapper(self, obj)
        else:
            if not isinstance(obj, self.UNTRACKED):
                logger.warn('Cannot track %r of type %s'%(obj, type(obj).__name__))
            return obj

    ### VALUE SET MANIPULATION {{{ ###


    def add_value(self, target, val, prio, ident=None, comb=None):
        val = self._unwrap(val)
        target = (self._unwrap(target[0]),) + target[1:]
        prio = self._unwrap(prio)
        if ident is None: ident = self.new_id()

        self._valuesets.setdefault(target, {})[ident] = (val, prio, comb)
        self._value_set_changed(target)

        return ident

    def remove_value(self, target, ident):
        target = (self._unwrap(target[0]),) + target[1:]
        try:
            del self._valuesets.setdefault(target, {})[ident]
        except KeyError:
            logger.debug('Not removing %r %r', target, self._valuesets.setdefault(target, {}))
            return
        self._value_set_changed(target)

    @contextmanager
    def _inhibit_notify(self, target):
        try:
            self._inhibit_cnt.setdefault(target, 0)
            self._inhibit_cnt[target] += 1
            yield
        finally:
            self._inhibit_cnt[target] -= 1
            if self._inhibit_cnt[target] <= 0:
                del self._inhibited[target]

    def _do_set(self, target, val):
        obj, subtype, subname = target
        if isinstance(obj, ObjectWrapper): obj = obj._rbk_obj
        if subtype == 'attr':
            # Support the explicit setter idiom common in Python.
            if hasattr(obj, 'set_' + subname):
                getattr(obj, 'set_' + subname)(val)
            else:
                setattr(obj, subname, val)
        elif subtype == 'item':
            obj[subname] = val
        else:
            raise ValueError

    def _value_set_changed(self, target):
        vals = self._valuesets.get(target, {})
        if not vals and target in self._valuesets:
            del self._valuesets[target]
        logger.debug('VALSET %s %s', target, vals)

        if vals:
            eff = get_effective_value(vals)
            if self.in_transaction:
                self._uncommitted[target] = eff
            else:
                self._do_set(target, eff)
            self.notify_change(target, external=False)
        else:
            # If the value set is empty, the resulting value is undefined
            # (pretty much like a floating line in a circuit).
            # For now, we just keep the last value.
            # The best solution is to always include a low-priority assignment
            # with some sane default value in the root of your rulebook.
            #
            # Especially when you assign complex objects using Rulebook,
            # it is recommended to have a fallback rule configured that
            # resets the given target back to None when the object should
            # no longer be here. E.g.:
            #
            #     something.someattr = None prio -1000
            #     if <some-condition>:
            #         something.someattr = MyComplexObject()
            #
            # Without the first line, the object would fail to be garbage collected
            # when <some-condition> ceases to hold.
            pass

    ### }}} ###

    ### READ TRACKING {{{ ###

    def tracked_eval(self, expr):
        """Evaluates an expression (wrapped in a lambda by ``rulebook.compiler.Compiler._wrap_lambda``),
        recording its dependencties. Returns the tuple (value, depends)."""
        with self.track_reads() as deps:
            val = expr()
        return val, deps

    def _report_read(self, event):
        if self._readtrack_stack:
            self._readtrack_stack[-1].append(event)

    def _do_read(self, target):
        obj, subtype, subname = target
        if subtype == 'attr':
            return getattr(obj, subname)
        elif subtype == 'item':
            return obj[subname]
        elif subtype == 'iter':
            return iter(obj)
        else:
            raise ValueError("Unknown target type %r" % subtype)

    def read_value(self, target):
        if target in self._uncommitted:
            val = self._uncommitted[target]
        else:
            val = self._do_read(target)
        if self._readtrack_stack:
            self._report_read(target)
            val = self._wrap(val)
        return val

    @contextmanager
    def track_reads(self):
        lst = []
        self._readtrack_stack.append(lst)
        try:
            yield lst
        finally:
            self._readtrack_stack.pop()

    ### }}} ###

    ### CHANGE TRACKING (WATCHES) {{{ ###

    def commit(self):
        if not self.in_transaction: raise RuntimeError("Commit with no transaction")
        logger.debug('COMMIT')
        for dir in self._uncommitted_directives:
            logger.debug('COMMIT_DIR %r', dir)
            dir.commit()
        commit_objs = {}
        for target, val in self._uncommitted.items():
            if hasattr(target[0], '_rbk_commit'):
                commit_objs[id(target[0])] = target[0]
            logger.debug('COMMIT_VAL %r %r', target, val)
            self._do_set(target, val)
        commit_objs = sorted(commit_objs.values(), key=lambda obj: getattr(obj, '_rbk_commit_order', 0))
        for obj in commit_objs:
            logger.debug('COMMIT_OBJ %r', obj)
            obj._rbk_commit()
        for hook in self.commit_hooks:
            logger.debug('COMMIT_HOOK %r', hook)
            hook(commit_objs)
        self._uncommitted = ObjectKeyDict()
        self._uncommitted_directives = ObjectKeyDict()
        self.in_transaction = False

    def begin(self):
        if self.in_transaction: raise RuntimeError("Transaction already started")
        logger.debug('BEGIN')
        self.in_transaction = True

    def process_events(self):
        if self._processing: raise RuntimeError("Nested process_events call")
        logger.debug('PROCESS_BEGIN')
        self._processing = True
        try:
            in_trans = self.in_transaction
            if not in_trans: self.begin()
            cnt = 0
            while self._queue:
                target = self._queue.popleft()
                cnt += 1
                # list() is necessary as watchers might change during iteration
                for func in list(self._watchers.get(target, {}).values()):
                    func(target)

                if cnt > self.MAX_CHAIN:
                    raise RuntimeError("Maximum number of transaction events exceeded"
                            " (probable reason: oscillating configuration). Current: %r, next 10: %r"
                            % (target, list(self._queue)[:10]))
            if not in_trans: self.commit()
        except:
            # XXX temporary workaround for broken exception handling in Network Secretary
            # TODO remove
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            sys.exit(1)
        finally:
            self._processing = False
            logger.debug('PROCESS_END')

    def notify_change(self, target, external=True):
        logger.debug('NOTIFY_%s %r in_trans=%d processing=%d',
                'EXT' if external else 'INT', target, self.in_transaction,
                self._processing)
        if target in self._inhibit_cnt:
            logger.debug('...inhibit')
            return
        self._queue.append(target)
        if not self._processing:
            self.process_events()

    def add_watchset(self, targets, func, ident=None):
        logger.debug('ADD_WATCHSET %s %s %s', targets, func, ident)
        if ident is None: ident = self.new_id()
        if ident in self._watchsets: self.remove_watchset(ident)
        for target in targets:
            obj, *sub = target
            if isinstance(obj, ObjectWrapper): raise TypeError("Cannot track ``ObjectWrapper``s")
            self._watchers.setdefault(target, collections.OrderedDict())[ident] = func
            if isinstance(obj, RuleAbider):
                obj._rbk_trackers.add(self.notify_change)
            else:
                logger.warn("Cannot track %r", target)
        self._watchsets[ident] = targets

    def remove_watchset(self, ident):
        if ident not in self._watchsets: return
        for target in self._watchsets[ident]:
            try: del self._watchers[target][ident]
            except KeyError: pass
        del self._watchsets[ident]

    ### }}} ###

class Namespace(RuleAbider):
    def __getattr__(self, name):
        return getattr(builtins, name)
    def __repr__(self):
        return 'N'

class NamespaceOverlay(object):
    def __init__(self, ctx, base, overlay):
        super().__init__()
        self._ctx = ctx
        self._base = base
        self._overlay = overlay

    def __getattr__(self, name):
        if name.startswith('_'): raise AttributeError(name)
        if name in self._overlay:
            return self._ctx._wrap(self._overlay[name])
        else:
            return self._ctx._wrap(getattr(self._base, name))

    def __setattr__(self, name, value):
        if name.startswith('_'): return super().__setattr__(name, value)
        if name in self._overlay:
            #self._overlay[name] = value
            raise AttributeError("Cannot change overlaid attribute %s"%name)
        else:
            setattr(self._base, name, value)
        #self._changed(name)

class LocalNamespace(object):
    def __init__(self, ctx, base):
        self._ctx = ctx
        self._base = base
        self._locals = {}
        self._globals = set()

    def __setattr__(self, name, value):
        if name.startswith('_'): return super().__setattr__(name, value)
        if name in self._globals:
            setattr(self._base, name, value)
        else:
            self._locals[name] = self._ctx._unwrap(value)

    def __getattr__(self, name):
        if name.startswith('_'): raise AttributeError(name)
        if name in self._locals:
            return self._ctx._wrap(self._locals[name])
        else:
            return self._ctx._wrap(getattr(self._base, name))



class Directive(WithFields):
    def __init__(self, ctx, *args, **kw):
        super().__init__(*args, **kw)
        self.ctx = ctx
        # (in)active state as seen by the current transaction (if any, committed state otherwise)
        self.active = False
        # (in)active state as last committed
        self.c_active = False

    def _set_active(self, active):
        pass

    def set_active(self, active):
        active = bool(active)
        if self.active == active: return
        in_trans = self.ctx.in_transaction
        if not in_trans: self.ctx.begin()
        self._set_active(active)
        self.active = active
        self.ctx._uncommitted_directives[self] = True
        if not self.ctx._processing: self.ctx.process_events()
        if not in_trans: self.ctx.commit()

    def _commit(self):
        pass

    def commit(self):
        if self.c_active != self.active:
            self._commit()
            self.c_active = self.active

# Try to keep fields names in sync with the AST!

class Block(Directive):
    FIELDS_REQ = ['body']
    def _set_active(self, active):
        if active:
            for directive in self.body:
                directive.set_active(True)
        else:
            for directive in reversed(self.body):
                directive.set_active(False)


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
        self.ctx.add_watchset(deps,    self._on_changed, id(self))
        logger.debug('IFCHG %s %s', self, val)
        self.body.set_active(val)
        if self.orelse:
            self.orelse.set_active(not val)

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
        if isinstance(self.ctx._unwrap(val), RuleAbider):
            deps.append((self.ctx._unwrap(val), 'iter', None))

        self._set_items(val)
        self.ctx.add_watchset(deps,    self._on_changed, id(self))


    def _set_items(self, items):
        items = [ self.ctx._unwrap(x) for x in items ]
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
        if ((self.event == 'enter' and active)
                or (self.event == 'leave' and not active)):
            self.body()

    def _commit(self):
        if ((self.event == 'c_enter' and self.active)
                or (self.event == 'c_leave' and not self.active)):
            self.body()

class Assign(Directive):
    FIELDS_REQ = ['obj', 'subtype', 'subval', 'rhs', 'prio']
    FIELDS_OPT = ['comb']
    cur_obj = None
    comb = None

    def _set_active(self, active):
        logger.debug('%s %s', 'ACTIVATE' if active else 'DEACTIVATE', self)
        if active:
            self._on_changed(activating=True)
        else:
            self._unset()

    def _commit(self):
        # Do not have to do anything. Value sets are committed separately.
        # If the commit were done here and there were multiple assignments
        # to the same target, each of them would set the value on the target
        # object, resulting in the same value being assigned multiple times.
        # This could be possibly an expensive operation (especially when
        # we call explicit setters).
        pass

    def _unset(self):
        logger.debug('UNSET %s', self)
        if self.cur_obj is None: return
        cur_obj = self.cur_obj()
        if cur_obj is None: return
        target = (cur_obj, self.subtype, self.subval)
        logger.debug('UNSET2 %s', target)
        self.ctx.remove_value(target, id(self))
        self.ctx.remove_watchset(id(self))
        self.cur_obj = None

    def _on_changed(self, *a, activating=False):
        if not (self.active or activating): return
        obj, obj_deps = self.ctx.tracked_eval(self.obj)
        val, val_deps    = self.ctx.tracked_eval(self.rhs)
        if isinstance(obj, ObjectWrapper):
            obj = obj._rbk_obj
        if isinstance(val, ObjectWrapper):
            val = val._rbk_obj
        if self.prio:
            prio, prio_deps    = self.ctx.tracked_eval(self.prio)
        else:
            prio, prio_deps = 0, []

        if self.cur_obj is None: cur_obj = None
        else: cur_obj = self.cur_obj()

        logger.debug('CHANGED %s %s %s', self, cur_obj, obj)

        if obj is not cur_obj:
            # LHS changed, we must remove the attribute from the old object
            # in addition to setting it on the new one
            self._unset()

        target = (obj, self.subtype, self.subval)
        self.ctx.add_value(target, val, prio, id(self), comb=self.comb)
        self.ctx.add_watchset(obj_deps + val_deps + prio_deps, self._on_changed, id(self))
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

### DIRECTIVES WITHOUT A SPECIAL SYNTAX (used with CustomDirective) ###
