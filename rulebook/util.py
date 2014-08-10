import itertools

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
