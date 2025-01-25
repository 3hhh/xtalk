#!/usr/bin/env python3
# -*- encoding: utf8 -*-
#
# MIDI cross-talk cancellation filter.
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

import argparse
import asyncio
import sys
import time
import os
import json
import copy
import inspect
import importlib.util
import rtmidi # rtmidi doc: https://spotlightkid.github.io/python-rtmidi/rtmidi.html
from rtmidi.midiutil import list_input_ports
from rtmidi.midiutil import list_output_ports
from rtmidi.midiutil import open_midiport

class MessageHistory():
    def __init__(self, idx):
        self._history = {} #value = velocity/note --> list of events
        self._idx = idx #index of the value in the message
        for i in range(256):
            self._history[i] = []

    def add(self, msg):
        self._history[msg[self._idx]].append(msg)

    def remove(self, msg):
        try:
            self._history[msg[self._idx]].remove(msg)
        except ValueError:
            pass

    def pop_similar(self, msg):
        try:
            return self._history[msg[self._idx]].pop()
        except IndexError:
            return None

    def has_similar(self, msg):
        return len(self._history[msg[self._idx]]) > 0

    def get_similar(self, msg):
        yield from self._history[msg[self._idx]]

    def get_all(self, values):
        if not values:
            return
        for val in values:
            yield from self._history[val]

    def get_all_above(self, threshold):
        for i in range(int(threshold), 256):
            yield from self._history[i]

    def __str__(self):
        return f'{self._idx}: {self._history}'

#global vars
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PLUGIN_DIR_NAME = 'plugins'
PLUGIN_DIR = os.path.join(SCRIPT_DIR, PLUGIN_DIR_NAME)
PLUGIN_CONF_FILE_DEFAULT = os.path.join(PLUGIN_DIR, 'config.json')
PLUGINS = [] #plugins in the order to use
ARGS = None
POLICY = None
QUEUE = None
LOOP = None
HISTORY = MessageHistory(1) #recently seen note_on messages per note (idx = 1)
DISABLED = MessageHistory(1) #recent NOTE_OFF or similar Midi messages per note number (idx = 1)

#import the plugin base class
sys.path.insert(1, PLUGIN_DIR)
from plugins import XtalkPlugin
from plugins import XtalkPluginException
from plugins import XtalkPluginAbortException
from plugins import is_note_on
from plugins import is_note_off
from plugins import is_note_aftertouch
from plugins import is_note_mod

