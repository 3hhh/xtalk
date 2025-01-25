# xtalk

MIDI cross-talk cancellation filter.

It should work on Linux, Windows and Mac OS.

## Usage

See `xtalk.py --help` for the list of available options.

`xtalk.py --list` will display all available MIDI interfaces that you can work with.

You can either specify a basic set of parameters on the command-line or work with advanced filter policies.
The policies enable users to specify which MIDI notes cause what cross-talk MIDI notes, so that ideally only
those are filtered. A set of example policies can be found in the policies folder.

## Installation

1. Install all required dependencies according to their installation guides or with your favorite package manager: [python3](https://www.python.org/downloads/), [python3-rtmidi](https://spotlightkid.github.io/python-rtmidi/installation.html)  
   E.g. on debian-based OSes: `sudo apt install python3 python3-rtmidi`
2. Clone this repository and copy it to a directory of your liking.
3. Run the xtalk script, e.g. `cd [dir] ; ./xtalk.py --help`.

## Uninstall

Just remove the directory created during the installation and uninstall the xtalk dependencies.

## Copyright

© 2025 David Hobach

xtalk is released under the GPLv3 license; see `LICENSE` for details.
