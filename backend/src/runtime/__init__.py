"""
src/runtime/
Process-shared state.

Everything here exists because something in this system is correct only by
virtue of running in exactly one process, and would become incorrect -- not
merely slower -- with a second one.
"""
