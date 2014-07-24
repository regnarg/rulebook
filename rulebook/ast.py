
from itertools import chain, repeat

class Node(object):
    FIELDS_REQ = []
    FIELDS_OPT = []
    @property
    def FIELDS(self):
        return self.FIELDS_REQ + self.FIELDS_OPT
    def __init__(self, *args, **kw):
        data = dict(zip(self.FIELDS, chain(args, repeat(None))))
        data.update(kw)
        for fld in self.FIELDS_REQ:
            if fld not in data:
                raise ValueError("Field %s required for nodes of type %s"%(fld,
                    type(self).__name__))
        self.__dict__.update(data)

    def __repr__(self):
        return '%s(%s)'%( type(self).__name__, ', '.join([ repr(getattr(self, x)) for x in self.FIELDS ]) )


class If(Node):
    FIELDS_REQ = ['cond', 'body']
    FIELDS_OPT = ['else']

class Assign(Node):
    FIELDS_REQ = [ 'lhs', 'rhs' ]
    FIELDS_OPT = [ 'prio' ]

