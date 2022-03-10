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

def findSysDefFile(path):
    pf = path.joinpath('data', 'sys_def.lua')
    if pf.is_file():
        return pf
    if path.parent == path:
        return None
    return findSysDefFile(path.parent)

def findRequireInsertPos(lines):
    pos = 0
    mode = 'INIT'
    last_require_line = None
    for cursor, line in enumerate(lines):
        if mode == 'INIT':
            if line.startswith('--'):
                pos = cursor + 1
            elif re.match(r'^\s*local\s+M\s+=\s+{\s*}\s*$', line):
                pos = cursor + 1
            elif re.match(r'^local\s+\w+\s*=\s*require\b.*$', line):
                last_require_line = cursor
                pos = cursor + 1
                mode = 'HEAD_REQUIRE_FOUND'
            else:
                pass
        elif mode == 'HEAD_REQUIRE_FOUND':
            if line.startswith('--'):
                pos = cursor + 1
            elif re.match(r'^local\s+\w+\s*=\s*require\b.*$', line):
                last_require_line = cursor
                pos = cursor + 1
            else:
                break
        else:
            raise Exception(f'unknown mode: {mode}')
    if last_require_line != None:
        return last_require_line + 1
    else:
        return pos

def insertRequire(lines, sys_name):
    insert_pos = findRequireInsertPos(lines)
    lines.insert(insert_pos, f'local {sys_name} = require \'game.sys.{sys_name}\'\n')

def analyzeForRequires(src_path):
    need_require = []

    src_dir = src_path.parent
    config_path = findConfigFile(src_dir)

    proc = Popen(['luacheck', '-q', '--no-color', '--config', config_path, src_path], stdout=PIPE)
    while True:
        line = proc.stdout.readline()
        if not line:
            break

        m = re.match(r'^\s+[\w:/\\\._-]+:\d+:\d+:\s*(.*)$', line.decode('utf-8'))
        if m:
            msg = m.group(1)
            mm = re.match(r'accessing undefined variable \'(S[A-Z]\w+)\'', msg)
            if mm:
                sys_name = mm.group(1)
                need_require.append(sys_name)

    return need_require

def analyzeForSysDef(lines):
    flags = set()
    for line in lines:
        m = re.match(r'^function\s+M\.(\w+)\s*\(.*\)\s*$', line)
        if m:
            funcname = m.group(1)
            if funcname in {'on_sys_awake', 'on_sys_start', 'update'}:
                flags.add(funcname)
    return flags

def handleRequires(lines, need_require):
    required = set()
    for sys_name in need_require:
        if sys_name in required: continue
        required.add(sys_name)
        insertRequire(lines, sys_name)

def handleFlags(sys_def_path, flags, sys_name):
    lines = []

    with open(sys_def_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            lines.append(line)

    cursor = 0
    sys_awake_mode = 'INIT'
    sys_start_mode = 'INIT'
    update_mode = 'INIT'
    update_insert_pos = 0
    dirty = False
    while cursor < len(lines):
        line = lines[cursor]
        if 'on_sys_awake' in flags:
            if sys_awake_mode == 'INIT' or sys_awake_mode == 'MATCHING':
                m = re.match(r'^\s*{\s*\'(\w+)\'\s*,\s*\'on_sys_awake\'\s*}\s*,\s*$', line)
                if m:
                    if m.group(1) == sys_name:
                        sys_awake_mode = 'DONE'
                    else:
                        sys_awake_mode = 'MATCHING'
                elif sys_awake_mode == 'MATCHING':
                    padding = ' ' * (32 - len(sys_name) - 5 - 8)
                    lines.insert(cursor, f'        {{ \'{sys_name}\',{padding}\'on_sys_awake\' }},\n')
                    cursor += 1
                    dirty = True
                    sys_awake_mode = 'DONE'
        if 'on_sys_start' in flags:
            if sys_start_mode == 'INIT' or sys_start_mode == 'MATCHING':
                m = re.match(r'^\s*{\s*\'(\w+)\'\s*,\s*\'on_sys_start\'\s*}\s*,\s*$', line)
                if m:
                    if m.group(1) == sys_name:
                        sys_start_mode = 'DONE'
                    else:
                        sys_start_mode = 'MATCHING'
                elif sys_start_mode == 'MATCHING':
                    padding = ' ' * (32 - len(sys_name) - 5 - 8)
                    lines.insert(cursor, f'        {{ \'{sys_name}\',{padding}\'on_sys_start\' }},\n')
                    dirty = True
                    cursor += 1
                    sys_start_mode = 'DONE'
        if 'update' in flags:
            if update_mode == 'INIT':
                m = re.match(r'^\s*update\s*=\s*{\s*$', line)
                if m:
                    update_insert_pos = cursor + 1
                    update_mode = 'MATCHING'
            elif update_mode == 'MATCHING':

                def matchUpdateEntry(line):
                    m = re.match(r'^\s*$', line)
                    if m:
                        return 'MATCHING'

                    m = re.match(r'^\s*--.*$', line)
                    if m:
                        return 'MATCHING'

                    m = re.match(r'^\s*{\s*\'(\w+)\',\s*\'\w+\',?\s*(\'\w+\',?\s*)?},\s*$', line)
                    if m:
                        if m.group(1) == sys_name:
                            return 'DONE'
                        return 'MATCHING'

                    m = re.match(r'^\s*{\s*sys=\'(\w+)\',\s*func=\'\w+\',?\s*(comp=\'\w+\'\s*)?},\s*$', line)
                    if m:
                        if m.group(1) == sys_name:
                            return 'DONE'
                        return 'MATCHING'

                    if re.match(r'^\s*},\s*$', line):
                        return 'INSERT'

                    raise Exception(f'bad update entry line: {line}')

                update_mode = matchUpdateEntry(line)
                if update_mode == 'INSERT':
                    update_mode = 'DONE'
                    padding = ' ' * (32 - len(sys_name) - 9 - 8)
                    lines.insert(update_insert_pos, f'        {{ sys=\'{sys_name}\',{padding}func=\'update\' }},\n')
                    dirty = True
                    cursor += 1
        cursor += 1

    if dirty:
        with open(sys_def_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(''.join(lines))

def getSysName(path):
    m = re.match(r'.*[\\/]game[\\/]sys[\\/](S\w+)\.lua$', path)
    if m:
        return m.group(1)
    else:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('src_file')
    args = parser.parse_args()

    src_path = Path(args.src_file)
    sys_def_path = findSysDefFile(src_path)
    sys_name = getSysName(args.src_file)

    need_require = analyzeForRequires(src_path)

    lines = []
    with open(src_path, 'r', encoding='utf-8') as f:
        for line in f.readlines():
            lines.append(line)

    if need_require:
        handleRequires(lines, need_require)

    if sys_def_path and sys_name:
        flags = analyzeForSysDef(lines)
        if flags:
            handleFlags(sys_def_path, flags, sys_name)

    sys.stdout.buffer.write(''.join(lines).encode('utf-8'))

if __name__ == '__main__':
    main()

