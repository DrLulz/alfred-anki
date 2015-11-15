#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright: Damien Elmes <anki@ichi2.net>
# License: GNU GPL, version 3 or later; http://www.gnu.org/copyleft/gpl.html

"""\
The Deck
====================
"""
__docformat__ = 'restructuredtext'

try:
    from sqlite3 import dbapi2 as sqlite
except ImportError:
    try:
        from pysqlite2 import dbapi2 as sqlite
    except:
        raise "Please install pysqlite2 or python2.5"
sqlite.enable_shared_cache(True)

import tempfile, time, os, random, sys, re, stat, shutil, types
from heapq import heapify, heappush, heappop

from anki.db import *
from anki.lang import _
from anki.errors import DeckAccessError, DeckWrongFormatError
from anki.stdmodels import BasicModel
from anki.utils import parseTags
from anki.history import CardHistoryEntry
from anki.models import Model

# ensure all the metadata in other files is loaded before proceeding
import anki.models, anki.facts, anki.cards, anki.stats, anki.history

PRIORITY_HIGH = 4
PRIORITY_MED = 3
PRIORITY_NORM = 2
PRIORITY_LOW = 1
PRIORITY_NONE = 0

MATURE_THRESHOLD = 21

NewCardOrder = {
    0: _("Show new cards in random order"),
    1: _("Show new cards in order they were added"),
    }

# parts of the code assume we only have one deck
decksTable = Table(
    'decks', metadata,
    Column('id', Integer, primary_key=True),
    Column('created', Float, nullable=False, default=time.time),
    Column('modified', Float, nullable=False, default=time.time),
    Column('description', UnicodeText, nullable=False, default=u""),
    Column('version', Integer, nullable=False, default=0),
    Column('currentModelId', Integer, ForeignKey("models.id")),
    # syncing
    Column('syncName', UnicodeText),
    Column('lastSync', Float, nullable=False, default=0),
    # scheduling
    ##############
    # initial intervals
    Column('hardIntervalMin', Float, nullable=False, default=0.333),
    Column('hardIntervalMax', Float, nullable=False, default=0.5),
    Column('midIntervalMin', Float, nullable=False, default=3.0),
    Column('midIntervalMax', Float, nullable=False, default=5.0),
    Column('easyIntervalMin', Float, nullable=False, default=7.0),
    Column('easyIntervalMax', Float, nullable=False, default=9.0),
    # delays on failure
    Column('delay0', Integer, nullable=False, default=600),
    Column('delay1', Integer, nullable=False, default=1200),
    Column('delay2', Integer, nullable=False, default=28800),
    # collapsing future cards
    Column('collapseTime', Float, nullable=False, default=18000),
    # priorities & postponing
    Column('highPriority', UnicodeText, nullable=False, default=u""),
    Column('medPriority', UnicodeText, nullable=False, default=u""),
    Column('lowPriority', UnicodeText, nullable=False, default=u""),
    Column('suspended', UnicodeText, nullable=False, default=u"Suspended"),
    # 0 is random, 1 is by input date
    Column('newCardOrder', Integer, nullable=False, default=0),
    # not currently used
    Column('newCardSpacing', Integer, nullable=False, default=0),
    # limit the number of failed cards in play
    Column('failedCardMax', Integer, nullable=False, default=20))

