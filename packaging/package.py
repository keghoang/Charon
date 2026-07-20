# -*- coding: utf-8 -*-

name = 'charon'

version = '1.3.0'

description = 'Nuke workflow panel and ComfyUI execution bridge'

authors = ['Kien']

tools = []

requires = [
    '~nuke-15+'
]

def commands():
    # env.PYTHONPATH.append(r"\\abadal\globalprefs\3d_wip\Scripts\charon_beta")
    # Add the charon path to the python path
    env.PYTHONPATH.append("{root}")

timestamp = 1759440856

format_version = 2
