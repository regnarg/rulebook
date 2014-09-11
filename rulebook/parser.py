"""Parser module"""

import sys, os, io
from functools import partial

from tokenize import tokenize,untokenize,TokenInfo
import tokenize as t
from . import ast as rbkast
import ast as pyast

from .util import *

def tokenize(arg, ensure_newline=False):
    """A simpler interface to the ``tokenize.tokenize`` function.
    Accepts string and file objects as input."""
    if isinstance(arg, str):
        arg = arg.encode('utf-8') # ``tokenize`` requires a byte string
    if isinstance(arg, bytes):
        from io import BytesIO
        arg = BytesIO(arg)
    if isinstance(arg, io.TextIOBase):
        arg = arg.buffer
    if hasattr(arg, 'read'):
        arg = arg.readline
    if callable(arg):
        orig_readline = arg
        if ensure_newline:
            def readline():
                r = orig_readline()
                # Absence of a final newline breaks the tokenizer
                if r and not r.endswith(b'\n'): return r + b'\n'
                else: return r
        else:
            readline = orig_readline
        arg = t.tokenize(readline)
    arg = list(arg)
    return arg

class Parser:
    # NL is used for ignored newlines in explicit and implicit line continuations
    # (as opposed to NEWLINE which signifies the end of a command). See the note
    # in ``parse_pycode`` for details.
    IGNORE = [t.ENCODING, t.NL, t.COMMENT]
    PY_BALANCE = {'(': ')', '[': ']', '{': '}', t.INDENT: t.DEDENT}

    KW_PRIO = (t.NAME, 'prio')
    KW_IF = (t.NAME, 'if')
    KW_ELSE = (t.NAME, 'else')
    KW_FOR = (t.NAME, 'for')
    ENTERLEAVE_KEYWORDS = [ (t.NAME, kw) for kw in ('enter', 'leave', 'c_enter', 'c_leave') ]
    IMPORT_KEYWORDS = [ (t.NAME, 'import'), (t.NAME, 'from') ]
    KW_SET = (t.NAME, 'set')

    in_simple_body = False

    def __init__(self, inp, filename = '<str>'):
        readline = None
        if inp is None:
            inp = open(filename, 'rb')
        self.tokens = tokenize(inp, ensure_newline=True)
        self.filename = filename
        self.pos = 0
        self.defaults = { 'prio': pyast.Num(0) }

    ### HELPER FUNCTIONS TO EASE TOKEN HANDLING ###

    def skip_ignored(self):
        while self.tokens[self.pos].type in self.IGNORE:
            self.pos += 1
        if self.tokens[self.pos].type == t.ERRORTOKEN:
            self.syntax_error("Invalid token: " + str(self.tokens[self.pos]))
    def match(self, spec):
        self.skip_ignored()
        if isinstance(spec, str):
            return self.match((t.OP, spec))
        elif isinstance(spec, int):
            return self.match((spec, None))
        elif isinstance(spec, tuple):
            return all( spec[i] is None or self.peek()[i] == spec[i] for i in range(2) )
        elif hasattr(spec, '__iter__'):
            for opt in spec:
                if self.match(opt): return True
            return False
        else:
            raise TypeError
    def syntax_error(self, msg):
        """Raise a SyntaxError at the current position in the source.
        The main purpose of this function is to fill in the correct line number and other info."""

        # Despite what the Python documentation claims, the ``line`` attribute of the
        # TokenInfo contains the physical, not logical line, i.e. what we need here,
        exc = SyntaxError(msg, (self.filename, self.tokens[self.pos].start[0],
                                    self.tokens[self.pos].start[1], self.tokens[self.pos].line))

        raise exc


    def expect(self, spec):
        if not self.match(spec):
            # TODO: better error message (token names)
            self.syntax_error("Expected " + repr(spec))
    def peek(self):
        self.skip_ignored()
        return self.tokens[self.pos]
    def eat(self, expected=None):
        if expected is not None:
            self.expect(expected)
        self.skip_ignored()
        r = self.tokens[self.pos]
        self.pos += 1
        return r

    ### INDIVIDUAL RECURSIVE DESCENT PARSING FUNCTIONS ###

    def eat_pycode(self, endtoks):
        """Eat a Python expression, statement or block (depending on `endtoks`)"""
        orig_ignore = self.IGNORE
        self.IGNORE = []
        try:
            ret = []
            parens = [] # A stack of open parentheses and other tookens that come in pairs.
                        # The expression cannot end until all of them are closed.
                        # This allows corect handling of e.g. ':'s inside  ``{'key': 'val'}``
                        # so that they don't terminate the expession.
                        #
                        # NB: This is not perfect. It doesn't correctly parse e.g.
                        # the expression in  ``if lambda f: None:``. You probably shouldn't
                        # write code like that anyway ;-). And if you must, parentheses are
                        # your friend).
            while True:
                # NB: Newlines and indentaion INSIDE expressions (due to explicit and implicit
                # line continuations) DOES NOT generate NEWLINE, INDENT or DEDENT tokens.
                # E.g.:
                #     $ cat >/tmp/x.py
                #     my_function(first_very_long_argument, second_very_long_argument,
                #                     third_very_long_argument)
                #     $ python -m tokenize /tmp/x.py
                #     0,0-0,0:            ENCODING       'utf-8'
                #     1,0-1,11:           NAME           'my_function'
                #     1,11-1,12:          OP             '('
                #     1,12-1,36:          NAME           'first_very_long_argument'
                #     1,36-1,37:          OP             ','
                #     1,38-1,63:          NAME           'second_very_long_argument'
                #     1,63-1,64:          OP             ','
                #     1,64-1,65:          NL             '\n'
                #     2,17-2,41:          NAME           'third_very_long_argument'
                #     2,41-2,42:          OP             ')'
                #     2,42-2,43:          NEWLINE        '\n'
                #     3,0-3,0:            ENDMARKER      ''
                # Therefore it's safe to say that an expression never contains the
                # aforementioned tokens.
                if self.match(endtoks) and not parens:
                    # The end token (e.g. a ':') is not a part of the expr, don't eat it)
                    break
                for opening, closing in self.PY_BALANCE.items():
                    if self.match(opening):
                        parens.append(closing)
                        break
                else:
                    if parens and self.match(parens[-1]):
                        parens.pop()
                ret.append(self.eat())
        finally:
            self.IGNORE = orig_ignore
        return ret

    def parse_pycode(self, endtoks, mode, *, prepend='', append=''):
        """Parse a Python expression starting at the current position in the token stream.
        The expression ends with the first occurence of any token from ``endtoks``, which
        does not become a part of the expression and is not eaten.

        Return the AST of the expression."""

        tokens = self.eat_pycode(endtoks)
        # Unfortunately, token streams cannot be parsed into ASTs from Python.
        # We must convert the tokens back to source code first.
        # See ``docs/desing/parser.md`` for more info.


        # The `untokenize` function has a curious habit of going to great lengths
        # in order to recreate the exact position (line and column number) of each
        # token in the output (so that tokenize(untokenize( partial_token_list ))
        # round-trips, including the ``start`` and ``end`` attributes).
        #
        # This means that when we untokenize a few tokens from line
        # 500, `untokenize` will prepend 499 newline characters to the output!
        # This can be circumvented by offsetting the line numbers so that the
        # token sequence starts at line 1.
        #
        # We must be wary of horizontal position, too, lest we want to
        # run into "unexpected indent" errors. Consider the
        # following Rulebook source:
        #     myfancydirective (firstitem,
        #                 seconditem)
        # Untokenizing the expression part would yield:
        #                      (firstitem,
        #                 seconditem)
        # which is clearly not a valid piece of Python code.
        # This can be resolved most easily by moving the very first token to column 0.

        if not tokens: self.syntax_error("Empty expression")

        #debug('parse_pycode BEFORE: tokens =', tokens)
        #src = prepend + untokenize(tokens) + append
        #debug('parse_pycode BEFORE: untokenized to\n    |' + src.replace('\n', '\n    |'))

        first_line = tokens[0].start[0]
        first_indent = tokens[0].start[1]

        def fix_col(col):
            col -= first_indent
            if col < 0: col = 0
            return col

        for idx in range(len(tokens)):
            tok = tokens[idx]
            newtok = list(tok)
            if tok.type == t.INDENT:
                newtok[1] = ' '*(len(tok.string) - first_indent)
            newtok[2] = (tok.start[0] - first_line + 1, fix_col(tok.start[1]))
            newtok[3] = (tok.end[0] - first_line + 1, fix_col(tok.end[1]))
            tokens[idx] = TokenInfo(*newtok)

        debug('parse_pycode: tokens =', tokens)
        src = prepend + untokenize(tokens) + append
        debug('parse_pycode: untokenized to\n    |' + src.replace('\n', '\n    |'))

        node = pyast.parse(src, self.filename, mode).body

        # TODO: Line number are wrong in `src`. Therefore we must:
        #   * fix them up in the AST
        #   * tranform them in SyntaxErrors that might be raised by `pyast.parse`

        return node

    def parse_directive(self):
        debug('parse_directive', self.peek())
        if self.match(self.KW_IF):
            self.eat()
            expr = self.parse_pycode([':', t.NEWLINE], 'eval')
            self.eat(':') # if it stopped at NEWLINE, this throws SyntaxError
            body = self.parse_body()
            if self.match(self.KW_ELSE):
                self.eat()
                self.eat(':')
                orelse = self.parse_body()
            else:
                orelse = None
            return rbkast.If(expr, body, orelse)
        elif self.match(self.KW_FOR):
            # (Ab)uses Python to parse the whole `for` header so that we don't
            # have to bother with correctly splitting the individual parts,
            # parsing the target expression in pyast.Store context, etc.
            pynode = self.parse_pycode([':', t.NEWLINE, t.DEDENT, t.INDENT], 'exec', append=': pass')[0]
            self.eat(':')
            body = self.parse_body()
            return rbkast.For(pynode.target, pynode.iter, body)
        elif self.match(self.ENTERLEAVE_KEYWORDS):
            event = self.eat().string
            self.eat(':')
            body = self.parse_pybody()
            return rbkast.EnterLeave(event, body)
        elif self.match(self.IMPORT_KEYWORDS):
            pynode = self.parse_pycode([t.NEWLINE, t.DEDENT], 'exec')[0]
            return rbkast.EnterLeave('enter', [pynode])
        elif self.match(self.KW_SET):
            self.eat()
            what = self.eat(t.NAME).string
            if what == 'prio':
                self.defaults['prio'] = self.parse_pycode([t.NEWLINE, t.DEDENT], 'eval')
            else:
                self.syntax_error("Unknown `set` directive: '%s'" % what)
            return None
        else:
            stoppers = [t.NEWLINE, t.DEDENT, self.KW_PRIO, '=']
            expr = self.parse_pycode(stoppers, 'eval')
            if self.match('='):
                # TODO multi-target assignments (x = y = 42)
                self.eat()
                lhs = expr
                if not hasattr(lhs, 'ctx'):
                    self.syntax_error("Invalid lvalue")
                lhs.ctx = pyast.Store()
                rhs = self.parse_pycode(stoppers, 'eval')
                node = rbkast.Assign(lhs, rhs, prio = self.defaults['prio'])
            else:
                raise NotImplementedError
            while not self.match([t.NEWLINE, t.DEDENT]):
                if self.match(self.KW_PRIO):
                    self.eat()
                    ## prio = int(pyast.literal_eval(self.parse_pycode(stoppers, 'eval')))
                    node.prio = self.parse_pycode(stoppers, 'eval')
                else:
                    self.syntax_error("Unexpected token")
            if self.match(t.NEWLINE): self.eat()
            return node

    def parse_block(self):
        r = []
        while True:
            if self.peek().type in [t.DEDENT, t.ENDMARKER]: break
            dir = self.parse_directive()
            if dir is not None:
                r.append(dir)
            if self.match(t.NEWLINE): self.eat()
        return rbkast.Block(r)

    def parse_body(self, parse_directive=None, parse_block=None):
        """Parse the body of a compound statement.
        That is either a single statement followed by a NEWLINE or a block enclosed
        in matching INDENT...DEDENT tokens."""

        if parse_directive is None: parse_directive = self.parse_directive
        if parse_block is None: parse_block = self.parse_block

        if self.match(t.NEWLINE):
            self.eat()
            self.eat(t.INDENT)
            body = parse_block()
            self.eat(t.DEDENT)
            return body
        elif self.in_simple_body:
            self.syntax_error("Nesting of simple bodies (e.g. ``if x: if y: z``) is not allowed.")
        else:
            self.in_simple_body = True
            r = parse_directive()
            self.in_simple_body = False
            return r

    def parse_pybody(self):
        return self.parse_body(partial(self.parse_pycode, [t.NEWLINE], 'exec'),
                               partial(self.parse_pycode, [t.DEDENT], 'exec'))

    def parse_rulebook(self):
        body = self.parse_block()
        return rbkast.Rulebook(body)

def parse(*a):
    return Parser(*a).parse_rulebook()

__all__ = ['Parser', 'parse', 'tokenize']

if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        file = None
        fn = sys.argv[1]
    else:
        file = sys.stdin
        fn = '<stdin>'
    p = Parser(file, fn)
    node = p.parse_block()
    rbkast.pprint(node)


