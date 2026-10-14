"""The terminal client: the program in a terminal window.

It talks to the running service over the same HTTP API the window uses and
keeps no logic of its own beside it. Nothing in here imports the service's
code, and nothing of the service imports this package.
"""
