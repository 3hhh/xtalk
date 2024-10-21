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

import asyncio
import re

from plugins import XtalkPlugin
from plugins import is_note
from plugins import is_note_on

class XtalkPlugin_replace(XtalkPlugin):
    '''
    Plugin to replace incoming MIDI notes with other MIDI notes.

    This may happen statically (e.g. always replace note 35 with 38) or dynamically:
    For example the user may specify MIDI note 40 to enable note 35 to be replaced
    by note 38 during play. Similarly the user may define a MIDI note to disable the
    replacement.
    Alternatively the user can employ a TCP API to enable or disable the replacement.
    This API can be used via `netcat` and similar programs. Users can e.g. bind such
    `netcat' commands to triggers coming from external USB foot pedals.

    Multiple triggers and replacements are supported.

    Available TCP API commands:
    enable|disable|toggle [id]|next|previous

    enable:  Enable the replacement identified by [id] or the next or previously
             listed replacement.
    disable: Disable the replacement identified by [id] or the next or previously
             listed replacement.
    toggle:  Toggle the replacement status of the [id] replacement or the next or previously
             listed replacement.
    unique:  Enable the replacement identified by [id] or the next or previously
             listed replacement _and_ disable all other replacements.

    See the supplied example config.json for all available configuration options.
    '''

    def __init__(self, config=None, debug=False):
        super().__init__(config=config, debug=debug)

        #currently active replacements map: from MIDI note --> to MIDI note
        self.replacements = {}

        #map of triggers: MIDI note --> set of enable or disable triggers (configuration indices as references)
        self.triggers = {}

        #index for the next|previous commands
        self.cmd_index = 0

        #whether or not to spawn a TCP server by default
        self.server = False

        if config:
            #init server vars
            self.server = bool(config.get("server", False))
            self.server_port = int(config.get("port", 1560))
            self.server_address = config.get("address", "localhost")

            #init self.replacements & self.triggers
            for index, replacement in enumerate(config.get("replace", [])):
                if self.is_enabled(replacement):
                    self.enable(replacement, force=True)
                triggers = set(replacement.get("enable", set())).union(set(replacement.get("disable", set())))
                for trigger in triggers:
                    self.triggers[trigger] = self.triggers.get(trigger) or set()
                    self.triggers[trigger].add(index)

        self.debug(f'replacements: {self.replacements}')
        self.debug(f'triggers: {self.triggers}')

        #spawn server, if necessary
        if self.server:
            loop = asyncio.get_event_loop()
            loop.call_soon(asyncio.create_task, self.start_server())

    async def start_server(self):
        server = await asyncio.start_server(self.handle_client, host=self.server_address, port=self.server_port)

        addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
        self.debug(f'Started server on {addrs}.')

        async with server:
            await server.serve_forever()

    async def handle_client(self, reader, writer):
        self.debug('Client connected.')
        pattern = re.compile('^(enable|disable|toggle|unique) (.*)$')

        line = True
        while line:
        #NOTE: This interface is inherently easy to attack via DoS. So do not use this in hostile environments!
            try:
                line = await reader.readline()
            except:
                continue

            if not line:
                self.debug('Client disconnected.')
                return

            try:
                line = line.decode(encoding="utf-8", errors="strict")
            except UnicodeError:
                self.debug('Client caused an encoding error.')
                continue

            match = pattern.match(line)
            if match:
                cmd = match.group(1)
                id_str = match.group(2)

                repls = self.find_replacements(id_str)
                if not repls:
                    self.debug(f'Unexpected ID: {line}')
                    continue

                if cmd == 'enable':
                    for repl in repls:
                        self.enable(repl)
                elif cmd == 'disable':
                    for repl in repls:
                        self.disable(repl)
                elif cmd == 'toggle':
                    for repl in repls:
                        self.toggle(repl)
                elif cmd == 'unique':
                    self.disable_all()
                    for repl in repls:
                        self.enable(repl, force=True)
                else:
                    self.debug(f'Unexpected command: {line}')
                    continue
            else:
                self.debug(f'Unexpected line: {line}')
                continue

    def is_enabled(self, replacement):
        return bool(replacement.get("enabled", False))

    #enable the given replacement configuration item
    def enable(self, replacement, force=False):
        if force or not self.is_enabled(replacement):
            rfrom = set(replacement.get("from", set()))
            rto = int(replacement.get("to"))

            for note in rfrom:
                self.replacements[note] = rto

            replacement["enabled"] = True
            self.debug(f'Enabled: {replacement}')

    #disable the given replacement configuration item
    def disable(self, replacement):
        if self.is_enabled(replacement):
            rfrom = set(replacement.get("from", set()))

            for note in rfrom:
                self.replacements[note] = None

            replacement["enabled"] = False
            self.debug(f'Disabled: {replacement}')

    def disable_all(self):
        self.debug('Disabling all...')
        for rpl in self.config.get("replace", set()):
            self.disable(rpl)

    #toggle the enable status of the given replacement configuration item
    def toggle(self, replacement):
        if self.is_enabled(replacement):
            self.disable(replacement)
        else:
            self.enable(replacement)

    #find matching replacements by id (supports next|previous commands)
    def find_replacements(self, id_str):
        replacements = list(self.config.get("replace", []))

        if not replacements:
            return

        if id_str == "next":
            self.cmd_index = ( self.cmd_index + 1 ) % len(replacements)
            yield replacements[self.cmd_index]
            return
        if id_str == "previous":
            self.cmd_index = ( self.cmd_index - 1 ) % len(replacements)
            yield replacements[self.cmd_index]
            return

        for replacement in replacements:
            if id_str == str(replacement.get("id")):
                yield replacement

    async def process(self, msg):
        if is_note(msg):
            note = msg[1]

            #process triggers
            if is_note_on(msg):
                for index in self.triggers.get(note, set()):
                    replacement = self.config.get("replace", [])[index]
                    if note in set(replacement.get("enable", set())) and note in set(replacement.get("disable", set())):
                        self.toggle(replacement)
                    elif note in set(replacement.get("enable", set())):
                        self.enable(replacement)
                    else:
                        self.disable(replacement)

            #process replacements
            note_to = self.replacements.get(note) or note
            if note_to != note:
                self.debug(f'Replaced: {note} -> {note_to}')

            msg[1] = note_to
        yield msg
