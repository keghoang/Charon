# -*- coding: utf-8 -*-

name = 'charon'

version = '1.3.0'

description = 'Script Launcher for Nuke and Maya'

authors = ['Kien']

tools = []

requires = [
    '~maya-2022+',
    '~nuke-15+'
]

def commands():
    # env.PYTHONPATH.append(r"\\abadal\globalprefs\3d_wip\Scripts\charon_beta")
    # Add the charon path to the python path
    env.PYTHONPATH.append("{root}")

timestamp = 1759440856

format_version = 2
