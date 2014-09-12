
import sys
import ast as pyast
from .util import *
from itertools import chain, repeat

class Node(WithFields):
    pass

class PrettyPrinter(object):
    def __init__(self, out=sys.stdout):
        self.out = out
    def pprint(self, node):
        self.reset()
        self._pprint(node)
        if not self.bol:
            self.out.write('\n') # Add the final newline
    def reset(self):
        self.bol = True
        self.eol = False
        self.indent = 0
    def write(self, s):
        if self.eol:
            self.eol = False
            if not self.bol:
                self.out.write('\n')
                self.bol = True
        if self.bol:
            self.out.write(' '*self.indent)
        self.out.write(s)
        self.bol = s.endswith('\n')
    def newline(self):
        """Ensure a line break at the current position of the output stream.
        Multiple consecutive calls insert only *one* line break (no empty lines).
        Line breaks are never inserted at the start or end of output.

        Do not call ``newline`` at start/end of ``_pprint``, that would prevent
        the caller to e.g. append a comma to your output."""
        self.eol = True
    def _pprint(self, node):
        if isinstance(node, pyast.AST):
            node_repr = pyast.dump(node)
        else:
            node_repr = repr(node)
        if isinstance(node, (pyast.AST, list, Node)) and len(node_repr) + self.indent > 64:
            if isinstance(node, list):
                self.write('[')
                self.newline()
                self.indent += 4
                for idx, item in enumerate(node):
                    if idx:
                        self.write(',')
                    self.newline()
                    self._pprint(item)
                self.indent -= 4
                self.newline()
                self.write(']')
            elif isinstance(node, Node):
                self.write(type(node).__name__ + '(')
                self.newline()
                self.indent += 4
                for idx, fld in enumerate(node.FIELDS):
                    if idx >= len(node.FIELDS_REQ) and val is None:
                        continue
                    if idx:
                        self.write(',')
                    self.newline()
                    if idx >= len(node.FIELDS_REQ):
                        self.write(fld + ' = ')
                    val = getattr(node, fld)
                    fldprefix = ""
                    self._pprint(val)
                self.indent -= 4
                self.newline()
                self.write(')')
            else:
                self.write(node_repr)
        else:
            self.write(node_repr)

def pprint(node):
    return PrettyPrinter().pprint(node)

class Block(Node):
    FIELDS_REQ = ['body']

class If(Node):
    FIELDS_REQ = ['cond', 'body']
    FIELDS_OPT = ['orelse']

class For(Node):
    FIELDS_REQ = ['target', 'iter', 'body']

class Assign(Node):
    FIELDS_REQ = ['lhs', 'rhs']
    FIELDS_OPT = ['prio']

class Rulebook(Node):
    FIELDS_REQ = ['body']

class Import(Node):
    FIELDS_REQ = ['pynode']

class EnterLeave(Node):
    ENTER = 'enter'
    LEAVE = 'leave'
    FIELDS_REQ = ['event', 'body']
