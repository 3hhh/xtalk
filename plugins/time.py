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
import time

from datetime import datetime
from collections import deque

from rtmidi.midiutil import open_midiport

from plugins import XtalkPlugin
from plugins import is_note
from plugins import is_note_on

class XtalkPlugin_time(XtalkPlugin):
    '''
    Checks incoming MIDI notes against a reference click for correct timing.
    If the time is off, an error MIDI note is sent to the reference click output.
    This is intended for practice purposes.

    If no reference click is provided or the reference click remains silent for a long time,
    the plugin has no effect.

    The reference click and error notes are sent to their own output port.

    Requires a high precision OS clock and support for virtual MIDI ports
    (both usually not available on Windows).
    '''

    # configuration variables: use the config.json config file to set them

    # set: MIDI notes to start/stop checking the time (the plugin starts in enabled state)
    CONTROL = ()

    # name of the input MIDI client to open for the reference click
    CLIENT = 'time'

    # delay of the reference click in ms
    # The algorithm can at most respect this many ms of future click notes. Therefore it
    # should be large enough to cover all possible gaps in the click and small enough in
    # order not to affect the algorithmic and musical performance.
    DELAY = 3000

    # which of the reference click notes to play
    # 0 = none
    # 1 = every, 2 = every 2nd and so on
    PLAY_INTERVAL = 1

    # Accept this many percent offset from the reference click as correct MIDI note.
    ACCEPT_RANGE = 30

    # Maximum difference in ms from the reference click to accept. Use a negative value to disable the maximum.
    MAX_DIFF = 100

    # MIDI note to play, if the incoming MIDI note was played too early, i.e. ahead of the reference click.
    ERROR_EARLY = 1

    # MIDI note to play, if the incoming MIDI note was played too late, i.e. after of the reference click.
    ERROR_LATE = 2

    # Velocity of emitted error indicator MIDI notes. A negative value causes the velocity of the original note to be used.
    ERROR_VELOCITY = 127

    # Whether to drop erroneous MIDI notes. An additional error note will always be sent out.
    DROP = False

    # Calibration time in ms to subtract in case there are further unknown delays to respect.
    CALIBRATION = 0

    # Whether or not to use automatic calibration.
    AUTO_CALIBRATION = True

    # File to write success statistics to (empty = disable stats).
    STATS_FILE = ''

    # Time in seconds after which success statistics are written to the STATS_FILE.
    STATS_INTERVAL = 5

    # Duration in seconds for which to consider past statistics.
    STATS_DURATION = 600

    # How many missed hits to show in the stats.
    STATS_SHOW_MISSED = 20

    # set: MIDI notes to control the incoming click track
    # on 0 occurrences (default): The click track is passed to the click track output.
    # on 1 occurrence           : Replace incoming click MIDI notes with the CLICK_REPLACE MIDI note. This can be used to make an accentuated MIDI click non-accentuated.
    #                             To replace MIDI notes of the main MIDI channel, please use the `replace` plugin instead.
    # on 2 occurrences          : Stop outputting the click track and any error notes.
    CLICK_CONTROL = ()

    # All incoming time/click MIDI notes will be replaced by this MIDI note, if replacing was enabled (i.e. CLICK_CONTROL was seen before).
    CLICK_REPLACE = -1

    def send_click(self, msg):
        if self.click_mode == 2: #we shouldn't send anything
            return

        if self.click_mode == 1 and self.CLICK_REPLACE >= 0 and self.CLICK_REPLACE < 128 and is_note(msg):
            msg[1] = self.CLICK_REPLACE

        #self.debug(f'sending click: {msg}')
        self.oport.send_message(msg)

    async def read_click(self, tup):
        # on received reference note:
        # 1. if note on: store in search buffer with exact time
        # 2. playback (optional) after self.DELAY ms
        # 3. removal from buffer after another self.DELAY ms
        msg = tup[0]

        if msg:
            is_on = is_note_on(msg)
            if is_on:
                #self.debug(f'adding to the buffer: {msg}')
                now = time.time_ns()
                #add it to the buffer ("future")
                self.buffer.append((now, msg))

            if self.PLAY_INTERVAL > 0:
                #send it after self.DELAY ms
                await asyncio.sleep(self.DELAY / 1000)

                if is_on:
                    self.index = ( self.index + 1 ) % self.PLAY_INTERVAL
                    if self.index == 0:
                        self.send_click(msg)
                else:
                    self.send_click(msg)

            #keep it in the buffer for 2 * self.DELAY ms ("past")
            if is_on:
                await asyncio.sleep(self.DELAY / 1000)

                self.buffer.pop(0)
                #self.debug(f'removing from the buffer: {msg}')

    def read_callback(self, tup, data=None):
        if self.loop is None:
            return
        #NOTE: we're running in the thread of the caller (no asyncio loop here)
        #https://raspberrypi.stackexchange.com/questions/54514/implement-a-gpio-function-with-a-callback-calling-a-asyncio-method
        if tup:
            self.loop.call_soon_threadsafe(asyncio.create_task, self.read_click(tup))

    def __init__(self, config=None, args=None):
        super().__init__(config=config, args=args)

        self.enabled = True
        self.click_mode = 0 #see the CLICK_CONTROL doc
        self.buffer = [] #(time, msg) buffer for note on events
        self.index = -1
        self.loop = None #asyncio event loop, will be initialized late
        self.calib = 0 #current calibration value for automatic calibration
        self.calib_update_cnt = 0

        if config:
            self.CONTROL = set(config.get('control', self.CONTROL))
            self.CLIENT = config.get('client', self.CLIENT)
            self.DELAY = int(config.get('delay', self.DELAY))
            self.PLAY_INTERVAL = int(config.get('play_interval', self.PLAY_INTERVAL))
            self.ACCEPT_RANGE = int(config.get('accept_range', self.ACCEPT_RANGE))
            self.MAX_DIFF = int(config.get('max_diff', self.MAX_DIFF))
            self.ERROR_EARLY = int(config.get('error_early', self.ERROR_EARLY))
            self.ERROR_LATE = int(config.get('error_late', self.ERROR_LATE))
            self.ERROR_VELOCITY = int(config.get('error_velocity', self.ERROR_VELOCITY))
            self.DROP = bool(config.get('drop', self.DROP))
            self.CALIBRATION = int(config.get('calibration', self.CALIBRATION))
            self.AUTO_CALIBRATION = bool(config.get('auto_calibration', self.AUTO_CALIBRATION))
            self.STATS_FILE = config.get('stats_file', self.STATS_FILE)
            self.STATS_INTERVAL = int(config.get('stats_interval', self.STATS_INTERVAL))
            self.STATS_DURATION = int(config.get('stats_duration', self.STATS_DURATION))
            self.STATS_SHOW_MISSED = int(config.get('stats_show_missed', self.STATS_SHOW_MISSED))
            self.CLICK_CONTROL = set(config.get('click_control', self.CLICK_CONTROL))
            self.CLICK_REPLACE = int(config.get('click_replace', self.CLICK_REPLACE))

            #some sanitization (we let most fail later though)
            self.STATS_INTERVAL = max(self.STATS_INTERVAL, 1)
            self.STATS_DURATION = max(self.STATS_DURATION, 1)

        #init stats
        self.stats_task = None
        self.stats_hits = 0
        self.stats_hits_last = 0
        self.stats_late = 0
        self.stats_early = 0
        self.stats_late_last = 0
        self.stats_early_last = 0
        self.stats_missed_notes = {} #note --> count of misses
        self.stats_missed_buf = deque(maxlen=self.STATS_SHOW_MISSED) #buffer for the last misses

        # open the reference click MIDI input & output port
        self.iport, _name = open_midiport(port=None, type_='input', client_name=self.CLIENT, api=args.api, port_name='input', use_virtual=True, interactive=False)
        self.iport.set_callback(self.read_callback)
        self.oport, _name = open_midiport(port=None, type_='output', client_name=self.CLIENT, api=args.api, port_name='output', use_virtual=True, interactive=False)

    #get the time of the closest neighbour to the element with the given index in self.buffer (time wise)
    def get_neighbour_time(self, index):
        prv = None
        nxt = None
        itime = self.buffer[index][0]
        if index > 0:
            prv = self.buffer[index-1][0]
        if index + 1 < len(self.buffer):
            nxt = self.buffer[index+1][0]

        if not prv and not nxt:
            return None
        if prv and not nxt:
            return prv
        if not prv and nxt:
            return nxt

        pdiff = abs(prv - itime)
        ndiff = abs(nxt - itime)
        if pdiff < ndiff:
            return prv
        return nxt

    #get the index of the element in the reference click buffer closest to the given reference time
    def get_closest(self, ref):
        ret = 0
        min_diff = -1
        for i, el in enumerate(self.buffer):
            cur = el[0]
            diff = abs(cur - ref)
            if min_diff < 0 or diff < min_diff:
                min_diff = diff
                ret = i
        return ret

    def send_error(self, msg, diff):
        if self.click_mode == 2: #we shouldn't send anything
            return

        velocity = self.ERROR_VELOCITY

        if velocity < 0 or velocity > 127:
            velocity = msg[2]

        if diff > 0:
            note = self.ERROR_LATE
        else:
            note = self.ERROR_EARLY

        ret = [0x9f, note, velocity] #0x9f = note on on channel 16 (we use a channel != 1 to make filtering more easy)
        self.debug(f'error note on for {msg}: {ret} (diff: {diff})')
        self.oport.send_message(ret)
        ret = [0x8f, note, 0]
        self.debug(f'error note off for {msg}: {ret}')
        self.oport.send_message(ret)

    #returns True, if the timing in the current moment is OK; also returns the actual time difference in ns to the reference click
    def check_time(self, msg):
        cnow = time.time_ns() - ( self.DELAY + self.args.delay + self.CALIBRATION ) * 1000000 - self.calib #we need to subtract self.DELAY as the player will hear the click that many ms later and play to it as reference; the same applies to self.args.delay
        closest_ind = self.get_closest(cnow)

        ntime = self.get_neighbour_time(closest_ind)
        if ntime is None:
            self.warn('Could not find a neighbour in the reference click. You may want to increase the delay parameter.')
            return (True, 0)

        diff = cnow - self.buffer[closest_ind][0]
        acceptable_diff = abs(self.buffer[closest_ind][0] - ntime) * self.ACCEPT_RANGE / 100
        max_diff = self.MAX_DIFF * 1000000
        if self.MAX_DIFF >= 0 and acceptable_diff > max_diff:
            acceptable_diff = max_diff
        self.debug(f'check_time for {msg} at {cnow}: diff = {diff}, acceptable_diff = {acceptable_diff}, closest: {self.buffer[closest_ind]}, calib: {self.calib}')

        ret = abs(diff) <= acceptable_diff
        #update the automatic calibration on successful time matches
        if ret and self.AUTO_CALIBRATION and self.calib_update_cnt < 100:
            #compute a cumulative average
            self.calib = ( diff + self.calib_update_cnt * self.calib ) / ( self.calib_update_cnt + 1 )
            self.calib = int(self.calib)
            self.calib_update_cnt += 1

        return (ret, diff)

    def update_stats(self, msg, time_ok, time_diff):
        #self.debug(f'Updating stats for {msg}...')
        note = msg[1]

        if time_ok:
            self.stats_hits += 1
            self.stats_hits_last += 1
        else:
            self.stats_missed_notes[note] = self.stats_missed_notes.get(note, 0) + 1
            now = time.time()
            self.stats_missed_buf.append((now, note, time_diff))

            if time_diff > 0:
                self.stats_late += 1
                self.stats_late_last += 1
            else:
                self.stats_early += 1
                self.stats_early_last += 1

        asyncio.create_task(self.remove_stats_later(msg, time_ok, time_diff))

    async def remove_stats_later(self, msg, time_ok, time_diff):
        await asyncio.sleep(self.STATS_DURATION)
        note = msg[1]
        #self.debug(f'Removing old stats for {msg}...')

        if time_ok:
            self.stats_hits_last -= 1
        else:
            self.stats_missed_notes[note] -= 1

            if time_diff > 0:
                self.stats_late_last -= 1
            else:
                self.stats_early_last -= 1

    def get_most_missed_note(self):
        ret_note = None
        ret_cnt = 0

        for note, cnt in self.stats_missed_notes.items():
            if cnt > ret_cnt:
                ret_note = note
                ret_cnt = cnt

        return (ret_note, ret_cnt)

    def write_stats(self):
        #file writing may block, so this function MUST be delegated to a separate thread
        with open(self.STATS_FILE, 'w', encoding='utf-8') as sfile:
            while True:
                time.sleep(self.STATS_INTERVAL)
                self.debug(f'Writing stats to {self.STATS_FILE}...')

                cnt = self.stats_hits + self.stats_early + self.stats_late
                if cnt == 0:
                    cnt = 1
                cnt_last = self.stats_hits_last + self.stats_early_last + self.stats_late_last
                if cnt_last == 0:
                    cnt_last = 1
                cnt_missed_last = self.stats_early_last + self.stats_late_last
                if cnt_missed_last == 0:
                    cnt_missed_last = 1

                perc_hits = self.stats_hits / cnt
                perc_early = self.stats_early / cnt
                perc_late = self.stats_late / cnt
                perc_hits_last = self.stats_hits_last / cnt_last
                perc_early_last = self.stats_early_last / cnt_last
                perc_late_last = self.stats_late_last / cnt_last
                most_missed_note, most_missed_cnt = self.get_most_missed_note()
                perc_most_missed = most_missed_cnt / cnt_missed_last

                sfile.write(f'\nHits (since start): {self.stats_hits}/{cnt} ({perc_hits:.1%})\n')
                sfile.write(f'Early (since start): {self.stats_early}/{cnt} ({perc_early:.1%})\n')
                sfile.write(f'Late (since start): {self.stats_late}/{cnt} ({perc_late:.1%})\n\n')

                sfile.write(f'Hits ({self.STATS_DURATION} seconds): {self.stats_hits_last}/{cnt_last} ({perc_hits_last:.1%})\n')
                sfile.write(f'Early ({self.STATS_DURATION} seconds): {self.stats_early_last}/{cnt_last} ({perc_early_last:.1%})\n')
                sfile.write(f'Late ({self.STATS_DURATION} seconds): {self.stats_late_last}/{cnt_last} ({perc_late_last:.1%})\n\n')

                sfile.write(f'Most missed note ({self.STATS_DURATION} seconds): {most_missed_note} ({most_missed_cnt}/{cnt_missed_last} times = {perc_most_missed:.1%})\n\n')

                if self.AUTO_CALIBRATION:
                    calib = self.calib / 1000000
                    sfile.write(f'Calibration value: {calib:.1f}ms\n\n')

                if self.STATS_SHOW_MISSED > 0:
                    sfile.write('Last missed notes:\n')
                    for unix_time, note, time_diff in reversed(self.stats_missed_buf):
                        ts = datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d %H:%M:%S")
                        diff = time_diff / 1000000
                        if time_diff > 0:
                            error = "late"
                        else:
                            error = "early"
                        sfile.write(f'{ts} note {note}: {error} ({diff:.0f}ms)\n')
                    sfile.write('\n\n')

                sfile.flush()
                sfile.seek(0)

    async def process(self, msg):
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
            if self.STATS_FILE:
                self.stats_task = asyncio.create_task(asyncio.to_thread(self.write_stats))
                self.stats_task.add_done_callback(lambda task: task.result()) #make sure to print any exceptions coming from the thread

        # on received input note:
        # 1. check against reference notes in search buffer
        # 2. if match: play, else: play error
        if is_note_on(msg):
            note = msg[1]
            if note in self.CONTROL:
                self.enabled = not self.enabled
                self.debug(f'toggle enabled status: {msg}, new status: {self.enabled}')
            elif note in self.CLICK_CONTROL:
                self.click_mode = ( self.click_mode + 1 ) % 3
                if self.click_mode == 1 and ( self.CLICK_REPLACE < 0 or self.CLICK_REPLACE >= 128 ): #skip mode 1, if it has no valid config
                    self.click_mode = 2
                self.debug(f'click mode change: {msg}, new mode: {self.click_mode}')
            elif self.enabled and len(self.buffer) > 0:
                time_ok, time_diff = self.check_time(msg)

                if self.STATS_FILE:
                    self.update_stats(msg, time_ok, time_diff)

                if not time_ok:
                    self.send_error(msg, time_diff)
                    if self.DROP:
                        return
        yield msg