class FilterPolicy():
    """ A policy that defines how to filter MIDI events for cross-talk cancellation.

    Algorithm:
    On a MIDI note matching the set of [notes], check for cross-talk with the set of [cause] notes. If any [cause] notes were seen during
    the last [delay]+[history] milliseconds, check whether the current note is above the given [threshold] percent (relative to the strongest
    velocity among all recently played [cause] notes). If so, pass the current note.
    If not, check whether the same note was recently played with an acceptable velocity (set only_self=true to disable this check).
    Cancel/filter it otherwise.
    Moreover check_disable=true can be used to check, whether the current note was recently disabled via a note_off or aftertouch MIDI event.
    If so, the current note will be filtered. check_disable=false is the default.
    multi_disable=false can be used with check_disable=true to require a single disable note for every note to be disabled. By default,
    a single disable note will disable all identical notes during the entire history + delay time frame.

    A minimum velocity for all notes can also be enforced.

    Default policy:
    { "notes": [], "cause": [], "threshold": -1, "minimum": -1, "comment": "Empty lists indicate that all notes should be matched. An invalid threshold or minimum causes the command-line value to be used." }
    """

    def __init__(self, path=None):
        self.policies = {} #midi note --> list of policies for that note

        if path:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fp:
                    self.add_policies(json.load(fp))
            else: #directory
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.name.endswith('.json') and entry.is_file():
                            with open(entry, encoding="utf-8") as fp:
                                self.add_policies(json.load(fp))

        if self.policies:
            #make sure that the command-line minimum is always enforced (even if some notes already have policies)
            self.add_policy(json.loads('{ "notes": [], "cause": [], "threshold": 0, "minimum": -1 }'))
        else:
            #load default policies
            self.add_policy(json.loads('{ "notes": [], "cause": [], "threshold": -1, "minimum": -1 }'))

    def add_policy(self, policy):
        #set defaults
        notes = policy.get("notes")
        if not notes:
            notes = range(127)
        if policy.get("threshold") is None or policy["threshold"] < 0 or policy["threshold"] > 100:
            threshold = int(ARGS.threshold)/100
        else:
            threshold = int(policy["threshold"])/100
        if policy.get("minimum") is None or policy["minimum"] < 0 or policy["minimum"] > 127:
            minimum = int(ARGS.minimum)
        else:
            minimum = int(policy["minimum"])
        cause = set(policy.get("cause"))
        if not cause:
            if threshold != 0:
                cause = set(range(127))
            else:
                cause = None
        check_disable = bool(policy.get("check_disable", False))
        multi_disable = bool(policy.get("multi_disable", True))
        only_self = bool(policy.get("only_self", False))

        #add policy
        for note in notes:
            if not self.policies.get(note):
                self.policies[note] = []
            self.policies[note].append({"cause": cause, "threshold": threshold, "minimum": minimum, "check_disable": check_disable, "multi_disable": multi_disable, "only_self": only_self})

    def add_policies(self, policies):
        try:
            for policy in policies:
                self.add_policy(policy)
        except TypeError:
            self.add_policy(policies)

    def blocks(self, msg):
        """ Check the given MIDI note on message against this policy. Returns None, if the policy allows it, otherwise returns the blocking policy. """
        #get the policies for that note
        try:
            policies = self.policies[msg[1]]
        except KeyError:
            #no policy = allow
            return None

        for policy in policies:
            if policy.get("multi_disable"):
                disabled = DISABLED.has_similar(msg)
            else:
                #consume disable notes
                disabled = DISABLED.pop_similar(msg)

            #check whether the message reaches the required minimum velocity
            if msg[2] < policy.get("minimum", 0):
                return policy

            #check whether any disable notes were recently seen
            if policy.get("check_disable") and disabled:
                return policy

            #check whether any cross talk notes (messages causing cross-talk as per the policy) were recently seen
            cross_msgs = HISTORY.get_all(policy["cause"])
            if not cross_msgs:
                continue

            #identify the maximum velocity among the messages causing the potential cross-talk (cross_msgs)
            max_velocity = 0
            for c in cross_msgs:
                if c[2] > max_velocity:
                    max_velocity = c[2]

            if policy.get("only_self"):
                similar = [msg]
            else:
                similar = HISTORY.get_similar(msg)

            #check whether our message or similar messages with identical notes have an acceptable velocity
            acceptable_velocity = max_velocity * policy["threshold"]
            ret = False
            for s in similar: #includes our message
                if s[2] >= acceptable_velocity:
                    ret=True
            if not ret:
                return policy

        return None

    def __str__(self):
        return self.policies.__str__()

class PluginLoadFailedException(Exception):
    ''' Raised when a plugin load operation fails. '''

class PluginAbortException(Exception):
    ''' Raised when a plugin wants to abort further processing. '''

