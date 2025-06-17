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

from plugins import XtalkPlugin
from plugins import is_note_on
from plugins import get_epoch_now

class XtalkPlugin_replay(XtalkPlugin):
    '''
    Replay recorded MIDI notes / "MIDI looper".

    Requires a high precision OS clock (usually not available on Windows).
    '''

    # configuration variables: use the config.json config file to set them

    # set: MIDI notes to start/stop recording on; the record starts on the next MIDI note on
    RECORD = ()

    # set: MIDI notes to start/stop playing recorded notes on
    PLAY = ()

    # whether or not to loop recorded MIDI notes
    LOOP = True

    # whether to pass incoming notes
    PASS = True

    # whether or not the play note should also stop running records
    PLAY_STOPS_RECORD = True

    def __init__(self, config=None, debug=False):
        super().__init__(config=config, debug=debug)
        self.recording = False
        self.cache = []
        self.cache_last = None #timestamp of the last cache entry
        self.play_task = None #current play task
        self.ignore = False #ignore all notes for recording until the next note on

        if config:
            self.RECORD = set(config.get('record', self.RECORD))
            self.PLAY = set(config.get('play', self.PLAY))
            self.PASS = bool(config.get('pass', self.PASS))
            self.LOOP = bool(config.get('pass', self.LOOP))
            self.PLAY_STOPS_RECORD = bool(config.get('play_stops_record', self.PLAY_STOPS_RECORD))

    async def play(self):
        while True:
            if not self.cache:
                return
            for msg, diff in self.cache:
                self.debug(f'replaying: {msg}, wait time: {diff} ms')
                #NOTES:
                # - asyncio.sleep() method is not 100% accurate / depends on other running tasks
                # - usually asnyncio.sleep() is inaccurate by at least 1ms, i.e. it doesn't make sense to call it for anything below
                # - on Windows the default clock only has 15ms precision, which should be noticeable (1ns on Linux)
                if diff > 1:
                    await asyncio.sleep(diff/1000) #sleep expects seconds
                if msg:
                    self.send(msg)
            if not self.LOOP:
                return

    def is_playing(self):
        return self.play_task and not self.play_task.done()

    async def stop(self):
        if self.play_task:
            #stop
            self.debug('stopping playback')
            self.play_task.cancel()
            try:
                await self.play_task
            except asyncio.CancelledError:
                pass
            self.play_task = None

    async def toggle_play(self):
        if self.is_playing():
            await self.stop()
        else:
            #start playing
            self.debug(f'playing the cache: {self.cache}')
            self.play_task = asyncio.create_task(self.play())

    def add_to_cache(self, msg):
        now = get_epoch_now()
        if not self.cache_last:
            self.cache_last = now
        diff = now - self.cache_last
        self.cache.append((msg, diff))
        self.cache_last = now

    def clear_cache(self):
        self.cache.clear()
        self.cache_last = None

    async def process(self, msg):
        if is_note_on(msg):
            note = msg[1]
            if note in self.RECORD:
                self.recording = not self.recording
                self.debug(f'toggle recording status: {msg}, new status: {self.recording}')
                if self.recording:
                    await self.stop()
                    self.clear_cache()
                    self.ignore = True
                else:
                    if self.cache:
                        self.add_to_cache(None) #save the end timestamp for proper loops
            elif note in self.PLAY:
                self.debug(f'toggle play status: {msg}')
                if self.PLAY_STOPS_RECORD:
                    self.recording = False
                await self.toggle_play()
            else:
                self.ignore = False

        if self.recording and not self.ignore:
            self.debug(f'adding to the cache: {msg}')
            self.add_to_cache(msg)

        if self.PASS:
            yield msg
