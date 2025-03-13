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
from plugins import XtalkPluginException
from plugins import is_note_on
from plugins import get_epoch_now
from plugins import MIDI_AFTERTOUCH

def assertHasDefault(dictionary):
    try:
        int(dictionary["default"])
    except (KeyError, ValueError) as e:
        raise XtalkPluginException(e) from e

class XtalkPlugin_choke(XtalkPlugin):
    '''
    E-drum cymbal chokes from rim switches sometimes come in as low volume
    MIDI notes - probably because the piezo detects the touch.

    So this plugin triggers a choke of a previous loud cymbal hit on incoming
    low volume MIDI notes and suppresses those low volume notes.

    This way drummers can use low volume hits or touches (e.g. moving
    the cymbal upwards from below) as chokes instead of their rim switch. In fact
    this even adds choke support to cymbals without hardware rim switch.

    Make sure to use a low mask time with the respective MIDI notes to
    support quick choking.

    xtalk fix for https://github.com/corrados/edrumulus/issues/111
    '''

    # configuration variables: use the config.json config file to set them

    # map: str note value of a low volume choke indicator --> set of int notes to disable (may be empty)
    CHOKE = { }

    # minimum velocity of a choke note, map: note --> value, "default" as fallback
    CHOKE_MIN = { "default": 0 }

    # maximum velocity of a choke note
    CHOKE_MAX = { "default": 20 }

    # number of times a choke note must be seen
    CHOKE_CNT = { "default": 1 }

    # minimum velocity of a cymbal hit to consider it worth choking
    CYMBAL_MIN = { "default": 50 }

    # time in ms during which to allow chokes
    TIMEOUT = 3000

    def __init__(self, config=None, debug=False):
        super().__init__(config=config, debug=debug)

        self.last = None #last cymbal message, if any was seen lately
        self.last_time = None #timestamp of the last cymbal message
        self.last_choked = False #whether the last cymbal message was choked or not
        self.choke_cnt = 0 #number of chokes recently seen
        self.notes = set() #cymbal notes for quick access

        if config:
            self.CHOKE = dict(config.get('choke', self.CHOKE))
            self.CHOKE_MIN = dict(config.get('choke_min', self.CHOKE_MIN))
            self.CHOKE_MAX = dict(config.get('choke_max', self.CHOKE_MAX))
            self.CHOKE_CNT = dict(config.get('choke_cnt', self.CHOKE_CNT))
            self.CYMBAL_MIN = dict(config.get('cymbal_min', self.CYMBAL_MIN))
            self.TIMEOUT = int(config.get('timeout', self.TIMEOUT))
            assertHasDefault(self.CHOKE_MIN)
            assertHasDefault(self.CHOKE_MAX)
            assertHasDefault(self.CHOKE_CNT)
            assertHasDefault(self.CYMBAL_MIN)

        for val in self.CHOKE.values():
            self.notes = self.notes.union(set(val))

    def _create_choke(self, msg):
        channel = msg[0] & 0x0F
        note = msg[1]

        # aftertouch with full pressure, then go to zero
        yield [ MIDI_AFTERTOUCH | channel, note, 127 ]
        yield [ MIDI_AFTERTOUCH | channel, note, 0 ]

    def clear(self):
        self.last = None
        self.last_time = None
        self.choke_cnt = 0
        self.last_choked = False

    async def process(self, msg):
        if is_note_on(msg):
            note = msg[1]
            note_str = str(note)
            velocity = msg[2]
            now = get_epoch_now()

            choke_min = self.CHOKE_MIN.get(note_str, self.CHOKE_MIN["default"])
            choke_max = self.CHOKE_MAX.get(note_str, self.CHOKE_MAX["default"])
            cymbal_min = self.CYMBAL_MIN.get(note_str, self.CYMBAL_MIN["default"])
            choke_cnt = self.CHOKE_CNT.get(note_str, self.CHOKE_CNT["default"])

            if self.last_time and (self.last_time - now) > self.TIMEOUT:
                self.debug('choke timeout reached')
                self.clear()

            # check for choke note
            if self.last and choke_max >= velocity >= choke_min and self.last[1] in self.CHOKE.get(str(note), {}):
                self.debug(f'choke note: {msg}, choke_min: {choke_min}, choke_max: {choke_max}, choke_cnt: {choke_cnt}, cymbal_min: {cymbal_min}')
                self.choke_cnt += 1
                if self.choke_cnt >= choke_cnt:
                    # make sure that chokes are only emitted once (otherwise drumgizmo will go to aftertouch 127 for a short time on a second choke note)
                    if not self.last_choked:
                        for choke in self._create_choke(self.last):
                            yield choke
                        self.last_choked = True

                #suppress the choke note (multiple may occur)
                return

            # check for regular cymbal hit
            if note in self.notes:
                self.clear()

                if velocity >= cymbal_min:
                    self.debug(f'regular cymbal hit: {msg}')
                    self.last = msg
                    self.last_time = now
                    self.last_choked = False

        yield msg
