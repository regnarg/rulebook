import sys, os
import importlib.util, importlib.machinery
from pathlib import Path

from . import compiler, runtime

RBK_TAG = 'rbk0'

def cache_from_source(path, debug_override=None):
    """Given the path to a .rbk file, return the path to its .pyc/.pyo file.

    A slight modification of the importlib.util.cache_from_source function
    from CPython 3.4.
    """
    debug = not sys.flags.optimize if debug_override is None else debug_override
    if debug:
        suffixes = importlib.machinery.DEBUG_BYTECODE_SUFFIXES
    else:
        suffixes = importlib.machinery.OPTIMIZED_BYTECODE_SUFFIXES
    head, tail = os.path.split(path)
    base_filename, sep, _ = tail.partition('.')
    try:
        py_tag = sys.implementation.cache_tag
    except AttributeError:
        # Fallback for Python versions before 3.3
        import imp
        py_tag = imp.get_tag()
    # (1) Make sure the cache tag contains both Rulebook version and Python version
    # (2) Separate rulebook `pyc`s so that the normal import mechanism doesn't try to load them
    tag = '%s-%s' % (RBK_TAG, py_tag)
    filename = ''.join([base_filename, sep, tag, suffixes[0]])
    return os.path.join(head, '__pycache__', filename)

def load(filename, ctx = None):
    cache_fn = cache_from_source(filename)
    # TODO load compiled

    if ctx is None:
        ctx = runtime.Context()

    code = compiler.compile(None, filename)

    vars = {}
    exec(code, vars, vars)
    root = vars['init'](ctx)

    return root, ctx

def load_string(s, filename='<string>', ctx=None):
    if ctx is None:
        ctx = runtime.Context()

    code = compiler.compile(s, filename)

    vars = {}
    exec(code, vars, vars)
    root = vars['init'](ctx)

    return root, ctx




