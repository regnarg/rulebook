
import sys
import copy, functools
import ast as pyast

class _Found(Exception):
    def __init__(self, node):
        self.node=node
        super().__init__()


class EnhancedVisitor(pyast.NodeVisitor):
    def generic_visit(self, node):
        if isinstance(node, (list, tuple)):
            for i in node:
                self.visit(i)
        else:
            return super().generic_visit(node)

def flatten(array):
    res = []
    for itm in array:
        if isinstance(itm, (list, tuple)):
            res.extend(flatten(itm))
        else:
            res.append(itm)
    return res

class EnhancedTransformer(pyast.NodeTransformer):
    def generic_visit(self, node):
        if isinstance(node, (list, tuple)):
            r = [ self.visit(sub) for sub in node ]
            r = flatten(r)
            r = [ x for x in r if x is not None ]
            return r
        else:
            return super().generic_visit(node)

class _LocateDefVisitor(EnhancedVisitor):
    def __init__(self, lineno):
        self.lineno=lineno
        super().__init__()

    def visit(self, node):
        if (isinstance(node, pyast.FunctionDef) and hasattr(node, 'lineno') and
            node.lineno+len(node.decorator_list)-1==self.lineno):
            raise _Found(node)
        else:
            self.generic_visit(node)

class _RelineVisitor(EnhancedVisitor):
    def __init__(self, base_lno, indent):
        self.base_lno=base_lno
        self.indent=indent
        super().__init__()
    def visit(self, node):
        if hasattr(node, 'lineno'):
            node.lineno=node.lineno-self.base_lno+1
        if hasattr(node, 'col_offset'):
            node.col_offset-=self.indent
        self.generic_visit(node)



def get_ast(fun):
    f=sys._getframe(1)
    if '__ast__' in f.f_globals:
        f_ast=f.f_globals['__ast__']
        #modname=f.f_globals['__name__']
        #mod=sys.modules[modname]
    else:
        modfile=f.f_globals['__file__']
        #print("*** PARSING")
        f_ast=f.f_globals['__ast__']=pyast.parse(open(modfile, 'rb').read())
    loc=_LocateDefVisitor(f.f_lineno)
    try:
        loc.visit(f_ast)
    except _Found as exc:
        node=exc.node
    else:
        raise SyntaxError("AST node not found (not used as a decorator?)")
    body=copy.deepcopy(node.body)
    base=body[0]
    rlv=_RelineVisitor(base.lineno, base.col_offset)
    for n in body: rlv.visit(n)
    return body


class _ClearLocVisitor(EnhancedVisitor):
    def visit(self, node):
        if hasattr(node, 'lineno'): del node.lineno
        if hasattr(node, 'col_offset'): del node.col_offset
        self.generic_visit(node)

def set_loc(node, loc=None):
    if loc is None:
        return functools.partial(set_loc, loc=node)
    if isinstance(node, (list, tuple)):
        for i in node:
            set_loc(i, loc)
        return node
    node.lineno=loc[0]
    node.col_offset=loc[2]
    node.dkv_filename=loc[3]
    return node

def clear_loc(node):
    _ClearLocVisitor().visit(node)
    return node

class _InterpolateTransformer(pyast.NodeTransformer):
    def __init__(self, replaces):
        self.replaces=replaces
        super().__init__()
    def visit(self,node):
        #special-case
        nod=node
        if isinstance(nod, pyast.Expr): nod=nod.value
        if isinstance(nod, pyast.Expression): nod=nod.body
        if isinstance(nod, pyast.Name) and nod.id in self.replaces:
            return self.replaces[nod.id]
        del nod
        #end special-case
        if isinstance(node, pyast.AST):
            node=copy.copy(node)
            for k,v in list(node.__dict__.items()):
                node.__dict__[self.visit(k)]=self.visit(v)
            return node
        elif isinstance(node, dict):
            return { self.visit(k): self.visit(v) for k,v in node.items() }
        elif isinstance(node, (list, tuple)):
            typ=type(node)
            r=[]
            for i in node:
                i=self.visit(i)
                if isinstance(i, (list, tuple)):
                    r.extend(i)
                else:
                    r.append(i)
            return typ(r)
        elif isinstance(node, str):
            if node in self.replaces: return self.replaces[node]
            else: return node
        else:
            return node


def interpolate(node=None, **kw):
    if node is None: return functools.partial(interpolate, **kw)
    return _InterpolateTransformer(kw).visit(node)


def single(nodes):
    if not isinstance(nodes, (list, tuple)) or len(nodes)!=1:
        raise ValueError("INTERNAL ERROR: Expected a single AST node")
    return nodes[0]




def fix_missing_locations_force(node, fn=None):
    """
    When you compile a node tree with compile(), the compiler expects lineno and
    col_offset attributes for every node that supports them.  This is rather
    tedious to fill in for generated nodes, so this helper adds these attributes
    recursively where not already set, by setting them to the values of the
    parent node.  It works recursively starting at *node*.
    """
    def _fix(node, lineno, col_offset, filename):
        if isinstance(node, list):
            for i in node: _fix(i, lineno, col_offset, filename)
            return
        if 'lineno' in node._attributes:
            if not hasattr(node, 'lineno'):
                node.lineno = lineno
            else:
                lineno = node.lineno
        if 'col_offset' in node._attributes:
            if not hasattr(node, 'col_offset'):
                node.col_offset = col_offset
            else:
                col_offset = node.col_offset
        if not hasattr(node, 'dkv_filename'):
            node.dkv_filename = filename
        else:
            filename = node.dkv_filename
        for child in pyast.iter_child_nodes(node):
            _fix(child, lineno, col_offset, filename)
    _fix(node, 1, 0, fn)
    return node


def literal_to_ast(obj):
    """Transform a literal object into corresponding AST.
Supported are strings, numbers, bools, None and lists/tuples/dicts containing supported objects.
"""
    if obj is True or obj is False or obj is None:
        return pyast.Name(repr(obj), pyast.Load())
    elif isinstance(obj, str):
        return pyast.Str(obj)
    elif isinstance(obj, (int,float,complex)):
        return pyast.Num(obj)
    elif isinstance(obj, tuple):
        return pyast.Tuple(list(map(literal_to_ast, obj)), pyast.Load())
    elif isinstance(obj, list):
        return pyast.List(list(map(literal_to_ast, obj)), pyast.Load())
    elif isinstance(obj, dict):
        keys=list(obj.keys())
        values=[ obj[x] for x in keys ]
        return pyast.Dict(keys, values)
    else:
        raise ValueError('{0!r} is not a valid literal')

def dotted(name, ctx=pyast.Load()):
    comps=name.split('.')
    if len(comps)==1:
        return pyast.Name(name, ctx)
    node=pyast.Name(comps[0], pyast.Load())
    for i in comps[1:]:
        node=pyast.Attribute(node, i, pyast.Load())
    node.ctx=ctx #only the outermost Attribute has the real ctx
    return node

def ensure_ast(v):
    if isinstance(v, pyast.AST):
        return v
    else:
        return literal_to_ast(v)

def build_call(func, *args, **kw):
    """Builds a ``pyast.Call`` node based on arguments passed
    (as AST nodes) to this function.

    This allows one to use the familiar Python call notation
    instead of laboriously building Call, Arg and other AST nodes."""

    if isinstance(func, str): func = dotted(func)
    args = [ ensure_ast(x) for x in args ]
    keywords = [ pyast.keyword(k, ensure_ast(v)) for k,v in kw.items() ]
    node = pyast.Call(func, args, keywords, None, None)

    return node

EMPTY_SIG = pyast.arguments([],None,[],[],None, [])

