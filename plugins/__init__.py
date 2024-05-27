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

def is_note_on(msg):
    return ((msg[0] & 0xf0) ^ MIDI_NOTEON) == 0

def is_note_off(msg):
    return ((msg[0] & 0xf0) ^ MIDI_NOTEOFF) == 0

def is_note_aftertouch(msg):
    return ((msg[0] & 0xf0) ^ MIDI_AFTERTOUCH) == 0

def is_note_mod(msg):
    return is_note_off(msg) or is_note_aftertouch(msg)

class XtalkPluginException(Exception):
    ''' Base class for plugin exceptions. '''

class XtalkPluginAbortException(XtalkPluginException):
    ''' Thrown when the MIDI connection is meant to be aborted. '''

class _XtalkPlugin(ABC):
    ''' Internal base class. Not meant to be used by users. '''

    def __init__(self, config=None, debug=False):
        ''' Constructor.
        :param config: A dict with configuration options supplied by the user.
        :param debug: Whether or not the plugin should run in debug mode.
        '''
        self._debug = debug
        self.config = config
        if not self.config:
            self.config = {}

    def debug(self, msg):
        ''' Helper method to print debug output in a standard format.
        :param msg: Debug message string.
        '''
        if self._debug:
            now = time.time_ns()/1000000 #ms since epoch
            cls_name = type(self).__name__
            print(f'DEBUG ({now}): {cls_name}: {msg}', flush=True)

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
