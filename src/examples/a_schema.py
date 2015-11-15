-- cards are what you review. easy!
CREATE TABLE cards (
    id              integer primary key,
      -- the epoch milliseconds of when the card was created
    nid             integer not null,
      -- notes.id
    did             integer not null,
      -- deck id (available in col table)
    ord             integer not null,
      -- ordinal, seems like. for when a model has multiple templates, or thereabouts
    mod             integer not null,
      -- modified time as epoch seconds
    usn             integer not null,
      -- "From the source code it appears Anki increments this number each time you synchronize with AnkiWeb and applies this number to the cards that were synchronized. My database is up to 1230 for the collection and my cards have various numbers up to 1229." -- contributed by Fletcher Moore
    type            integer not null,
      -- in anki1, type was whether the card was suspended, etc. seems to be the same. values are 0 (suspended), 1 (maybe "learning"?), 2 (normal)
    queue           integer not null,
      -- "queue in the cards table refers to if the card is "new" = 0, "learning" = 1 or 3, "review" = 2 (I don't understand how a 3 occurs, but I have 3 notes out of 23,000 with this value.)" -- contributed by Fletcher Moore
    due             integer not null,
    ivl             integer not null,
      -- interval (used in SRS algorithm)
    factor          integer not null,
      -- factor (used in SRS algorithm)
    reps            integer not null,
      -- number of reviews
    lapses          integer not null,
      -- possibly the number of times the card went from a "was answered correctly" to "was answered incorrectly" state
    left            integer not null,
      -- 0 for all my cards
    odue            integer not null,
      -- 0 for all my cards
    odid            integer not null,
      -- 0 for all my cards
    flags           integer not null,
      -- 0 for all my cards
    data            text not null
      -- currently unused for decks imported from anki1. maybe extra data for plugins?
);

-- col is a collection of decks
CREATE TABLE col (
    id              integer primary key,
      -- seems to be an autoincrement
    crt             integer not null,
      -- there's the created timestamp
    mod             integer not null,
      -- last modified in milliseconds
    scm             integer not null,
      -- a timestamp in milliseconds. "schema mod time" - contributed by Fletcher Moore
    ver             integer not null,
      -- version? I have "11"
    dty             integer not null,
      -- 0
    usn             integer not null,
      -- 0
    ls              integer not null,
      -- "last sync time" - contributed by Fletcher Moore
    conf            text not null,
      -- json blob of configuration
    models          text not null,
      -- json object with keys being ids(epoch ms), values being configuration
    decks           text not null,
      -- json object with keys being ids(epoch ms), values being configuration
    dconf           text not null,
      -- json object. deck configuration?
    tags            text not null
      -- a cache of tags used in this collection (probably for autocomplete etc)
);

-- dunno what this is yet. my deck has 7. usn is -1, type is 1, and oid varies.
CREATE TABLE graves (
    usn             integer not null,
    oid             integer not null,
    type            integer not null
);

-- notes are the new facts, which can be used by different cards.
CREATE TABLE notes (
    id              integer primary key,
      -- epoch seconds of when the note was created
    guid            text not null,
      -- globally unique id, almost certainly used for syncing
    mid             integer not null,
      -- model id
    mod             integer not null,
      -- modified timestamp, epoch seconds
    usn             integer not null,
      -- -1 for all my notes
    tags            text not null,
      -- space-separated string of tags. seems to include space at the beginning and end of the field, almost certainly for LIKE "% tag %" queries
    flds            text not null,
      -- the values of the fields in this note. separated by 0x1f (31).
    sfld            integer not null,
      -- the text of the first field, used for anki2's new (simplistic) uniqueness checking
    csum            integer not null,
      -- dunno. not a unique field, but very few repeats
    flags           integer not null,
      -- 0 for all my notes
    data            text not null
      -- empty string for all my notes
);

-- revlog is review history; it has a row for every single review you've ever done!
CREATE TABLE revlog (
    id              integer primary key,
       -- epoch-seconds timestamp of when you did the review
    cid             integer not null,
       -- cards.id
    usn             integer not null,
       -- all my reviews have -1
    ease            integer not null,
       -- which button you pushed to score your recall. 1(wrong), 2(hard), 3(ok), 4(easy)
    ivl             integer not null,
       -- interval
    lastIvl         integer not null,
       -- last interval
    factor          integer not null,
      -- factor
    time            integer not null,
       -- how many milliseconds your review took, up to 60000 (60s)
    type            integer not null
);


CREATE INDEX ix_cards_nid on cards (nid);
CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_cards_usn on cards (usn);
CREATE INDEX ix_notes_csum on notes (csum);
CREATE INDEX ix_notes_usn on notes (usn);
CREATE INDEX ix_revlog_cid on revlog (cid);
CREATE INDEX ix_revlog_usn on revlog (usn);