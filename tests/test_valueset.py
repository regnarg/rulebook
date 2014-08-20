from testlib import *


def test_add_remove():
    ctx = Context()
    ctx.ns.obj = obj = TestObj('obj')
    target = (obj, 'attr', 'x')

    normal_id = ctx.add_value(target, 'normal', 0)
    assert obj.x == 'normal'

    high_id = ctx.add_value(target, 'high', 42)
    assert obj.x == 'high'

    ctx.remove_value(target, high_id)
    assert obj.x == 'normal'

    ctx.add_value(target, 'high2', 42, 'my_high')
    assert obj.x == 'high2'

    ctx.add_value(target, 'high3', 42, 'my_high')
    assert obj.x == 'high3'

    ctx.remove_value(target, 'my_high')
    assert obj.x == 'normal'

    ctx.add_value(target, 'low', -5)
    assert obj.x == 'normal'
    ctx.remove_value(target, normal_id)
    assert obj.x == 'low'