class Deck(object):
    "Top-level object. Manages facts, cards and scheduling information."

    def __init__(self, path=None):
        "Create a new deck."
        # a limit of 1 deck in the table
        self.id = 1
        # db session factory and instance
        self.Session = None
        self.s = None

    def _initVars(self):
        self.lastTags = u""
        self.lastLoaded = time.time()

    def modifiedSinceSave(self):
        return self.modified > self.lastLoaded

    factorFour = 1.3
    initialFactor = 2.5
    maxScheduleTime = 1825

    _queue = ("select type, due, id, modified, priority, reps, successive, interval, "
              "factId, ordinal, created from typedCards")

    _earliest = """
select (case
-- failed cards minus delay0/1 lookahead
when cards.reps != 0 and cards.successive = 0 then
cards.due - (select min(max(delay0, delay1), collapseTime)
from decks where id = 1)
-- 'due' if same card as last time
when cards.id = facts.lastCardId
then cards.due
-- otherwise max(due, spaceUntil)
else max(cards.due, facts.spaceUntil) end) as due2, cards.question
from cards, facts where
cards.factId = facts.id and cards.priority != 0
order by due2
limit 1
"""

    # Scheduling: queue management
    ##########################################################################

    def rebuildQueue(self):
        "Rebuild the revision queue on startup/after syncing/etc."
        # ensure all card objects are written to db first
        self.s.flush()
        self.factSpacing = {}
        if self.newCardOrder == 0: acq = AcqRandomItem
        else: acq = AcqOrderedItem
        queue = self.s.all(self._queue)
        def ilist(type, itemClass, q):
            return [itemClass(*x[1:]) for x in q if x[0]==type]
        self.failedQueue = ilist(0, FailedItem, queue)
        self.revQueue = ilist(1, RevItem, queue)
        self.acqQueue = ilist(2, acq, queue)
        self.futureQueue = ilist(3, FutureItem, queue)
        heapify(self.failedQueue)
        heapify(self.revQueue)
        heapify(self.acqQueue)
        heapify(self.futureQueue)

    def getCard(self):
        "Return the next due card, or None"
        now = time.time()
        # any expired cards?
        while self.futureQueue and self.futureQueue[0].due <= now:
            newItem = heappop(self.futureQueue)
            self.addExpiredItem(newItem)
        # failed card due?
        if (self.failedQueue and self.failedQueue[0].due <= now):
            item = heappop(self.failedQueue)
        # failed card queue too big?
        elif (self.failedCardMax and
            self.failedCardsDueSoon() >= self.failedCardMax):
            item = self.getOldestModifiedFailedCard()
        # card due for revision
        elif self.revQueue:
            item = heappop(self.revQueue)
        # card due for acquisition
        elif self.acqQueue:
            item = heappop(self.acqQueue)
        else:
            if self.collapsedFailedCards():
                # final review
                item = self.getOldestModifiedFailedCard(collapse=True)
            else:
                return
        # if it's not failed, check if it's spaced
        if item.successive or item.reps == 0:
            space = self.itemSpacing(item)
            if space > now:
                # update due time and put it back in future queue
                item.due = max(item.due, space)
                item = self.itemFromItem(FutureItem, item)
                heappush(self.futureQueue, item)
                return self.getCard()
        card = self.s.query(anki.cards.Card).get(item.id)
        card.genFuzz()
        card.startTimer()
        return card

    def getOldestModifiedFailedCard(self, collapse=False):
        # get the oldest modified within collapse.
        if collapse:
            cutoff = time.time() + self.collapseTime
        else:
            cutoff = time.time() + max(self.delay0, self.delay1)
        q = [i for i in self.failedQueue if i.due <= cutoff]
        item = sorted(q, cmp=self.oldestModifiedCmp)[0]
        # remove it from the queue and rebuild
        self.failedQueue.remove(item)
        heapify(self.failedQueue)
        return item

    def answerCard(self, card, ease):
        "Reschedule CARD based on EASE."
        oldState = self.cardState(card)
        lastDelay = max(0, (time.time() - card.due) / 86400.0)
        # update card details
        card.lastInterval = card.interval
        card.interval = self.nextInterval(card, ease)
        card.lastDue = card.due
        card.due = self.nextDue(card, ease, oldState)
        self.updateFactor(card, ease)
        # update fact
        card.fact.lastCard = card
        card.fact.lastCardId = card.id
        # spacing - first, we get the times of all other cards with the same
        # fact
        (smin, ssum, scnt) = self.s.all("""
select min(interval), sum(interval), count(interval) from cards
where factId = :fid and id != :id""", fid=card.factId, id=card.id)[0]
        smin = smin or 0
        ssum = ssum or 0
        space = min(smin, card.interval)
        if not space:
            newSpace = (time.time() +
                        card.fact.model.initialSpacing)
        else:
            newSpace = max(time.time() + (
                space * card.fact.model.spacing * 86400.0),
                           self.delay0+1,
                           self.delay1+1)
        # only update spacing if it's greater than before
        if newSpace > card.fact.spaceUntil:
            card.fact.spaceUntil = newSpace
        # update cache
        self.factSpacing[card.factId] = (card.id, card.fact.spaceUntil)
        card.fact.setModified(textChanged=False)
        # stats
        card.updateStats(ease, oldState) # sets mod
        anki.stats.updateAllStats(self.s, card, ease, oldState)
        # history
        entry = CardHistoryEntry(card, ease, lastDelay)
        self.s.save(entry)
        # add back to queue
        self.addCardToQueue(card)
        self.setModified()
        self.s.flush()

    def addCardToQueue(self, card):
        "Add CARD to the scheduling queue."
        if card.priority == 0:
            return
        if self.cardIsNew(card):
            # acquisition queue
            if self.newCardOrder == 0: acq = AcqRandomItem
            else: acq = AcqOrderedItem
            item = self.itemFromItem(acq, card)
            heappush(self.acqQueue, item)
        elif card.successive == 0:
            # failed
            item = self.itemFromItem(FailedItem, card)
            heappush(self.failedQueue, item)
        else:
            # future
            item = self.itemFromItem(FutureItem, card)
            if card.id != card.fact.lastCardId:
                item.due = max(card.due, card.fact.spaceUntil)
            heappush(self.futureQueue, item)

    def itemFromItem(self, itemClass, item):
        "Create a scheduling item of ITEMCLASS based on ITEM/CARD."
        return itemClass(item.due, item.id, item.modified, item.priority,
                         item.reps, item.successive, item.interval,
                         item.factId, item.ordinal, item.created)

    def addExpiredItem(self, item):
        "Place ITEM on the revision/failed queue."
        if item.successive:
            item = self.itemFromItem(RevItem, item)
            heappush(self.revQueue, item)
        elif item.reps == 0:
            if self.newCardOrder == 0: acq = AcqRandomItem
            else: acq = AcqOrderedItem
            item = self.itemFromItem(acq, item)
            heappush(self.acqQueue, item)
        else:
            item = self.itemFromItem(FailedItem, item)
            heappush(self.failedQueue, item)

    def itemSpacing(self, item):
        "Return the spacing of item, using our cache or the DB."
        # we do this to avoid having to flush changes after every card answer
        if item.factId not in self.factSpacing:
            self.factSpacing[item.factId] = self.s.first(
                "select lastCardId, spaceUntil from facts where id = :id",
                id=item.factId)
        if self.factSpacing[item.factId][0] == item.id:
            # same card has no spacing
            return 0
        return self.factSpacing[item.factId][1]

    def failedCardsDueSoon(self, cutoff=None):
        "Number of failed cards due within delay0/1."
        count = 0
        if not cutoff:
            cutoff = time.time() + max(self.delay0, self.delay1)
        for n in range(len(self.failedQueue)):
            if self.failedQueue[n].due <= cutoff:
                count += 1
        return count

    def collapsedFailedCards(self):
        "Number of cards due within collapse time."
        return self.failedCardsDueSoon(time.time() + self.collapseTime)

    def oldestModifiedCmp(self, a, b):
        return cmp(a.modified, b.modified)

    # Interval management
    ##########################################################################

    def nextInterval(self, card, ease):
        "Return the next interval for CARD given EASE."
        delay = self._adjustedDelay(card, ease)
        # if interval is less than mid interval, use presets
        if (card.interval + delay) < self.midIntervalMin:
            if ease < 2:
                interval = 0
            elif ease == 2:
                interval = random.uniform(self.hardIntervalMin,
                                          self.hardIntervalMax)
            elif ease == 3:
                interval = random.uniform(self.midIntervalMin,
                                          self.midIntervalMax)
            elif ease == 4:
                interval = random.uniform(self.easyIntervalMin,
                                          self.easyIntervalMax)
            interval += delay
        else:
            # otherwise, multiply the old interval by a factor
            if ease == 0:
                factor = 0
            elif ease == 1:
                factor = 1 / card.factor / 2.0
            elif ease == 2:
                factor = 1.2
            elif ease == 3:
                factor = card.factor
            elif ease == 4:
                factor = card.factor * self.factorFour
            interval = (card.interval + delay) * factor * card.fuzz
        if self.maxScheduleTime:
            interval = min(interval, self.maxScheduleTime)
        #print "e=%d f=%0.2f li=%0.2f ci=%0.2f ni=%0.2f, d=%0.2f" % (
        #    ease, card.factor, card.lastInterval, card.interval, interval, delay)
        return interval

    def nextDue(self, card, ease, oldState):
        "Return time when CARD will expire given EASE."
        if ease == 0:
            due =  self.delay0
        elif ease == 1 and oldState != 'mature':
            due =  self.delay1
        elif ease == 1:
            due =  self.delay2
        else:
            due =  card.interval * 86400.0
        return due + time.time()

    def updateFactor(self, card, ease):
        "Update CARD's factor based on EASE."
        card.lastFactor = card.factor
        if self.cardIsBeingLearnt(card) and ease in [0, 1, 2]:
            # only penalize failures after success when starting
            if card.successive and ease != 2:
                card.factor -= 0.20
        elif ease in [0, 1]:
            card.factor -= 0.20
        elif ease == 2:
            card.factor -= 0.15
        elif ease == 4:
            card.factor += 0.10
        card.factor = max(1.3, card.factor)

    def _adjustedDelay(self, card, ease):
        "Return an adjusted delay value for CARD based on EASE."
        if self.cardIsNew(card):
            return 0
        return max(0, (time.time() - card.due) / 86400.0)

    def resetCards(self, ids):
        "Reset progress on cards in IDS."
        strids = ",".join([str(id) for id in ids])
        self.s.statement("""
update cards set interval = 0, lastInterval = 0, lastDue = 0,
factor = 2.5, reps = 0, successive = 0, averageTime = 0, reviewTime = 0,
youngEase0 = 0, youngEase1 = 0, youngEase2 = 0, youngEase3 = 0,
youngEase4 = 0, matureEase0 = 0, matureEase1 = 0, matureEase2 = 0,
matureEase3 = 0,matureEase4 = 0, yesCount = 0, noCount = 0,
modified = :now, due = :now
where id in (%s)""" % strids, now=time.time())
        # undo any spacing
        factIds = self.s.column0(
            "select distinct factId from cards where id in (%s)" %
            strids)
        self.s.statement("""
update facts set spaceUntil = 0, lastCardId = null, modified = :now
where id in (%s)""" % ",".join([str(id) for id in factIds]), now=time.time())
        self.flushMod()

    # Times
    ##########################################################################

    def earliestTime(self):
        """Return the time of the earliest card.
        This may be in the past if the deck is not finished.
        If the deck has no (enabled) cards, return None."""
        self.s.flush()
        return self.s.scalar(self._earliest)

    def earliestTimeStr(self, next=None):
        """Return the relative time to the earliest card as a string."""
        if next == None:
            next = self.earliestTime()
        if not next:
            return _("unknown")
        diff = next - time.time()
        return anki.utils.fmtTimeSpan(diff)

    def nextIntervalStr(self, card, ease):
        "Return the next interval for CARD given EASE as a string."
        delay = self._adjustedDelay(card, ease)
        if card.due > time.time() and ease < 2:
            # the card is not yet due, and we are in the final drill
            return _("a short time")
        if ease < 2:
            interval = self.nextDue(card, ease, self.cardState(card)) - time.time()
        elif (card.interval+delay) < self.midIntervalMin:
            if ease == 4:
                interval = [self.easyIntervalMin, self.easyIntervalMax]
            elif ease == 3:
                interval = [self.midIntervalMin, self.midIntervalMax]
            else:
                interval = [self.hardIntervalMin, self.hardIntervalMax]
            interval[0] = (interval[0] + delay) * 86400.0
            interval[1] = (interval[1] + delay) * 86400.0
            if interval[0] != interval[1]:
                return anki.utils.fmtTimeSpanPair(*interval)
            interval = interval[0]
        else:
            interval = self.nextInterval(card, ease) * 86400.0
        return anki.utils.fmtTimeSpan(interval)

    # Priorities
    ##########################################################################

    def updateAllPriorities(self):
        "Update all card priorities if changed."
        now = time.time()
        newPriorities = []
        tagsList = self.tagsList()
        tagCache = self.genTagCache()
        for (cardId, tags, oldPriority) in tagsList:
            newPriority = self.priorityFromTagString(tags, tagCache)
            if newPriority != oldPriority:
                newPriorities.append({"id": cardId, "pri": newPriority})
        # update db
        self.s.execute(text("""
update cards set priority = :pri, modified = %f where cards.id = :id""" %
                            now),
                          newPriorities)

    def updatePriority(self, card):
        "Update priority on a single card."
        tagCache = self.genTagCache()
        tags = (card.tags + "," + card.fact.tags + "," +
                card.fact.model.tags + "," + card.cardModel.name)
        p = self.priorityFromTagString(tags, tagCache)
        if p != card.priority:
            card.priority = p
            self.flushMod()

    def priorityFromTagString(self, tagString, tagCache):
        tags = parseTags(tagString.lower())
        for tag in tags:
            if tag in tagCache['suspended']:
                return PRIORITY_NONE
        for tag in tags:
            if tag in tagCache['high']:
                return PRIORITY_HIGH
        for tag in tags:
            if tag in tagCache['med']:
                return PRIORITY_MED
        for tag in tags:
            if tag in tagCache['low']:
                return PRIORITY_LOW
        return PRIORITY_NORM

    def genTagCache(self):
        "Cache tags for quick lookup. Return dict."
        d = {}
        t = parseTags(self.suspended.lower())
        d['suspended'] = dict([(k, 1) for k in t])
        t = parseTags(self.highPriority.lower())
        d['high'] = dict([(k, 1) for k in t])
        t = parseTags(self.medPriority.lower())
        d['med'] = dict([(k, 1) for k in t])
        t = parseTags(self.lowPriority.lower())
        d['low'] = dict([(k, 1) for k in t])
        return d

    # Card/fact counts
    ##########################################################################

    def totalCardCount(self):
        return self.s.scalar(
            "select count(id) from cards")

    def totalFactCount(self):
        return self.s.scalar(
            "select count(id) from facts")

    def suspendedCardCount(self):
        return self.s.scalar(
            "select count(id) from cards where priority = 0")

    def oldCardCount(self):
        return self.s.scalar(
            "select count(id) from cards where reps > 0")

    def newCardCount(self):
        return self.s.scalar(
            "select count(id) from cards where reps = 0")

    def pendingFailedCount(self):
        "Number of pending failed cards. Use when queue not rebuilt."
        return self.s.scalar(
            "select count(id) from typedCards where due <= :now and type = 0",
            now=time.time()+self.collapseTime)

    def pendingSuccessiveCount(self):
        "Number of pending review cards. Use when queue not rebuilt."
        return self.s.scalar("select count(id) from typedCards where type = 1")

    def pendingNewCount(self):
        "Number of pending new cards. Use when queue not rebuilt."
        return self.s.scalar("select count(id) from typedCards where type = 2")

    def spacedCardCount(self):
        return self.s.scalar("""
select count(cards.id) from cards, facts where
cards.priority != 0 and
cards.due < :now and
cards.factId = facts.id and
facts.spaceUntil > :now""", now=time.time())

    def isEmpty(self):
        return self.totalCardCount() == 0

    def matureCardCount(self):
        return self.s.scalar(
            "select count(id) from cards where interval >= :t "
            "and reps > 0", t=MATURE_THRESHOLD)

    def youngCardCount(self):
        return self.s.scalar(
            "select count(id) from cards where interval < :t "
            "and reps > 0", t=MATURE_THRESHOLD)

    # Card predicates
    ##########################################################################

    def cardState(self, card):
        if self.cardIsNew(card):
            return "new"
        elif card.interval > MATURE_THRESHOLD:
            return "mature"
        return "young"

    def cardIsNew(self, card):
        "True if a card has never been seen before."
        return card.reps == 0

    def cardIsBeingLearnt(self, card):
        "True if card should use present intervals."
        return card.interval < self.easyIntervalMin

    def cardIsYoung(self, card):
        "True if card is not new and not mature."
        return (not self.cardIsNew(card) and
                not self.cardIsMature(card))

    def cardIsMature(self, card):
        return card.interval >= MATURE_THRESHOLD

    # Stats
    ##########################################################################

    def getStats(self, currentCard=None):
        "Return some commonly needed stats."
        stats = anki.stats.getStats(self.s)
        # add scheduling related stats
        stats['new'] = len(self.acqQueue)
        stats['failed'] = self.failedCardsDueSoon()
        stats['successive'] = len(self.revQueue)
        stats['old'] = stats['failed'] + stats['successive']
        if currentCard:
            q = self.queueForCard(currentCard)
            if q == "rev":
                stats['successive'] += 1
            elif q == "new":
                stats['new'] += 1
            else:
                stats['failed'] += 1
        if stats['dAverageTime']:
            stats['timeLeft'] = anki.utils.fmtTimeSpan(
                stats['dAverageTime'] * (stats['successive'] or stats['new']),
                pad=0, point=1)
        else:
            stats['timeLeft'] = _("Unknown")
        return stats

    def queueForCard(self, card):
        "Return the queue the current card is in."
        if self.cardIsNew(card):
            if card.priority == 4:
                return "rev"
            else:
                return "new"
        elif card.successive == 0:
            return "failed"
        elif card.reps:
            return "rev"
        else:
            sys.stderr.write("couldn't determine queue for %s" %
                             `card.__dict__`)

    # Facts
    ##########################################################################

    def newFact(self):
        "Return a new fact with the current model."
        return anki.facts.Fact(self.currentModel)

    def addFact(self, fact):
        "Add a fact to the deck. Return list of new cards."
        if not fact.model:
            fact.model = self.currentModel
        # the session may have been cleared, so refresh model
        fact.model = self.s.query(Model).get(fact.model.id)
        # validate
        fact.assertValid()
        fact.assertUnique(self.s)
        # and associated cards
        n = 0
        cards = []
        self.s.save(fact)
        self.flushMod()
        for cardModel in fact.model.cardModels:
            if cardModel.active:
                card = anki.cards.Card(fact, cardModel)
                self.flushMod()
                self.updatePriority(card)
                cards.append(card)
                self.addCardToQueue(card)
        # keep track of last used tags for convenience
        self.lastTags = fact.tags
        self.setModified()
        return cards

    def addMissingCards(self, fact):
        for cardModel in fact.model.cardModels:
            if cardModel.active:
                if self.s.scalar("""
select count(id) from cards
where factId = :fid and cardModelId = :cmid""",
                                 fid=fact.id, cmid=cardModel.id) == 0:
                    card = anki.cards.Card(fact, cardModel)
                    self.flushMod()
                    self.updatePriority(card)
                    # not added to queue
        self.setModified()

    def factIsInvalid(self, fact):
        "True if existing fact is invalid. Returns the error."
        try:
            fact.assertValid()
            fact.assertUnique(self.s)
        except FactInvalidError, e:
            return e

    def factUseCount(self, factId):
        "Return number of cards referencing a given fact id."
        return self.s.scalar("select count(id) from cards where factId = :id",
                             id=factId)

    def deleteFact(self, factId):
        "Delete a fact. Removes any associated cards. Don't flush."
        # remove any remaining cards
        self.s.statement("insert into cardsDeleted select id, :time "
                         "from cards where factId = :factId",
                         time=time.time(), factId=factId)
        self.s.statement("delete from cards where factId = :id", id=factId)
        # and then the fact
        self.s.statement("delete from facts where id = :id", id=factId)
        self.s.statement("delete from fields where factId = :id", id=factId)
        self.s.statement("insert into factsDeleted values (:id, :time)",
                         id=factId, time=time.time())
        self.setModified()

    def deleteFacts(self, ids):
        "Bulk delete facts by ID. Assume any cards have already been removed."
        if not ids:
            return
        now = time.time()
        strids = ",".join([str(id) for id in ids])
        self.s.statement("delete from facts where id in (%s)" % strids)
        self.s.statement("delete from fields where factId in (%s)" % strids)
        data = [{'id': id, 'time': now} for id in ids]
        self.s.statements("insert into factsDeleted values (:id, :time)", data)

    # Cards
    ##########################################################################

    def getCardById(self, id):
        return self.s.query(anki.cards.Card).get(id)

    def deleteCard(self, id):
        "Delete a card given its id. Delete any unused facts. Don't flush."
        factId = self.s.scalar("select factId from cards where id=:id", id=id)
        self.s.statement("delete from cards where id = :id", id=id)
        self.s.statement("insert into cardsDeleted values (:id, :time)",
                         id=id, time=time.time())
        if factId and not self.factUseCount(factId):
            self.deleteFact(factId)
        self.setModified()

    def deleteCards(self, ids):
        "Bulk delete cards by ID."
        if not ids:
            return
        now = time.time()
        strids = ",".join([str(id) for id in ids])
        # grab fact ids
        factIds = self.s.column0("select factId from cards where id in (%s)"
                                 % strids)
        # drop from cards
        self.s.statement("delete from cards where id in (%s)" % strids)
        # note deleted
        data = [{'id': id, 'time': now} for id in ids]
        self.s.statements("insert into cardsDeleted values (:id, :time)", data)
        # remove any dangling facts
        ids = self.s.column0("""
select facts.id from facts
where facts.id not in (select factId from cards)""")
        self.deleteFacts(ids)
        self.setModified()

    # Models
    ##########################################################################

    def addModel(self, model):
        if model not in self.models:
            self.models.append(model)
        self.currentModel = model
        self.flushMod()

    def deleteModel(self, model):
        "Delete MODEL, and delete any referencing cards/facts. Maybe flush."
        if self.s.scalar("select count(id) from models where id=:id",
                         id=model.id):
            # delete facts/cards
            self.deleteCards(self.s.column0("""
select cards.id from cards, facts where
facts.modelId = :id and
facts.id = cards.factId""", id=model.id))
            # then the model
            self.s.delete(model)
            self.s.flush()
            if self.currentModel == model:
                models = self.s.column0("select id from models")
                if not models:
                    self.currentModel = None
                else:
                    # need to flush before refreshing deck
                    self.currentModelId = models[0]
            self.s.statement("insert into modelsDeleted values (:id, :time)",
                             id=model.id, time=time.time())
            self.flushMod()
            self.s.refresh(self)
            self.setModified()

    def modelUseCount(self, model):
        "Return number of facts using model."
        return self.s.scalar("select count(facts.modelId) from facts "
                             "where facts.modelId = :id",
                             id=model.id)

    def deleteEmptyModels(self):
        for model in self.models:
            if not self.modelUseCount(model):
                self.deleteModel(model)

    # Fields
    ##########################################################################

    def allFields(self):
        "Return a list of all possible fields across all models."
        return self.s.column0("select distinct name from fieldmodels")

    def deleteFieldModel(self, model, field):
        self.s.statement("delete from fields where fieldModelId = :id",
                         id=field.id)
        self.s.statement("update facts set modified = :t where modelId = :id",
                         id=model.id, t=time.time())
        model.fieldModels.remove(field)
        # update q/a formats
        for cm in model.cardModels:
            cm.qformat = cm.qformat.replace("%%(%s)s" % field.name, "")
            cm.aformat = cm.aformat.replace("%%(%s)s" % field.name, "")
        model.setModified()
        self.flushMod()

    def addFieldModel(self, model, field):
        "Add FIELD to MODEL and update cards."
        model.addFieldModel(field)
        # commit field to disk
        self.s.flush()
        self.s.statement("""
insert into fields (factId, fieldModelId, ordinal, value)
select facts.id, :fmid, :ordinal, "" from facts
where facts.modelId = :mid""", fmid=field.id, mid=model.id, ordinal=field.ordinal)
        # ensure facts are marked updated
        self.s.statement("""
update facts set modified = :t where modelId = :mid"""
                         , t=time.time(), mid=model.id)
        model.setModified()
        self.flushMod()

    def renameFieldModel(self, model, field, newName):
        "Change FIELD's name in MODEL and update FIELD in all facts."
        for cm in model.cardModels:
            cm.qformat = cm.qformat.replace(
                "%%(%s)s" % field.name, "%%(%s)s" % newName)
            cm.aformat = cm.aformat.replace(
                "%%(%s)s" % field.name, "%%(%s)s" % newName)
        field.name = newName
        model.setModified()
        self.flushMod()

    def fieldModelUseCount(self, fieldModel):
        "Return the number of cards using fieldModel."
        return self.s.scalar("""
select count(id) from fields where
fieldModelId = :id and value != ""
""", id=fieldModel.id)

    # Card models
    ##########################################################################

    def cardModelUseCount(self, cardModel):
        "Return the number of cards using cardModel."
        return self.s.scalar("""
select count(id) from cards where
cardModelId = :id""", id=cardModel.id)

    def deleteCardModel(self, model, cardModel):
        "Delete all cards that use CARDMODEL from the deck."
        cards = self.s.column0("select id from cards where cardModelId = :id",
                               id=cardModel.id)
        for id in cards:
            self.deleteCard(id)
        model.cardModels.remove(cardModel)
        model.setModified()
        self.flushMod()

    def updateCardsFromModel(self, cardModel):
        "Update all card question/answer when model changes."
        ids = self.s.all("""
select cards.id, cards.factId from cards, facts, cardmodels
where
cards.factId = facts.id and
facts.modelId = cardModels.modelId and
cards.cardModelId = :id""", id=cardModel.id)
        if not ids:
            return
        pend = [{'q': cardModel.renderQASQL('q', fid),
                 'a': cardModel.renderQASQL('a', fid),
                 'id': cid}
                for (cid, fid) in ids]
        self.s.execute("""
update cards
set
question = :q,
answer = :a,
modified = %f
where id = :id""" % time.time(), pend)

    # Tags
    ##########################################################################

    def tagsList(self):
        "Return a list of (cardId, allTags, priority)"
        return self.s.all("""
select cards.id, cards.tags || "," || facts.tags || "," || models.tags || "," ||
cardModels.name, cards.priority from cards, facts, models, cardModels where
cards.factId == facts.id and facts.modelId == models.id
and cards.cardModelId = cardModels.id""")

    def allTags(self):
        "Return a hash listing tags in model, fact and cards."
        return list(set(parseTags(",".join([x[1] for x in self.tagsList()]))))

    def cardTags(self, ids):
        return self.s.all("""
select id, tags from cards
where id in (%s)""" % ",".join([str(id) for id in ids]))

    def factTags(self, ids):
        return self.s.all("""
select id, tags from facts
where id in (%s)""" % ",".join([str(id) for id in ids]))

    def addCardTags(self, ids, tags, idfunc=None, table="cards"):
        if not idfunc:
            idfunc=self.cardTags
        tlist = idfunc(ids)
        newTags = parseTags(tags)
        now = time.time()
        pending = []
        for (id, tags) in tlist:
            oldTags = parseTags(tags)
            tmpTags = list(set(oldTags + newTags))
            if tmpTags != oldTags:
                pending.append(
                    {'id': id, 'now': now, 'tags': ", ".join(tmpTags)})
        self.s.statements("""
update %s set
tags = :tags,
modified = :now
where id = :id""" % table, pending)
        self.flushMod()

    def addFactTags(self, ids, tags):
        self.addCardTags(ids, tags, idfunc=self.factTags, table="facts")

    def deleteCardTags(self, ids, tags, idfunc=None, table="cards"):
        if not idfunc:
            idfunc=self.cardTags
        tlist = idfunc(ids)
        newTags = parseTags(tags)
        now = time.time()
        pending = []
        for (id, tags) in tlist:
            oldTags = parseTags(tags)
            tmpTags = oldTags[:]
            for tag in newTags:
                try:
                    tmpTags.remove(tag)
                except ValueError:
                    pass
            if tmpTags != oldTags:
                pending.append(
                    {'id': id, 'now': now, 'tags': ", ".join(tmpTags)})
        self.s.statements("""
update %s set
tags = :tags,
modified = :now
where id = :id""" % table, pending)
        self.flushMod()

    def deleteFactTags(self, ids, tags):
        self.deleteCardTags(ids, tags, idfunc=self.factTags, table="facts")

    # File-related
    ##########################################################################

    def name(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    # Media
    ##########################################################################

    def mediaDir(self, create=False):
        "Return the media directory if exists. None if couldn't create."
        if not self.path:
            return None
        dir = re.sub("(?i)\.(anki)$", ".media", self.path)
        if not os.path.exists(dir) and create:
            try:
                os.mkdir(dir)
            except OSError:
                # permission denied
                return None
        if not os.path.exists(dir):
            return None
        return dir

    def addMedia(self, path):
        """Add PATH to the media directory.
Rename for uniqueness if not the same. Return the new name."""
        file = os.path.basename(path)
        location = os.path.join(self.mediaDir(), file)
        location = location.replace('"', "")
        if os.path.exists(location):
            print "uniqueness check NYI"
        else:
            # RLC use copy instead of copy2 for wince test
            shutil.copy(path, location)
        return os.path.basename(location)

    def renameMediaDir(self, oldPath):
        "Copy oldPath to our current media dir. "
        assert os.path.exists(oldPath)
        newPath = self.mediaDir(create=True)
        # copytree doesn't want the dir to exist
        os.rmdir(newPath)
        shutil.copytree(oldPath, newPath)

    # DB helpers
    ##########################################################################

    def save(self):
        "Commit any pending changes to disk."
        if self.lastLoaded == self.modified:
            return
        self.lastLoaded = self.modified
        self.s.commit()

    def close(self):
        self.s.rollback()
        self.s.clear()
        self.engine.dispose()

    def rollback(self):
        "Roll back the current transaction and reset session state."
        self.s.rollback()
        self.refresh()

    def refresh(self):
        "Flush, invalidate all objects from cache and reload."
        self.s.flush()
        self.s.clear()
        self.s.update(self)
        self.s.refresh(self)

    def openSession(self):
        "Open a new session. Assumes old session is already closed."
        self.s = SessionHelper(self.Session(), lock=self.needLock)
        self.refresh()

    def closeSession(self):
        "Close the current session, saving any changes. Do nothing if no session."
        if self.s:
            self.save()
            self.s.expunge(self)
            self.s.close()
            self.s = None

    def setModified(self, newTime=None):
        self.modified = newTime or time.time()

    def flushMod(self):
        "Mark modified and flush to DB."
        self.setModified()
        self.s.flush()

    def saveAs(self, newPath):
        oldMediaDir = self.mediaDir()
        # flush old deck
        self.s.flush()
        # remove new deck if it exists
        try:
            os.unlink(newPath)
        except OSError:
            pass
        # create new deck
        newDeck = DeckStorage.Deck(newPath)
        # attach current db to new
        s = newDeck.s.statement
        s("pragma read_uncommitted = 1")
        s("attach database :path as old", path=self.path)
        # copy all data
        s("delete from decks")
        s("insert into decks select * from old.decks")
        s("insert into fieldModels select * from old.fieldModels")
        s("insert into modelsDeleted select * from old.modelsDeleted")
        s("insert into cardModels select * from old.cardModels")
        s("insert into facts select * from old.facts")
        s("insert into fields select * from old.fields")
        s("insert into cards select * from old.cards")
        s("insert into factsDeleted select * from old.factsDeleted")
        s("insert into reviewHistory select * from old.reviewHistory")
        s("insert into cardsDeleted select * from old.cardsDeleted")
        s("insert into models select * from old.models")
        s("insert into stats select * from old.stats")
        # detach old db and commit
        s("detach database old")
        newDeck.s.commit()
        # close ourself, rebuild queue
        self.s.close()
        newDeck.refresh()
        newDeck.rebuildQueue()
        # move media
        if oldMediaDir:
            newDeck.renameMediaDir(oldMediaDir)
        # and return the new deck object
        return newDeck

mapper(Deck, decksTable, properties={
    'currentModel': relation(anki.models.Model, primaryjoin=
                             decksTable.c.currentModelId ==
                             anki.models.modelsTable.c.id),
    'models': relation(anki.models.Model, post_update=True,
                       primaryjoin=
                       decksTable.c.id ==
                       anki.models.modelsTable.c.deckId),
    })


# Items in the scheduler
##########################################################################
#
# - heapq doesn't support an explicit sort argument, so we need to define
#   objects with their own __cmp__()
# - to minimize memory footprint we inline __init__ instead of subclassing a
#   parent object

# item in failed queue
class FailedItem(object):
    __slots__ = ['due', 'id', 'modified', 'priority', 'reps', 'successive', 'interval',
                 'factId', 'ordinal', 'created']
    def __init__(self, due, id, modified, priority, reps, successive, interval,
                 factId, ordinal, created):
        self.due = due
        self.id = id
        self.modified = modified
        self.priority = priority
        self.reps = reps
        self.successive = successive
        self.interval = interval
        self.factId = factId
        self.ordinal = ordinal
        self.created = created
    def __cmp__(self, other):
        return cmp(self.due, other.due)

# item in revision queue
class RevItem(object):
    __slots__ = ['due', 'id', 'modified', 'priority', 'reps', 'successive', 'interval',
                 'factId', 'ordinal', 'created']
    def __init__(self, due, id, modified, priority, reps, successive, interval,
                 factId, ordinal, created):
        self.due = due
        self.id = id
        self.modified = modified
        self.priority = priority
        self.reps = reps
        self.successive = successive
        self.interval = interval
        self.factId = factId
        self.ordinal = ordinal
        self.created = created
    def __cmp__(self, other):
        # order by priority, then relative delay
        ret = cmp(other.priority, self.priority)
        if ret != 0:
            return ret
        return cmp(self.interval / float(time.time() - self.due),
                   other.interval / float(time.time() - other.due))

# item in random acquisition queue
class AcqRandomItem(object):
    __slots__ = ['due', 'id', 'modified', 'priority', 'reps', 'successive', 'interval',
                 'factId', 'ordinal', 'created']
    def __init__(self, due, id, modified, priority, reps, successive, interval,
                 factId, ordinal, created):
        self.due = due
        self.id = id
        self.modified = modified
        self.priority = priority
        self.reps = reps
        self.successive = successive
        self.interval = interval
        self.factId = factId
        self.ordinal = ordinal
        self.created = created
    def __cmp__(self, other):
        # order by priority, factId, ordinal
        ret = cmp(other.priority, self.priority)
        if ret != 0:
            return ret
        ret = cmp(self.factId, other.factId)
        if ret != 0:
            return ret
        return cmp(self.ordinal, other.ordinal)

# item in ordered acquisition queue
class AcqOrderedItem(object):
    __slots__ = ['due', 'id', 'modified', 'priority', 'reps', 'successive', 'interval',
                 'factId', 'ordinal', 'created']
    def __init__(self, due, id, modified, priority, reps, successive, interval,
                 factId, ordinal, created):
        self.due = due
        self.id = id
        self.modified = modified
        self.priority = priority
        self.reps = reps
        self.successive = successive
        self.interval = interval
        self.factId = factId
        self.ordinal = ordinal
        self.created = created
    def __cmp__(self, other):
        # order by priority, due, ordinal
        ret = cmp(other.priority, self.priority)
        if ret != 0:
            return ret
        ret = cmp(self.created, other.created)
        if ret != 0:
            return ret
        return cmp(self.ordinal, other.ordinal)

# item in future queue
class FutureItem(object):
    __slots__ = ['due', 'id', 'modified', 'priority', 'reps', 'successive', 'interval',
                 'factId', 'ordinal', 'created']
    def __init__(self, due, id, modified, priority, reps, successive, interval,
                 factId, ordinal, created):
        self.due = due
        self.id = id
        self.modified = modified
        self.priority = priority
        self.reps = reps
        self.successive = successive
        self.interval = interval
        self.factId = factId
        self.ordinal = ordinal
        self.created = created
    def __cmp__(self, other):
        return cmp(self.due, other.due)

# Deck storage
##########################################################################

class DeckStorage(object):

    backupDir = os.path.expanduser("~/.anki/backups")
    numBackups = 10

    def newDeckPath():
        # create ~/mydeck(N).anki
        n = 2
        path = os.path.expanduser("~/mydeck.anki")
        while os.path.exists(path):
            path = os.path.expanduser("~/mydeck%d.anki" % n)
            n += 1
        return path
    newDeckPath = staticmethod(newDeckPath)

    def Deck(path=None, rebuild=True, backup=True, lock=True):
        "Create a new deck or attach to an existing one."
        # generate a temp name if necessary
        fd = None
        if path is None:
            path = DeckStorage.newDeckPath()
        if path != -1:
            if isinstance(path, types.UnicodeType):
                path = path.encode(sys.getfilesystemencoding())
            path = os.path.abspath(path)
            #print "using path", path
            if os.path.exists(path) and not fd:
                # attach
                if not os.access(path, os.R_OK | os.W_OK):
                    raise DeckAccessError(_("Can't read/write deck"))
                create = False
            else:
                # create
                if not os.access(os.path.dirname(path), os.R_OK | os.W_OK):
                    raise DeckAccessError(_("Can't read/write directory"))
                create = True
        else:
            create = True
        # attach and sync/fetch deck - first, to unicode
        if not isinstance(path, types.UnicodeType):
            path = unicode(path, sys.getfilesystemencoding())
        # sqlite needs utf8
        (engine, session) = DeckStorage._attach(path.encode("utf-8"))
        s = session()
        try:
            if create:
                deck = DeckStorage._init(s)
            else:
                deck = s.query(Deck).get(1)
            # attach db vars
            deck.path = path
            deck.engine = engine
            deck.Session = session
            deck.needLock = lock
            deck.s = SessionHelper(s, lock=lock)
            DeckStorage._addViews(deck.s, create)
        except OperationalError, e:
            if (str(e.orig).startswith("database table is locked") or
                str(e.orig).startswith("database is locked")):
                raise DeckAccessError(_("File is in use by another process"),
                                      type="inuse")
            else:
                raise e
        # rebuild?
        if rebuild:
            deck.rebuildQueue()
        deck._initVars()
        deck.s.commit()
        # rotate backups
        if not create and backup:
            DeckStorage.backup(deck.modified, path)
        return deck
    Deck = staticmethod(Deck)

    def _attach(path):
        "Attach to a file, initializing DB"
        if path == -1:
            path = "sqlite:///:memory:"
        else:
            path = "sqlite:///" + path
        engine = create_engine(path,
                               strategy='threadlocal',
                               connect_args={'timeout': 0})
        session = sessionmaker(bind=engine,
                               autoflush=False,
                               transactional=False)
        try:
            metadata.create_all(engine)
        except DBAPIError, e:
            engine.dispose()
            raise DeckWrongFormatError("Deck is not in the right format")
        return (engine, session)
    _attach = staticmethod(_attach)

    def _init(s):
        "Add a new deck to the database. Return saved deck."
        deck = Deck()
        s.save(deck)
        s.flush()
        return deck
    _init = staticmethod(_init)

    def _addViews(s, create):
        # old tables
        s.statement("drop view if exists failedCards")
        s.statement("drop view if exists acqCards")
        s.statement("drop view if exists revCards")
        s.statement("drop view if exists futureCards")
        # types:
        # 0 - failed
        # 1 - rev
        # 2 - acq
        # 3 - future
        s.statement("drop view if exists typedCards")
        s.statement("""
create view typedCards as
select
(case
-- failed cards
when reps != 0 and successive = 0
then 0
-- due
when
due < strftime('%s', 'now')
and (lastCardId is null or
     lastCardId = cards.id or
     spaceUntil < strftime('%s', 'now'))
then
case
-- revision
when priority != 1 and
(priority = 4 or (reps != 0 and successive != 0))
then 1
-- acquisition
when priority != 4 and
(reps = 0 or priority = 1)
then 2
end
else 3
end) as type,
(case
when (reps != 0 and successive = 0) or cards.id = facts.lastCardId
then cards.due
else max(cards.due, facts.spaceUntil) end) as due, *
from cards, facts where
cards.factId = facts.id
and cards.priority != 0""")
    _addViews = staticmethod(_addViews)

    def backup(modified, path):
        # need a non-unicode path
        path = path.encode(sys.getfilesystemencoding())
        backupDir = DeckStorage.backupDir.encode(sys.getfilesystemencoding())
        numBackups = DeckStorage.numBackups
        def backupName(path, num):
            path = os.path.abspath(path)
            path = path.replace("\\", "!")
            path = path.replace("/", "!")
            path = path.replace(":", "")
            path = os.path.join(backupDir, path)
            path = re.sub("\.anki$", ".backup-%d.anki" % num, path)
            return path
        if not os.path.exists(backupDir):
            os.makedirs(backupDir)
        # if the mod time is identical, don't make a new backup
        firstBack = backupName(path, 0)
        if os.path.exists(firstBack):
            s1 = int(modified)
            s2 = int(os.stat(firstBack)[stat.ST_MTIME])
            if s1 == s2:
                return
        # remove the oldest backup if it exists
        oldest = backupName(path, numBackups)
        if os.path.exists(oldest):
            os.chmod(oldest, 0666)
            os.unlink(oldest)
        # move all the other backups up one
        for n in range(numBackups - 1, -1, -1):
            name = backupName(path, n)
            if os.path.exists(name):
                newname = backupName(path, n+1)
                if os.path.exists(newname):
                    os.chmod(newname, 0666)
                    os.unlink(newname)
                os.rename(name, newname)
        # save the current path
        newpath = backupName(path, 0)
        if os.path.exists(newpath):
            os.chmod(newpath, 0666)
            os.unlink(newpath)
        # RLC replaced with next line for wince        shutil.copy2(path, newpath)
        shutil.copy(path, newpath)
        # set mtimes to be identical
        # RLC remove utime stuff for wince os.utime(newpath, (modified, modified))
    backup = staticmethod(backup)