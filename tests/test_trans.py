from testlib import *

class EvenOnly:
    def __setattr__(self, name, val):
        if val % 2 == 1: raise ValueError("I don't like odd numbers!")
        super().__setattr__(name, val)
def test_trans_assign():
    root,ctx = load_string('''
        obj.a = 2*x + 1
        obj.a = 2*x prio 10
        obj.a = 2*x + 1
    ''')
    ctx.ns.obj = obj = EvenOnly()
    ctx.ns.x = 0
    root.set_active(True)
    assert obj.a == 0
    ctx.ns.x = 5
    assert obj.a == 10

def test_trans_assign_indirect():
    root,ctx = load_string('''
        y = 1
        obj.a = 2*x + 1
        obj.a = y prio 10
        obj.a = 2*x + 1
        y = 2*x prio 10
    ''')
    ctx.ns.obj = obj = EvenOnly()
    ctx.ns.x = 0
    root.set_active(True)
    assert obj.a == 0
    ctx.ns.x = 5
    assert obj.a == 10
