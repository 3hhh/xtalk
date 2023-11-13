#!/usr/bin/python3
# -*- encoding: utf8 -*-
#
# MIDI cross-talk cancellation filter.
#
# Copyright (C) 2023  David Hobach  GPLv3
# 0.7
#
# rtmidi doc: https://spotlightkid.github.io/python-rtmidi/rtmidi.html
#

import argparse
import asyncio
import sys
import time
import os
import json
import rtmidi
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
        for val in values:
            yield from self._history[val]

    def get_all_above(self, threshold):
        for i in range(int(threshold), 256):
            yield from self._history[i]

    def __str__(self):
        return f'{self._idx}: {self._history}'

#constants
MIDI_NOTEON     = 0x90 #lower bytes must be ignored
MIDI_NOTEOFF    = 0x80 #lower bytes must be ignored
MIDI_AFTERTOUCH = 0xA0 #lower bytes must be ignored

#global vars
ARGS = None
POLICY = None
QUEUE = None
HISTORY = MessageHistory(1) #recently seen note_on messages per note (idx = 1)
DISABLED = MessageHistory(1) #recent NOTE_OFF or similar Midi messages per note number (idx = 1)

class FilterPolicy():
    """ A policy that defines how to filter MIDI events for cross-talk cancellation.

    Algorithm:
    On a MIDI note matching the set of [notes], check for cross-talk with the set of [cause] notes. If any [cause] notes were seen during
    the last [delay]+[history] milliseconds, check whether the current note is above the given [threshold] percent (relative to the strongest
    velocity among all recently played [cause] notes). If so, pass the current note.
    If not, check whether the same note was recently played with an acceptable velocity. Cancel/filter it otherwise.
    Moreover check_disable=true can be used to check, whether the current note was recently disabled via a note_off or aftertouch MIDI event.
    If so, the current note will be filtered. check_disable=false is the default.
    multi_disable=false can be used with check_disable=true to require a single disable note for every note to be disabled. By default,
    a single disable note will disable all identical notes during the entire history + delay time frame.

    A minimum velocity for all notes can also be enforced.

    Default policy:
    { "notes": [], "cause": [], "threshold": -1, "minimum": -1, "check_disable": false, "comment": "Empty lists indicate that all notes should be matched. An invalid threshold causes the command-line threshold to be used." }
    """

    def __init__(self, path=None):
        self.policies = {} #midi note --> list of policies for that note

        if path:
            if os.path.isfile(path):
                with open(path) as fp:
                    self.add_policies(json.load(fp))
            else: #directory
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.name.endswith('.json') and entry.is_file():
                            with open(entry) as fp:
                                self.add_policies(json.load(fp))
        if not self.policies:
            #load default policies
            self.add_policy(json.loads('{ "notes": [], "cause": [], "threshold": -1, "minimum": -1, "check_disable": false }'))

    def add_policy(self, policy):
        #set defaults
        notes = policy.get("notes")
        if not notes:
            notes = range(127)
        cause = set(policy.get("cause"))
        if not cause:
            cause = set(range(127))
        if not policy.get("threshold") or policy["threshold"] < 0 or policy["threshold"] > 100:
            threshold = int(ARGS.threshold)/100
        else:
            threshold = int(policy["threshold"])/100
        if not policy.get("minimum") or policy["minimum"] < 0 or policy["minimum"] > 127:
            minimum = int(ARGS.minimum)
        else:
            minimum = int(policy["minimum"])
        check_disable = bool(policy.get("check_disable", False))
        multi_disable = bool(policy.get("multi_disable", True))

        #add policy
        for note in notes:
            if not self.policies.get(note):
                self.policies[note] = []
            self.policies[note].append({"cause": cause, "threshold": threshold, "minimum": minimum, "check_disable": check_disable, "multi_disable": multi_disable})

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

            #check whether our message or similar messages with identical notes have an acceptable velocity
            acceptable_velocity = max_velocity * policy["threshold"]
            ret = False
            for s in HISTORY.get_similar(msg): #includes our message
                if s[2] >= acceptable_velocity:
                    ret=True
            if not ret:
                return policy

        return None

    def __str__(self):
        return self.policies.__str__()

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
    parser.add_argument('-I', '--input', help='MIDI inport port to read from (port number or substring of a port name).')
    parser.add_argument('-O', '--output', help='MIDI output port to write to (port number or substring of a port name).')
    parser.add_argument('-d', '--delay', default=5, type=int, help='Delay (ms): Time to wait for MIDI messages with potential cross-talk issues to come in before starting the algorithm.')
    parser.add_argument('-H', '--history', default=150, type=int, help='History (ms): Time to keep old MIDI messages for cross-talk checks; excludes the delay.')
    parser.add_argument('-t', '--threshold', default=30, type=int, help='Threshold (%%): Acceptable percentage of the maximum velocity signals that came in during the delay + history time frame.')
    parser.add_argument('-m', '--minimum', default=0, type=int, help='Minimum velocity: All MIDI signals below that velocity are suppressed.')
    parser.add_argument('-c', '--client', default='xtalk', help='Name of the MIDI client to use.')
    parser.add_argument('-a', '--api', default='default', choices=['jack', 'alsa', 'default'], help='MIDI API to use. Use default on non-Linux devices.')
    parser.add_argument('-P', '--policy', help='Path to a json file or directory with *.json files defining the MIDI filter policy to use. A policy allows for more fine-grained cross-talk cancellation. You can find some examples in the policies folder. Policies are loaded in alphabetical order and may override parameters given on the command-line.')
    parser.add_argument('--dtypes', default='aftertouch', choices=['none', 'note_off', 'aftertouch', 'any'], help='Defines the type of MIDI events to consider MIDI disable notes. Only useful with the -P option and check_disable=true.')
    parser.add_argument('--list', action='store_true', help='Just list the available APIs and their MIDI ports.')
    parser.add_argument('--debug', action='store_true', help='Print debug output.')
    args = parser.parse_args()

    if args.delay < 0:
        raise ValueError('Delay is out of range.')
    if args.history < 0:
        raise ValueError('History is out of range.')
    if args.threshold < 0 or args.threshold > 100:
        raise ValueError('Threshold is out of range.')
    if args.minimum < 0 or args.minimum > 128:
        raise ValueError('The minimum velocity must be between 0 and 128.')

    args.api = find_api(args.api)

    return args

