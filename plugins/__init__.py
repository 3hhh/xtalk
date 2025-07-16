#!/usr/bin/env python3
# -*- encoding: utf8 -*-
#
# Copyright (C) 2023
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

import time
from abc import ABC, abstractmethod

#constants
MIDI_NOTEON     = 0x90 #lower bytes must be ignored
MIDI_NOTEOFF    = 0x80 #lower bytes must be ignored
MIDI_AFTERTOUCH = 0xA0 #lower bytes must be ignored

def is_note_on(msg, strict=False):
    if strict:
        return ((msg[0] & 0xf0) ^ MIDI_NOTEON) == 0
    #according to the MIDI standard, note on with 0 velocity is a note off
    return is_note_on(msg, strict=True) and msg[2] > 0

def is_note_off(msg, strict=False):
    if strict:
        return ((msg[0] & 0xf0) ^ MIDI_NOTEOFF) == 0
    #according to the MIDI standard, note on with 0 velocity is a note off
    return is_note_off(msg, strict=True) or (is_note_on(msg, strict=True) and msg[2] == 0)

def is_note_aftertouch(msg):
    return ((msg[0] & 0xf0) ^ MIDI_AFTERTOUCH) == 0

def is_note_mod(msg):
    return is_note_off(msg) or is_note_aftertouch(msg)

def is_note(msg):
    return is_note_on(msg) or is_note_mod(msg)

def get_epoch_now():
    return time.time_ns()/1000000

class XtalkPluginException(Exception):
    ''' Base class for plugin exceptions. '''

class XtalkPluginAbortException(XtalkPluginException):
    ''' Thrown when the MIDI connection is meant to be aborted. '''

class _XtalkPlugin(ABC):
    ''' Internal base class. Not meant to be used by users. '''

    def __init__(self, config=None, args=None, send_func=None):
        ''' Constructor.
        :param config: A dict with configuration options supplied by the user.
        :param args: Arguments used by xtalk.
        :param send_func: Function to directly send MIDI messages.
        '''
        self.send_func = send_func
        self.config = config
        self.args = args
        if not self.config:
            self.config = {}

    def debug(self, msg):
        ''' Helper method to print debug output in a standard format.
        :param msg: Debug message string.
        '''
        if self.args.debug:
            now = get_epoch_now()
            cls_name = type(self).__name__
            print(f'DEBUG ({now}): {cls_name}: {msg}', flush=True)

    def warn(self, msg):
        ''' Helper method to print warning output in a standard format.
        :param msg: Warning message string.
        '''
        now = get_epoch_now()
        cls_name = type(self).__name__
        print(f'WARNING ({now}): {cls_name}: {msg}', flush=True)

    def send(self, msg):
        ''' Directly send the given MIDI message to the global MIDI output, bypassing any further plugins.
        :param msg: MIDI message
        '''
        self.send_func(msg)

class XtalkPlugin(_XtalkPlugin):
    '''
    Base class for plugins to inherit from.

    In addition they must use a class name equal to `XtalkPlugin_[plugin name]` to be scheduled
    by xtalk.
    '''

    @abstractmethod
    async def process(self, msg):
        '''
        Process the given MIDI message.
        This function is called exactly once for every incoming MIDI message _after_
        it was handled by the regular xtalk policies.

        Blocking or delaying this function will block or delay the MIDI message
        pipeline, i.e. it should return as fast as possible.

        Messages can be modified, added or filtered.

        Unhandled AbortExceptions will abort xtalk. Other exceptions are logged only.

        :param msg: 3 byte MIDI message.
        :return:    Iterable of MIDI messages that should be passed to the next plugin.
        '''
