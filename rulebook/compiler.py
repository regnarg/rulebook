
from . import ast as rbkast, pyast_tools
from .util import *
import ast as pyast
import builtins

def _nsify(node):
    class _NsifyTransformer(pyast.NodeTransformer):
        def generic_visit(self, node):
            if isinstance(node, (list, tuple)):
                return type(node)(self.visit(i) for i in node)
            else:
                return super().generic_visit(node)
        def visit(self, node):
            if isinstance(node, pyast.Name) and not (node.id.startswith('_') and not node.id.startswith('__')):
                #nn=pyast.Attribute(Compiler.CTX, 'nswrap', pyast.Load())
                nn = pyast_tools.dotted('N')
                pyast.copy_location(nn, node)
                na=pyast.Attribute(nn, node.id, node.ctx)
                pyast.copy_location(na, node)
                return na
            else:
                return self.generic_visit(node)
    return _NsifyTransformer().visit(node)

class Compiler:
    CTX = pyast_tools.dotted('C')
    def transform_node(self, node):
        """Transform a Rulebook AST node to corresponding Python code (represented as AST)."""
        for cls in type(node).__mro__:
            meth = '_xform_%s' % cls.__name__.lower()
            if hasattr(self, meth):
                return getattr(self, meth)(node)
        raise TypeError("Don't know how to compile %r of type %r" % (node, type(node)))

    def _wrap_lambda(self, expr):
        """Wrap the expression in a Lambda so that it is not evaluated
        immediately but at the appropriate time (e.g. what a directive
        is activated."""

        r = pyast.Lambda(pyast_tools.EMPTY_SIG, expr)
        if debug_enabled:
            try:
                import astunparse
            except ImportError:
                pass
            else:
                src = astunparse.unparse(expr).strip()
                r = pyast_tools.build_call('R._LambdaWithSource', r, src)
        return r

    def _xform_assign(self, node):
        lhs = _nsify(node.lhs)
        rhs = _nsify(node.rhs)
        if isinstance(lhs, pyast.Attribute):
            obj = lhs.value
            subtype = 'attr'
            subval = pyast_tools.literal_to_ast(lhs.attr)
        elif isinstance(lhs, pyast.Subscript):
            obj = lhs.value
            subtype = 'item'
            if isinstance(lhs.slice, pyast.Index):
                sub = lhs.slice.value
            elif isinstance(lhs.slice, pyast.Slice):
                sub = pyast_tools.build_call('slice', lhs.slice.lower,
                        lhs.slice.upper, lhs.slice.step)
            else:
                raise TypeError
        else:
            # Plain name assignments (x = y) do not fall here as _NsifyTransformer
            # makes them into attribute assignments (ns.x = y).
            #
            # The known unhandled cases are Tuple and List (yes, List is an L-value,
            # I was surprised just like you; try this: ``[x,y] = [4,2]``).
            raise NotImplementedError("Unsupported assignment LHS: %s", pyast.dump(lhs))

        pynode = self._build_directive('Assign', self._wrap_lambda(obj),
                                        subtype, subval, self._wrap_lambda(rhs), prio=node.prio)
        return pynode

    def _xform_block(self, node):
        pynodes = [ self.transform_node(directive) for directive in node.body ]
        return self._build_directive('Block', pyast.List(pynodes, pyast.Load()))

    def _xform_if(self, node):
        return self._build_directive('If', self._wrap_lambda(_nsify(node.cond)),
                                        self.transform_node(node.body))

    def _xform_rulebook(self, node):
        body_pynode = self.transform_node(node.body)
        @pyast_tools.interpolate(ROOT=body_pynode)
        @pyast_tools.get_ast
        def module_body():
            from rulebook import runtime as R
            def init(ctx):
                C = ctx
                N = ctx.nswrap
                return ROOT

        #return pyast.Module([pyast.Assign([pyast.Name('root', pyast.Store())], body_pynode)])
        return pyast.Module(module_body)

    def _build_directive(self, name, *args, **kw):
        return pyast_tools.build_call('R.'+name, self.CTX, *args, **kw)

def compile(source_or_ast, filename=None):
    if not isinstance(source_or_ast, rbkast.Node):
        from . import parser
        source_or_ast = parser.parse(source_or_ast, filename)
    compiler = Compiler()
    node = compiler.transform_node(source_or_ast)
    node = pyast.fix_missing_locations(node)
    code = builtins.compile(node, filename, 'exec')
    return code

__all__ = ['Compiler', 'compile']

if __name__ == '__main__':
    import sys, argparse

    parser = argparse.ArgumentParser()

    parser.add_argument('-t', '--tree', help='Print AST tree instad of Python source'
                                             ' (-tt for non-pretty-printed `ast.dump` for the brave)',
                        action='count')
    parser.add_argument('filename', default=None)

    args = parser.parse_args()

    if args.filename is None:
        file = sys.stdin
        fn = '<stdin>'
    else:
        file = None
        fn = args.filename
    from . import parser
    node = parser.parse(file, fn)

    comp = Compiler()
    pynode = comp.transform_node(node)

    try:
        import astunparse
    except ImportError:
        print("The `astunparse` package is required for displaying the compiled output."
              " Install it with ``pip install astunparse`` or from <https://github.com/simonpercivall/astunparse/>.",
                file=sys.stderr)
        sys.exit(1)

    if args.tree == 2:
        print(pyast.dump(pynode))
    elif args.tree == 1:
        printer = astunparse.Printer()
        printer.visit(pynode)
    else:
        unparser = astunparse.Unparser(pynode, file=sys.stdout)
        # Apparently, ``Unparser`` does all the work in the contructor.
        # Ugly but what can I do.