def is_note_on(msg):
    return ((msg[0] & 0xf0) ^ MIDI_NOTEON) == 0

def is_note_off(msg):
    return ((msg[0] & 0xf0) ^ MIDI_NOTEOFF) == 0

def is_note_aftertouch(msg):
    return ((msg[0] & 0xf0) ^ MIDI_AFTERTOUCH) == 0

def is_note_mod(msg):
    return is_note_off(msg) or is_note_aftertouch(msg)

def is_note_disable(msg):
    if ARGS.dtypes == 'none':
        return False
    elif ARGS.dtypes == 'note_off':
        return is_note_off(msg)
    elif ARGS.dtypes == 'aftertouch':
        return is_note_aftertouch(msg)
    else: #'any'
        return is_note_mod(msg)

async def read_in(midiin, wait_s=1/1000):
    while True:
        tup = midiin.get_message()
        if tup:
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
        else:
            await asyncio.sleep(wait_s)

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
    delay = ARGS.delay / 1000
    history = ARGS.history / 1000

    while True:
        msg, delta = await QUEUE.get()
        bpolicy = None
        send = True

        #wait for further messages to come in
        await asyncio.sleep(min(delta, delay))

        #debug(f'checking: {msg}')

        if is_note_disable(msg):
            #schedule cleanup
            asyncio.get_running_loop().call_later(history, cleanup_disabled, msg)
        elif is_note_on(msg):
            #schedule cleanup
            asyncio.get_running_loop().call_later(history, cleanup_note_on, msg)

            #check cross-talk cancellation policy
            bpolicy = POLICY.blocks(msg)
            send = ( bpolicy is None )

        #send
        if send:
            midiout.send_message(msg)
            debug(f'passed: {msg}')
        else:
            debug(f'SUPPRESSED: {msg}, policy: {bpolicy}')

async def run():
    global QUEUE
    QUEUE = asyncio.Queue()
    tasks = None
    midiin = None
    midiout = None
    try:
        midiout, midiout_port = open_midiport(port=ARGS.output, type_='output', client_name=ARGS.client, api=ARGS.api, port_name='output', use_virtual=(ARGS.output is None))
        midiin, midiin_port = open_midiport(port=ARGS.input, type_='input', client_name=ARGS.client, api=ARGS.api, port_name='input', use_virtual=(ARGS.input is None))
        midiin.ignore_types(sysex=False,timing=False,active_sense=False) #make sure no messages are ignored
        tasks = asyncio.gather(read_in(midiin), write_out(midiout))
        await tasks
    finally:
        if tasks:
            tasks.cancel()
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
    ARGS = parse_args()
    POLICY = FilterPolicy(ARGS.policy)
    debug(POLICY)

    if ARGS.list:
        print_info()
    else:
        asyncio.run(run())

if __name__ == '__main__':
    sys.exit(main())