def load_plugin(plugin, cls=XtalkPlugin):
    plugin_file = ''.join([PLUGIN_DIR, '/', plugin, '.py'])
    try:
        spec = importlib.util.spec_from_file_location(PLUGIN_DIR_NAME + '.' + plugin, plugin_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except FileNotFoundError as e:
        raise PluginLoadFailedException('Could not load the plugin %s from the file %s. Does it not exist?' % (plugin, plugin_file)) from e

    ret = None
    cls_name = '_'.join([cls.__name__, plugin])
    for _, member in inspect.getmembers(module, inspect.isclass):
        if member.__name__ == cls_name and issubclass(member, cls):
            ret = member
            break
    if not ret:
        raise PluginLoadFailedException(f'The plugin {plugin} appears to be incorrectly implemented. No matching class {cls_name} found.')
    return ret

def find_api(api_name):
    if api_name == "default":
        return 0

    for api in rtmidi.get_compiled_api():
        name = rtmidi.get_api_display_name(api).lower()
        if api_name in name:
            return api
    raise ValueError(f'No such API found: {api_name}')

def parse_args():
    parser = argparse.ArgumentParser(description='MIDI cross-talk cancellation filter. All incoming MIDI messages are delayed for [delay] milliseconds and stored for [history] milliseconds. Once the delay expires, the notes with acceptable velocity which came in during that time frame are identified (at least [threshold] percent velocity of the strongest velocity that came in). If the current message shares an instrument with that group, it is let through.')
    parser.add_argument('-I', '--input', help='MIDI input port to read from (port number or substring of a port name).')
    parser.add_argument('-O', '--output', help='MIDI output port to write to (port number or substring of a port name).')
    parser.add_argument('-d', '--delay', default=5, type=int, help='Delay (ms): Time to wait for MIDI messages with potential cross-talk issues to come in before starting the algorithm. (default: %(default)s)')
    parser.add_argument('-H', '--history', default=150, type=int, help='History (ms): Time to keep old MIDI messages for cross-talk checks; excludes the delay. (default: %(default)s)')
    parser.add_argument('-t', '--threshold', default=30, type=int, help='Threshold (%%): Acceptable percentage of the maximum velocity signals that came in during the delay + history time frame. (default: %(default)s)')
    parser.add_argument('-m', '--minimum', default=0, type=int, help='Minimum velocity: All MIDI signals below that velocity are suppressed. (default: %(default)s)')
    parser.add_argument('-b', '--before', action='store_true', help='Block MIDI messages unrelated to notes until a decision is made for the next note on event. This will delay all messages happening before a note on event and block them, if the note_on event is blocked.')
    parser.add_argument('-c', '--client', default='xtalk', help='Name of the MIDI client to use. (default: %(default)s)')
    parser.add_argument('-a', '--api', default='default', choices=['jack', 'alsa', 'default'], help='MIDI API to use. Use default on non-Linux devices. (default: %(default)s)')
    parser.add_argument('-P', '--policy', help='Path to a json file or directory with *.json files defining the MIDI filter policy to use. A policy allows for more fine-grained cross-talk cancellation. You can find some examples in the policies folder. Policies are loaded in alphabetical order and may override parameters given on the command-line.')
    parser.add_argument('--dtypes', default='aftertouch', choices=['none', 'note_off', 'aftertouch', 'any'], help='Defines the type of MIDI events to consider MIDI disable notes. Only useful with the -P option and check_disable=true. (default: %(default)s)')
    parser.add_argument('--plugins', help='Comma-separated list of plugins to use. Plugins will be called in the order in which they are specified here and after the xtalk policy decision is made. Plugins are python classes that can be used to filter, add or modify MIDI messages.')
    parser.add_argument('--plugins-config', default=PLUGIN_CONF_FILE_DEFAULT, help='Configuration file to use for plugins. (default: %(default)s)')
    parser.add_argument('--plugins-only', action='store_true', help='Short for --threshold 0 --delay 0 --history 0 --minimum 0. Essentially disables cross-talk cancellation and only runs loaded plugins.')
    parser.add_argument('--list', action='store_true', help='Just list the available APIs and their MIDI ports.')
    parser.add_argument('--debug', action='store_true', help='Print debug output.')
    args = parser.parse_args()

    if args.plugins_only:
        args.threshold = 0
        args.delay = 0
        args.history = 0
        args.minimum = 0

    if args.delay < 0:
        raise ValueError('Delay is out of range.')
    if args.history < 0:
        raise ValueError('History is out of range.')
    if args.threshold < 0 or args.threshold > 100:
        raise ValueError('Threshold is out of range.')
    if args.minimum < 0 or args.minimum > 128:
        raise ValueError('The minimum velocity must be between 0 and 128.')

    if args.plugins:
        args.plugins = args.plugins.split(',')
    else:
        args.plugins = []

    args.api = find_api(args.api)

    return args

def is_note_disable(msg):
    if ARGS.dtypes == 'none':
        return False
    if ARGS.dtypes == 'note_off':
        return is_note_off(msg)
    if ARGS.dtypes == 'aftertouch':
        return is_note_aftertouch(msg)
    return is_note_mod(msg)

def read_callback(tup, data=None):
    if LOOP is None:
        return
    #NOTE: we're running in the thread of the caller (no asyncio loop here)
    #https://raspberrypi.stackexchange.com/questions/54514/implement-a-gpio-function-with-a-callback-calling-a-asyncio-method
    if tup:
        LOOP.call_soon_threadsafe(asyncio.create_task, read_in(tup))

async def read_in(tup):
    await QUEUE.put(tup)
    msg = tup[0]
    if is_note_on(msg):
        HISTORY.add(msg)
        debug(f'note on: {msg}')
    elif is_note_disable(msg):
        #track disable notes for check_disable policy
        DISABLED.add(msg)
        debug(f'note disable: {msg}')
    await asyncio.sleep(0)

def cleanup_note_on(msg):
    try:
        HISTORY.remove(msg)
    except ValueError:
        pass

def cleanup_disabled(msg):
    try:
        DISABLED.remove(msg)
    except ValueError:
        pass

def debug(print_msg):
    if ARGS.debug:
        now = time.time_ns()/1000000 #ms since epoch
        print(f'DEBUG ({now}): {print_msg}', flush=True)

async def write_out(midiout):
    cache = []
    delay = ARGS.delay / 1000
    history = ARGS.history / 1000

    while True:
        msg, delta = await QUEUE.get()
        bpolicy = None
        send = True

        #wait for further messages to come in
        await asyncio.sleep(min(delta, delay))

        #debug(f'checking: {msg}')

        msgs = [] #messages to handle during this iteration

        if is_note_disable(msg):
            #schedule cleanup
            asyncio.get_running_loop().call_later(history, cleanup_disabled, msg)
        elif is_note_on(msg):
            #schedule cleanup
            asyncio.get_running_loop().call_later(history, cleanup_note_on, msg)

            #check cross-talk cancellation policy
            bpolicy = POLICY.blocks(msg)
            send = bpolicy is None

            #use & clear cache
            msgs = cache
            cache = []
        elif ARGS.before and not is_note_mod(msg):
            #cache until next NOTE_ON message
            cache.append(msg)
            continue

        #decide
        msgs.append(msg)
        if send:
            debug(f'passed: {msgs}')
        else:
            debug(f'SUPPRESSED: {msgs}, policy: {bpolicy}')
            msgs = []

        #plugins may modify messages --> better create a copy or our own memory references may change
        if PLUGINS:
            pmsgs = copy.deepcopy(msgs)
        else:
            pmsgs = msgs

        #run plugins
        for plugin in PLUGINS:
            try:
                omsgs = []
                for msg in pmsgs:
                    async for m in plugin.process(msg):
                        omsgs.append(m)
                pmsgs = omsgs
            except XtalkPluginAbortException as e:
                #stop processing further messages
                raise PluginAbortException(f'The {plugin} plugin raised an abort exception.') from e
            except XtalkPluginException as e:
                #don't stop processing
                print(f'The {plugin} plugin raised an exception: {e}')

        #send
        #debug(f'sending: {pmsgs}')
        for msg in pmsgs:
            midiout.send_message(msg)

async def run():
    global QUEUE
    QUEUE = asyncio.Queue()
    midiin = None
    midiout = None

    try:
        midiout, midiout_port = open_midiport(port=ARGS.output, type_='output', client_name=ARGS.client, api=ARGS.api, port_name='output', use_virtual=ARGS.output is None)
        midiin, midiin_port = open_midiport(port=ARGS.input, type_='input', client_name=ARGS.client, api=ARGS.api, port_name='input', use_virtual=ARGS.input is None)
        midiin.ignore_types(sysex=False,timing=False,active_sense=False) #make sure no messages are ignored
        midiin.set_callback(read_callback)
        await write_out(midiout)
    finally:
        if midiin:
            del midiin
        if midiout:
            del midiout

def print_info():
    print('Available APIs:')
    for api in rtmidi.get_compiled_api():
        name = rtmidi.get_api_display_name(api)
        print(f'{api}: {name}')
        try:
            list_input_ports(api=api)
            list_output_ports(api=api)
        except:
            print('Error while reading from the API.')

def main():
    global ARGS
    global POLICY
    global LOOP
    ARGS = parse_args()
    POLICY = FilterPolicy(ARGS.policy)
    debug(POLICY)

    if ARGS.list:
        print_info()
        return

    #read plugin configuration, if available
    try:
        with open(ARGS.plugins_config, encoding="utf-8") as fp:
            plugin_conf = json.load(fp)
        debug(f'Plugin configuration loaded from {ARGS.plugins_config}.')
    except OSError:
        debug(f'No plugin configuration found at {ARGS.plugins_config}.')
        plugin_conf = {}

    #load plugins
    plugin_classes = {}
    i=0
    for plugin in ARGS.plugins:
        plugin_cls = plugin_classes.get(plugin)
        if not plugin_cls:
            plugin_cls = load_plugin(plugin)

        #get plugin configuration
        #try index first (useful if the same plugin is used multiple times), plugin name second
        try:
            pconf = plugin_conf[str(i)]
        except KeyError:
            pconf = plugin_conf.get(plugin)

        PLUGINS.append(plugin_cls(config=pconf, debug=ARGS.debug))
        debug(f'Plugin {plugin} loaded. Config: {pconf}')
        i=i+1

    #run
    LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(LOOP)
    try:
        LOOP.run_until_complete(run())
    finally:
        LOOP = None

if __name__ == '__main__':
    sys.exit(main())
