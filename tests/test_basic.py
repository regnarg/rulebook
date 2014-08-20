from testlib import *



def test_assign():
    root,ctx = load_string('''
        y = x
    ''')
    ctx.ns.x = 5
    with raises(AttributeError):
        ctx.ns.y

    root.set_active(True)
    assert ctx.ns.y == 5
    ctx.ns.x = 42
    assert ctx.ns.y == 42

    root.set_active(False)
    ctx.ns.y = 12
    ctx.ns.x = 24
    assert ctx.ns.y == 12

def test_assign_lhs_change():
    root,ctx = load_string('''
       obj1.x = 0
       obj2.x = 0
       obj.x = 42 prio 5
    ''')
    obj1, obj2 = TestObj('obj1'), TestObj('obj2')
    # ctx.add_value((obj1, 'attr', 'x'), 0, 0, 'default')
    # ctx.add_value((obj2, 'attr', 'x'), 0, 0, 'default')
    ctx.ns.obj1 = obj1
    ctx.ns.obj2 = obj2
    ctx.ns.obj = obj1

    root.set_active(True)
    assert obj1.x == 42
    assert obj2.x == 0

    ctx.ns.obj = obj2
    assert obj2.x == 42
    assert obj1.x == 0


def test_prio_simple():
    root,ctx = load_string('''
        x = 100
        x = 200 prio -5
    ''')
    root.set_active(True)
    assert ctx.ns.x == 100

# def test_if():
#     root,ctx = load_string('''
#         b = False
#         if a:
#             b = True prio 10
#     ''')
#     ctx.ns.a = False
#
#     root.set_active(True)
#     assert ctx.ns.b == False
#
#     ctx.ns.a = True
#     assert ctx.ns.b == True
