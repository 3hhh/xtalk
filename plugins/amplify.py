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

from plugins import XtalkPlugin
from plugins import is_note_on

class XtalkPlugin_amplify(XtalkPlugin):
    '''
    Linear amplification of the velocity for MIDI notes.
    '''

    # configuration variables: use the config.json config file to set them

    # map: MIDI note --> dict of "multiply" (percent) and "add" factors; the new velocity will be: v_new = v_old * multiply + add
    AMPLIFY = { }

    def __init__(self, config=None, args=None):
        super().__init__(config=config, args=args)

        if config:
            self.AMPLIFY = dict(config.get('amplify', self.AMPLIFY))

        for val in self.AMPLIFY.values():
            try:
                int(val.get('multiply',1))
                int(val.get('add',0))
            except (KeyError, ValueError, NameError) as e:
                raise ValueError(f'The amplification values must be specified as dict, but this looks different: {val}') from e

    async def process(self, msg):
        if is_note_on(msg):
            note = str(msg[1])
            velocity = msg[2]

            if self.AMPLIFY.get(note):
                mul = self.AMPLIFY[note].get('multiply', 100)/100
                add = self.AMPLIFY[note].get('add', 0)
                nvelo = int(velocity * mul + add)
                if nvelo < 0:
                    nvelo = 0
                elif nvelo > 127:
                    nvelo = 127
                self.debug(f'{msg}: mul: {mul}, add: {add} --> new velocity: {nvelo}')
                msg[2] = nvelo

        yield msg
