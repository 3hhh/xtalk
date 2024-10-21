#!/usr/bin/env python3
# -*- encoding: utf8 -*-
#
# Copyright (C) 2024
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
from plugins import MIDI_AFTERTOUCH

class XtalkPlugin_choke(XtalkPlugin):
    '''
    E-drum cymbal chokes from rim switches sometimes come in as low volume
    MIDI notes.

    So this plugin triggers a choke of a previous loud cymbal hit on incoming
    low volume MIDI notes and suppresses those low volume notes.

    Also, this can enable drummers to use low volume hits or touches as chokes
    instead of their rim switch.

    xtalk fix for https://github.com/corrados/edrumulus/issues/111
    '''

    # configuration variables: use the config.json config file to set them

    # map: str note value of a low volume choke indicator --> set of int notes to disable (may be empty)
    CHOKE = { }

    # minimum velocity of a choke note
    CHOKE_MIN = 0

    # maximum velocity of a choke note
    CHOKE_MAX = 20

    # minimum velocity of a cymbal hit to consider it worth choking
    CYMBAL_MIN = 50

    def __init__(self, config=None, debug=False):
        super().__init__(config=config, debug=debug)

        self.last = None #last cymbal message, if any was seen lately
        self.last_choked = False #whether the last cymbal message was choked or not
        self.notes = set() #cymbal notes for quick access

        if config:
            self.CHOKE = dict(config.get('choke', self.CHOKE))
            self.CHOKE_MIN = int(config.get('choke_min', self.CHOKE_MIN))
            self.CHOKE_MAX = int(config.get('choke_max', self.CHOKE_MAX))
            self.CYMBAL_MIN = int(config.get('cymbal_min', self.CYMBAL_MIN))

        for val in self.CHOKE.values():
            self.notes = self.notes.union(set(val))

    def _create_choke(self, msg):
        channel = msg[0] & 0x0F
        note = msg[1]

        # aftertouch with full pressure, then go to zero
        yield [ MIDI_AFTERTOUCH | channel, note, 127 ]
        yield [ MIDI_AFTERTOUCH | channel, note, 0 ]

    async def process(self, msg):
        if is_note_on(msg):
            note = msg[1]
            velocity = msg[2]

            # check for choke note
            if self.last and self.CHOKE_MAX >= velocity >= self.CHOKE_MIN and self.last[1] in self.CHOKE.get(str(note), {}):
                self.debug(f'choke note: {msg}')
                # make sure that chokes are only emitted once (otherwise drumgizmo will go to aftertouch 127 for a short time on a second choke note)
                if not self.last_choked:
                    for choke in self._create_choke(self.last):
                        yield choke
                    self.last_choked = True

                #suppress the choke note (multiple may occur)
                return

            # check for regular cymbal hit
            if note in self.notes:
                self.last = None #clear

                if velocity >= self.CYMBAL_MIN:
                    self.debug(f'regular cymbal hit: {msg}')
                    self.last = msg
                    self.last_choked = False

        yield msg
