#!/usr/bin/env python3
# -*- encoding: utf8 -*-
#
# Copyright (C) 2026
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

from pynput.keyboard import Key, KeyCode, Controller

from plugins import XtalkPlugin
from plugins import is_note
from plugins import is_note_on
from plugins import is_note_off

class XtalkPlugin_keyboard(XtalkPlugin):
    '''
    Enables you to use your MIDI device as PC keyboard.

    MIDI Note On events are translated to key down events, MIDI Note Off events to key up
    events.

    Also, multiple key strokes in a short period of time can be translated to other keys
    than a single key stroke.
    '''

    def __init__(self, config=None, args=None):
        super().__init__(config=config, args=args)

        #whether or not to pass input MIDI events
        self.pass_msg = False

        #time in ms to wait for a subsequent key stroke, if multiple key strokes have a different meaning
        self.repeat_timeout = 250

        #time in ms to delay any key stroke
        self.delay = 0

        #map: MIDI note --> array of key combinations to emulate on the first, second, ... key stroke/MIDI note; key combinations are arrays of either actual characters (e.g. "c") to press _or_ names of special characters such as "left", "f1" etc. (the complete list can be obtained from pynput)
        #self.mapping = {}

        #internal variant of self.mapping with actual pynput objects
        self._mapping = {}

        #global keyboard handle
        self.keyboard = Controller()

        #handle buffer for self.handle_note()
        self.hbuf = {}

        #map: MIDI note --> bool: was pressed recently
        self.pressed = {}

        if config:
            self.pass_msg = bool(config.get("pass", self.pass_msg))
            self.repeat_timeout = int(config.get("repeat-timeout", self.repeat_timeout))
            self.delay = int(config.get("delay", self.delay))
            mapping = dict(config.get('mapping', self._mapping))

            #init self._mapping
            for i in range(128):
                try:
                    self._mapping[i] = mapping[str(i)]
                except KeyError:
                    continue

                try:
                    for j, val in enumerate(self._mapping[i]):
                        for k, v in enumerate(val):
                            self._mapping[i][j][k] = self.translate_key(v)
                except (TypeError, KeyError, ValueError) as e:
                    raise ValueError(f'The key combinations must be specified as arrays of arrays of strings, but this looks different: {self._mapping[i]}') from e

    #translate the given key specified by a string to a pynput object
    def translate_key(self, key):
        if not key:
            raise ValueError('An empty key was specified.')

        if len(key) == 1:
            return KeyCode.from_char(key)

        #special character such as 'left'
        #NOTE: enums are essentially dicts
        return Key[key]

    #handle the given MIDI note, on is a bool indicating whether it was on or off
    async def handle_note(self, note, on):
        # algorithm:
        # a) if time to wait (further MIDI notes may mean something different):
        #    1. cancel any previous task via the handle for the note & on from the global buffer
        #    2. create a task to handle it later (after self.repeat_timeout)
        #    3. use note & on as index for the task handle and add it to a global buffer
        # b) if no time to wait: handle immediately
        if not self._mapping.get(note):
            return

        dkey = (note, on)
        previous = self.hbuf.get(dkey)
        count = 1
        if previous:
            count = previous['count'] + 1
            previous['task'].cancel()

        todo_count = len(self._mapping[note])
        keys = self._mapping[note][count-1]

        if count >= todo_count: #no time to wait
            await self.press_keys(note, on, keys)
        else: #we need to wait
            #update hbuf
            self.hbuf[dkey] = {
                'count': count,
                'task' : asyncio.create_task(self.press_keys_later(note, on, keys)),
            }

    async def press_keys_later(self, note, on, keys):
        try:
            await asyncio.sleep(self.repeat_timeout/1000)
            self.debug(f'press_keys_later({note}, {on}, {keys})')
            await self.press_keys(note, on, keys)
        except asyncio.CancelledError:
            return

    #press the keys corresponding to a note
    async def press_keys(self, note, on, keys):
        dkey = (note, on)

        #clean up
        del self.hbuf[dkey]

        #delay, if necessary
        if self.delay > 0:
            self.debug(f'delaying by {self.delay}ms for note {note}.')
            await asyncio.sleep(self.delay/1000)

        #emulate keys
        if on:
            self.debug(f'pressing for note {note}: {keys}')
            self.pressed[note] = True
            for key in keys:
                self.keyboard.press(key)
        else:
            if self.pressed.get(note):
                self.debug(f'releasing for note {note}: {keys}')
                self.pressed[note] = False
                for key in keys:
                    self.keyboard.release(key)

    async def process(self, msg):
        pass_msg = True

        if is_note(msg):
            note = msg[1]

            if self._mapping.get(note):
                pass_msg = self.pass_msg

                if is_note_on(msg):
                    await self.handle_note(note, True)
                elif is_note_off(msg):
                    await self.handle_note(note, False)

                self.debug(f'hbuf: {self.hbuf}')

        if pass_msg:
            yield msg
        else:
            self.debug(f'suppressed: {msg}')
