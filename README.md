# xtalk

MIDI cross-talk cancellation filter and plugin host for real-time MIDI applications in Python.

It should work on Linux, Windows and Mac OS.

## Usage

See `xtalk.py --help` for the list of available options.

`xtalk.py --list` will display all available MIDI interfaces that you can work with.

For crass-talk cancellation you can either specify a basic set of parameters on the command-line or use advanced filter policies.
The policies enable users to specify which MIDI notes cause what cross-talk MIDI notes, so that ideally only
those are filtered. A set of example policies can be found in the policies folder.

The currently available plugins can be found in the plugins folder.

## Installation

On Linux systems:

1. Install all required dependencies according to their installation guides or with your favorite package manager: [python3](https://www.python.org/downloads/) incl. [venv support](https://docs.python.org/3/library/venv.html), [python3-pip](https://github.com/pypa/pip) and [python3-rtmidi](https://spotlightkid.github.io/python-rtmidi/installation.html).  
   E.g. on debian-based OSes: `sudo apt install python3 python3-venv python3-pip python3-rtmidi`
2. Clone this repository and copy it to a directory of your liking.
3. Use `cd` to change to the repository directory.
4. Optional: If you want to use the most recent dependencies, run `rm -f pkgs/* && pip3 download --destination-directory ./pkgs pynput setuptools`.
5. Run the installer via `./installer install`.  
   You can check the `./installer` help output for further options.
6. Run xtalk via the `./xtalk` script, which was created by the installer.

### A note on other OSes

All of the python code is cross-platform, i.e. it should also work on other OSes such as Windows or Mac.

The installer routines however are specific to Linux, i.e. you'll have to figure out the installation yourself.

## Uninstall

1. Run `./installer uninstall`.
2. Remove the repository and uninstall the dependencies installed during the first installation step.

## Copyright

© 2026 David Hobach

xtalk is released under the GPLv3 license; see `LICENSE` for details.
