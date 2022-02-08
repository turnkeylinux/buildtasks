#!/usr/bin/python3

"""Quick and dirty test to check that all files import cleanly."""

import importlib
import sys

modules = ['conf', 'ebs', 'ebs_bundle', 'ebs_publish', 'ebs_register',
           'ebs_share', 'ec2_copy', 'utils']

for module in modules:
    print(f'testing import of {module}')
    temp_module = importlib.import_module(module)
    callables = []
    for item in dir(temp_module):
        if not item.startswith('__'):
            callables.append(item)
    print(f'callables: {callables}')
    # now deport module
    print('removing...')
    del sys.modules[module]
    del temp_module
