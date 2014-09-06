import sys, os
import itertools
import collections

debug_enabled = os.environ.get('RULEBOOK_DEBUG')
if debug_enabled:
    from functools import partial
    debug = partial(print, '[rbk]', file=sys.stderr)
    trace_indent = 0
    def tracefunc(frame, event, arg):
        global trace_indent
        if 'rulebook' in frame.f_globals.get('__name__', ''):
            if event == "call":
                trace_indent += 2
                debug("-" * trace_indent + "> call function", frame.f_code.co_name)
            elif event == "return":
                debug("<" + "-" * trace_indent, "exit function", frame.f_code.co_name)
                trace_indent -= 2
        return tracefunc

    #sys.settrace(tracefunc)
else:
    debug = lambda *a,**kw: None

class LateBindingProperty(property):
    """An unrelated but useful piece of code. Allows the following use case:
        class A(object):
            def get_x(self): return 0
            x = LateBindingProperty(get_x)
        class B(A):
            def get_x(self): return 42
        print(B().x) # prints `42`, with ordinary `property` it would print `0`
    Losely based on http://code.activestate.com/recipes/408713-late-binding-properties-allowing-subclasses-to-ove/#c1
    """
    def __new__(cls, fget=None, fset=None, fdel=None, doc=None):

        if fget is not None:
            @functools.wraps(fget)
            def newget(obj, objtype=None, name=fget.__name__):
                fget = getattr(obj, name)
                return fget()

        if fset is not None:
            @functools.wraps(fset)
            def newset(obj, value, name=fset.__name__):
                fset = getattr(obj, name)
                return fset(value)

        if fdel is not None:
            @functools.wraps(fdel)
            def newdel(obj, name=fdel.__name__):
                fdel = getattr(obj, name)
                return fdel()

        return property(newget, newset, newdel, doc)


class WithFields(object):
    FIELDS_REQ = []
    FIELDS_OPT = []
    @property
    def FIELDS(self):
        return self.FIELDS_REQ + self.FIELDS_OPT
    def __init__(self, *args, **kw):
        data = dict(zip(self.FIELDS, itertools.chain(args, itertools.repeat(None))))
        data.update(kw)
        for fld in self.FIELDS_REQ:
            if fld not in data:
                raise ValueError("Field %s required for nodes of type %s"%(fld,
                    type(self).__name__))
        self.__dict__.update(data)

    def __repr__(self):
        return '%s(%s)'%( type(self).__name__, ', '.join([ repr(getattr(self, x)) for x in self.FIELDS ]) )

## class WeakishKeyDictionary(collections.MutableMapping):
##     """A class similar to weakref.WeakKeyDictionary. Unlike WeakKeyDictionary, which
##     stores whole keys as weakrefs, this one stores only non-trivial objects in the
##     key as weakrefs. Thus it allows you to have a key like (myobject, 'myattr').
##     You couldn't have that with a WeakKeyDictionary because there would be no strong
##     references to the tuple and thus it would be immediately garbage-collected*.
##     However, WeakishKeyDictionary stores the key as ``(weakref.ref(myobject), 'myattr')``,
##     elliminating this issue while still not forcing your object to remain alive.
##
##     * In fact, it would throw an exception because tuples are not weakreffable.
##
##     The types extempt from weakreffing are (quite naturally) those without __weakref__.
##     This includes all builtin immutable types like tuple, string, int, etc., which
##     should cover most use cases."""
##
##     def _convert_key(self, key, want_remove=False):
##         if isinstance(key, tuple):
##             return tuple( self._convert_key(itm, want_remove) for itm in key )
##         elif hasattr(key, '__weakref__'):
##             if want_remove:
##                 return weakref.ref(key, self._remove)
##             else:
##                 return weakref.ref(key)
##         elif hasattr(key, '__hash__'): # str, int, ...
##             return key
##         else:
##             raise TypeError("Don't know how to process key %r (type %s)" % (key, type(key).__name__))
##
##
##     def __getitem__(self, key):
##         pass

class ObjectKeyDict(collections.MutableMapping):
    """A dictionary that allows arbitrary mutable objects as keys (compared by identity).
    Furthermore, it allows composite keys containing mutable objects. You can have a key
    like ``(myobject, 'myattr')`` and this class will Do The Right Thing (compare the
    tuple and the string by value, while the object by identity).

    Internally this is done by replacing all the mutable (unhashable) objects in the
    key (tuples are walked recursively) with their ``id``s while keeping around a reference
    to the original objects. See the ``_convert_key`` method.
    """
    def __init__(self):
        self._data = {}

    def _convert_key(self, key, want_remove=False):
        if isinstance(key, tuple):
            return tuple( self._convert_key(itm, want_remove) for itm in key )
        elif hasattr(key, '__hash__'): # str, int, ...
            return key
        else:
            return id(key)

    def __getitem__(self, key):
        # As we hold a reference to the objects in the key, their ``id``s are guaranteed
        # to be unique so it's enough to compare them. No additional comparisons on the
        # stored original key (``_data[...][0]``) needed.
        return self._data[self._convert_key(key)][1]

    def __setitem__(self, key, val):
        self._data[self._convert_key(key)] = (key, val)

    def __delitem__(self, key):
        del self._data[self._convert_key(key)]

    def __contains__(self, key):
        return self._convert_key(key) in self._data

    def keys(self):
        return ( x[0] for x in self._data.values() )

    def values(self):
        return ( x[1] for x in self._data.values() )

    def items(self):
        return self._data.values()

    def get(self, key, default):
        return self._data.get(self._convert_key(key), (key, default))[1]

    def setdefault(self, key, val):
        return self._data.setdefault(self._convert_key(key), (key, val))[1]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self._data)

    # TODO implement more ``dict`` methods as needed.
