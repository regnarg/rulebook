from pytest import *
from rulebook import loader
from rulebook.util import *
from rulebook.abider import *
from rulebook.runtime import *
import re

INDENT_RE = re.compile(r'^\s*')
def load_string(s):
    '''Strip any common indentation from a multi-line string.'''
    indent = min( INDENT_RE.match(line).span()[1] for line in s.split('\n') if line.strip() )
    s = '\n'.join( line[indent:] for line in s.split('\n') )
    return loader.load_string(s)

class TestObj(RuleAbider):
    '''A simple dummy object that is controlled by the test rulebooks.'''
    x = None
    def __init__(self, name):
        self._name = name
        super().__init__()
    def __repr__(self):
        return self._name

