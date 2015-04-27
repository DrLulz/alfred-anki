#!/usr/bin/python
# encoding: utf-8
#
# Copyright Â© 2015 Dean Jackson <deanishe@deanishe.net>
#
# MIT Licence. See http://opensource.org/licenses/MIT
#
# Created on 2015-04-20
#

"""
Demo script for a possible interaction model for creating flashcards.

**Requires Alfred-Workflow**

This is a Script Filter script. It should be saved in the workflow
directory and run as a Script Filter with Language `/bin/bash`,
the default Escaping options, and the following Script:

    /usr/bin/python anki.py "{query}"

The script it's connected to (the one which actually adds the card
to Anki) should load the `list` of sides with:

    wf.cached_data('user_sides', max_age=0)

"""

from __future__ import print_function, unicode_literals, absolute_import

import sys

from lib.workflow import Workflow, ICON_INFO

log = None

# Users enter this delimiter in their query to separate sides of the card
DELIMITER = '//'

# The minimum allowable number of sides before a card can be added
MIN_SIDES = 2
# MIN_SIDES = 1  # Allow faster collection

# Alfred-Workflow boilerplate stuff
DEFAULT_SETTINGS = {}
UPDATE_SETTINGS = {}
HELP_URL = ''
ICON = 'icon.png'

def main(wf):

    # --------------------------------------------------
    # Input

    query = None
    if len(wf.args):
        query = wf.args[0]

    # Split `query` on `DELIMITER`. Remove any empty items.
    sides = [s.strip() for s in query.split(DELIMITER) if s.strip()]
    log.debug('sides : {}'.format(sides))

    # --------------------------------------------------
    # Output

    # If we have data we can act on, offer to save the new card.
    if len(sides) >= MIN_SIDES:

        # First, cache the data the user has entered, so we can load it in
        # the next script. We *could* put it in `arg`, but there might be
        # a lot of data (users can paste reams into Alfred's query box).
        wf.cache_data('user_sides', sides)

        # Only `valid` item.
        wf.add_item('Add New Card',
                    'Card has {} sides'.format(len(sides)),
                    valid=True,
                    arg=' ',  # Need *something* here to make item valid
                    icon='icons/plus.png')

    # Show some help messages. A setting to turn these off might be
    # appropriate
    if len(sides) < 2:
        wf.add_item('Start typing...'.format(DELIMITER),
                    'Start a new side with //',
                    icon=ICON_INFO)
    elif query.endswith(DELIMITER):  # Empty (and invisible) new side
        wf.add_item('Enter "{}" to start a new side'.format(DELIMITER),
                    icon=ICON_INFO)

    # Add sides to results. This provides live feedback of what
    # will be on the new card.
    for i, side in enumerate(sides):
        wf.add_item('Side {:d}: {}'.format(i+1, side),
                    icon=ICON)

    # Finally, send the results to Alfred
    wf.send_feedback()

if __name__ == '__main__':
    wf = Workflow(default_settings=DEFAULT_SETTINGS,
                  update_settings=UPDATE_SETTINGS,
                  help_url=HELP_URL)
    log = wf.logger
    sys.exit(wf.run(main))
