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

from plugins import XtalkPlugin
from plugins import is_note_on

class XtalkPlugin_example(XtalkPlugin):
    '''
    Some edrumulus hotfixes serving as an example.
    '''

    async def process(self, msg):
        if is_note_on(msg):

            # the hihat (note 22) always comes in at maximum velocity (127) --> reduce it
            if msg[1] == 22 and msg[2] == 127:
                msg[2] = 50

            # MPS 750x ride heuristics: if the ride bell is hit, it triggers a ride edge (59) note with low velocity
            # -->switch that to ride bell (53)
            if msg[1] == 59 and msg[2] <= 80:
                msg[1] = 53

        yield msg
