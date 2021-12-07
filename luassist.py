# coding: utf-8

import os
import sys
import argparse
import re
from pathlib import Path
from subprocess import Popen, PIPE

def findConfigFile(path):
    pf = path.joinpath('.luacheckrc')
    if pf.is_file():
        return pf
    if path.parent == path:
        return None
    return findConfigFile(path.parent)

def findRequireInsertPos(lines):
    pos = 0
    mode = 'INIT'
    for cursor, line in enumerate(lines):
        if mode == 'INIT':
            if line.startswith('--'):
                pos = cursor + 1
            elif re.match(r'^\s*local\s+M\s+=\s+{\s*}\s*$', line):
                pos = cursor + 1
            elif re.match(r'^local\s+\w+\s*=\s*require\b.*$', line):
                pos = cursor + 1
                mode = 'HEAD_REQUIRE_FOUND'
            else:
                pass
        elif mode == 'HEAD_REQUIRE_FOUND':
            if line.startswith('--'):
                pos = cursor + 1
            elif re.match(r'^local\s+\w+\s*=\s*require\b.*$', line):
                pos = cursor + 1
            else:
                break
        else:
            raise Exception(f'unknown mode: {mode}')
    return pos

def insertRequire(lines, sys_name):
    insert_pos = findRequireInsertPos(lines)
    lines.insert(insert_pos, f'local {sys_name} = require \'game.sys.{sys_name}\'\n')

parser = argparse.ArgumentParser()
parser.add_argument('src_file')
args = parser.parse_args()

src_path = Path(args.src_file)
src_dir = src_path.parent
config_path = findConfigFile(src_dir)

need_require = []

proc = Popen(['luacheck', '-q', '--config', config_path, src_path], stdout=PIPE)
while True:
    line = proc.stdout.readline()
    if not line:
        break
    m = re.match(r'^\s+[\w:\\\.]+:\d+:\d+:\s*(.*)$', line.decode('utf-8'))
    if m:
        msg = m.group(1)
        mm = re.match(r'accessing undefined variable \'(S[A-Z]\w+)\'', msg)
        if mm:
            sys_name = mm.group(1)
            need_require.append(sys_name)

lines = []
with open(src_path, 'r', encoding='utf-8') as f:
    for line in f.readlines():
        lines.append(line)

required = set()
for sys_name in need_require:
    if sys_name in required: continue
    required.add(sys_name)
    insertRequire(lines, sys_name)

sys.stdout.writelines(lines)
