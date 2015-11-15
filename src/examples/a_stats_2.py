#!/usr/bin/env python3

import collections
import json
import os
import pprint
import sqlite3


DECK_NAME = 'Chinese'

conn = sqlite3.connect(os.path.expanduser('~/Anki/User 1/collection.anki2'))

decks_col = conn.execute("SELECT decks FROM col")
decks = json.loads(decks_col.fetchone()[0])

for id, deck in decks.items():
    if deck['name'] == DECK_NAME:
        chinese = deck
        chinese['id'] = id
        break
else:
    print("Unable to find the %r deck :(" % DECK_NAME)

cards = conn.execute("SELECT cards.id, nid, flds, sfld "
                     "FROM cards "
                     "JOIN notes ON notes.id = cards.nid "
                     "WHERE cards.did = ?",
                     (chinese['id'],))

chars = collections.defaultdict(lambda: 0)

for card in cards:
    id, note_id, front, back = card

    for char in back:
        if ord(char) < 127:
            continue
        chars[char] += 1

for char in sorted(chars, key=lambda c: chars[c]):
    print("%s: %d" % (char, chars[char]))

print("Total: %d" % len(chars))