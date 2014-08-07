
from . import ast as rbkast, pyast_tools
import ast as pyast

def _nsify(node):
    class _NsifyTransformer(pyast.NodeTransformer):
        def generic_visit(self, node):
            if isinstance(node, (list, tuple)):
                return type(node)(self.visit(i) for i in node)
            else:
                return super().generic_visit(node)
        def visit(self, node):
            if isinstance(node, pyast.Name) and not (node.id.startswith('_') and not node.id.startswith('__')):
                nn=pyast.Name('ns', pyast.Load())
                pyast.copy_location(nn, node)
                na=pyast.Attribute(nn, node.id, node.ctx)
                pyast.copy_location(na, node)
                return na
            else:
                return self.generic_visit(node)
    return _NsifyTransformer().visit(node)

class Compiler:
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

        return pyast.Lambda(pyast_tools.EMPTY_SIG, expr)

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

        pynode = pyast_tools.build_call('_rbkapi.Assign', self._wrap_lambda(obj),
                                        subtype, subval, self._wrap_lambda(rhs), prio=node.prio)
        return pynode

    def _xform_block(self, node):
        pynodes = [ self.transform_node(directive) for directive in node.body ]
        return pyast_tools.build_call('_rbkapi.Block', pyast.List(pynodes, pyast.Load()))

    def _xform_if(self, node):
        return pyast_tools.build_call('_rbkapi.If', self._wrap_lambda(node.cond),
                                        self.transform_node(node.body))

    def _xform_rulebook(self, node):
        body_pynode = self.transform_node(node.body)
        return pyast.Module([pyast.Assign([pyast.Name('root', pyast.Store())], body_pynode)])


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
