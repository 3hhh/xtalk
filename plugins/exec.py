#!/usr/bin/env python3
# -*- encoding: utf8 -*-
#
# Copyright (C) 2025
#                   David Hobach <tripleh@hackingthe.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import asyncio
import subprocess
import sys
import traceback

from plugins import XtalkPlugin
from plugins import is_note
from plugins import is_note_on
from plugins import get_epoch_now

class XtalkPlugin_exec(XtalkPlugin):
    '''
    Execute external programs on a configurable set of MIDI notes.
    '''

    # configuration variables: use the config.json config file to set them

    # map: MIDI note --> [ command, arg 1, arg 2, ... ] array
    EXEC = { }

    # whether or not to pass matching MIDI notes to the output
    PASS = True

    # time in ms during which to suppress further program executions (negative = no suppression)
    SUPPRESS = -1

    # whether all notes should trigger program execution (False = MIDI note on messages only)
    ALL_NOTES = False

    def __init__(self, config=None, debug=False):
        super().__init__(config=config, debug=debug)

        self.suppression_cache = {}
        self.background_tasks = set()

        if config:
            self.EXEC = dict(config.get('exec', self.EXEC))
            self.PASS = bool(config.get('pass', self.PASS))
            self.SUPPRESS = int(config.get('suppress', self.SUPPRESS))
            self.ALL_NOTES = bool(config.get('all_notes', self.ALL_NOTES))

        for val in self.EXEC.values():
            try:
                for d in val:
                    _testing = d['command'][0]
            except (TypeError, KeyError, ValueError) as e:
                raise ValueError(f'The commands must be specified as in the example, but this looks different: {val}') from e

    async def execute_coro(self, command):
        try:
            proc = await asyncio.create_subprocess_exec(*command, stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr)
            ret = await proc.wait()
            if ret != 0:
                print(f'The command {command} returned a non-zero exit code {ret}.', file=sys.stderr)
        except Exception:
            traceback.print_exc()

    def execute(self, command):
        task = asyncio.create_task(self.execute_coro(command))
        #without this reference, tasks may be garbage collected, even if still running
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def process(self, msg):
        pass_msg = True

        if is_note(msg):
            note = msg[1]
            velocity = 0
            if is_note_on(msg):
                velocity = msg[2]

            to_exec = self.EXEC.get(str(note))
            if to_exec:
                if self.ALL_NOTES or is_note_on(msg):
                    last = self.suppression_cache.get(note)
                    now = get_epoch_now()

                    if last and ( now - last <= self.SUPPRESS ):
                        self.debug(f'execution of {to_exec} suppressed: {msg}')
                    else:
                        self.suppression_cache[note] = now
                        for ex in to_exec:
                            min_velocity = ex.get('min_velocity', 0)
                            if velocity >= min_velocity:
                                cmd = ex['command']
                                self.debug(f'executing: {cmd}')
                                self.execute(cmd)
                                break

                #NOTE: we intentionally also block note off or other related messages here with self.PASS = False - even if nothing was executed
                pass_msg = self.PASS

        if pass_msg:
            yield msg
        else:
            self.debug(f'suppressed: {msg}')
