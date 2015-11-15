import os
import sys
import sqlite3
import time

sys.path.insert(0, '/usr/share/anki')
from anki import storage, stats

deckname = os.environ.get('BLOCK_INSTANCE')
if deckname is None or deckname == '':
    deckname = 'core6k'

succ = False
for i in range(1,10):
    try:
        col = storage.Collection('/home/peter/Anki/Benutzer 1/collection.anki2')
    except sqlite3.OperationalError:
        time.sleep(0.1)
        continue
    succ = True
    break

if not succ:
    print '-'
    sys.exit(1)
    
st = stats.CollectionStats(col)

prev = col.decks.selected()

x = col.decks.byName(deckname)
if x is not None:
    col.decks.select(int(x['id']))
else:
    print '-'
    col.decks.select(prev)
    sys.exit(1)

st = stats.CollectionStats(col)
due = st._due(-1000, 1, 1)

if len(due):
    print sum([ x[1] + x[2] for x in due ])
else:
    print 0

col.decks.select(prev)