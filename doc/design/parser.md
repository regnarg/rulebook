A Note on Extending the Python Grammar
--------------------------------------

Python uses a C parser generated at compile time from the grammar definition file
``Grammar/Grammar.txt``. This means that the parsing cannot be extended or modified
in any way at runtime.

See [our graph](py_gram_ext.pdf) for an overview of the parsing process and the APIs
available to access it.

This leaves several options as to extending the language:

(a) Modify the grammar and recompile Python, as described [here][1]. This is
    clearly unacceptable, as we want our solution to be a loadable module, usable
    together with any other modules that may be already installed for the system
    Python interpreter.

    We could, in theory, extract only the parser from the Python source tree
    and include a modified version with our module. That would still suffer
    from issues described in (b).

(b) Reimplement the whole parsing independently. There is at least one library
    that does so, in an extansible way: [EasyExtend][2]. This poses the issue
    that the Python grammar included with the library is used, which may be from
    a different Python version than the one currently installed, causing
    unexpected discrepancies. Also, keeping the parser up-to-date with upstream
    changes is a lot of unnecessary work, even when someone else does it for us
    (noone guaranteed that they will keep on doing so).

    [^1] It would suffice to reimplement the CST parsing step (which could be
    relatively cheap, perhaps reusing Python's ``Grammar.txt`` and a generic
    parsing engine) and feed the result to ``parser.compilest``. However, if
    for any reason we wanted to access the AST, we would either need a C extension
    module to call ``PyAST_FromNode`` or reimplement the whole CST-to-AST
    conversion rules (which would be perhaps even more annoying than the parsing
    itself), as there is no way of converting CST to AST in pure Python (see
    the graph).

(c) Somehow preprocess the input at either the source code or the token stream
    stages.

References
----------

  * [Eli Bendersky's website » Python internals: adding a new statement to Python][1]
  * [EasyExtend module][2]

[1]: http://eli.thegreenplace.net/2010/06/30/python-internals-adding-a-new-statement-to-python/
[2]: http://www.fiber-space.de/EasyExtend/doc/main/EasyExtend.html
