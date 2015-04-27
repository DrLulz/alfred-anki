#!/usr/bin/python
# encoding: utf-8

########################################################
# Currently a hot mess...
# This needs to be cleaned up...


class AnkiFx(str):
    
    def __init__(self, apath):
        from anki import Collection as aopen  
        self.col = aopen(apath)
        self.dm  = self.col.decks
        self.mm  = self.col.models   

    def create_deck(self, title):
        self.col.decks.id(title)
        self.col.save()
        self.col.close()
    
    def create_card(self, did, data):
    
        mname = 'Alfred Dark'

        deck = self.dm.get(did)
        self.dm.select(deck['id'])

        model = self.mm.byName(mname)
        if model is None:
            model = self.dark_theme(mname)

        model['did'] = deck['id']
        self.mm.save(model)
        self.mm.setCurrent(model)

        card = self.col.newNote(forDeck=False)
        #for name in card.keys():

        card['Note ID'] = str(card.id)
        card['Front']   = data[0]
        card['F Note']  = ''
        card['Back']    = data[1]
        card['B Note']  = ''
        card['class']   = ''
        card['Noty']    = ''     
        card['http']    = '' 
        card['video']   = ''             
        self.col.addNote(card)
        self.col.save()
        self.col.close()
        
        
        
    def dark_theme(self, name):
        import os
        abspath = os.path.abspath(__file__)
        
        path  = os.path.dirname(abspath) + '/template'
        f = path + '/front.txt'
        c = path + '/css.txt'
        b = path + '/back.txt'
    
        with open(f, 'r') as ft, open(c, 'r') as ct, open (b, 'r') as bt:
            ftemp = ft.read()
            css   = ct.read()
            btemp = bt.read()

        m  = self.mm.new(name)

        fld = self.mm.newField('Note ID'); self.mm.addField(m, fld)
        fld = self.mm.newField('Front');   self.mm.addField(m, fld)
        fld = self.mm.newField('F Note');  self.mm.addField(m, fld)
        fld = self.mm.newField('Back');    self.mm.addField(m, fld)
        fld = self.mm.newField('B Note');  self.mm.addField(m, fld)
        fld = self.mm.newField('class');   self.mm.addField(m, fld)
        fld = self.mm.newField('Noty');    self.mm.addField(m, fld)
        fld = self.mm.newField('http');    self.mm.addField(m, fld)
        fld = self.mm.newField('video');   self.mm.addField(m, fld)

        m['css'] = css

        t = self.mm.newTemplate('Card 1')
        t['qfmt'] = ftemp
        t['afmt'] = btemp
        self.mm.addTemplate(m, t)
        self.mm.add(m)
        return m
        
        
    def children(self, did):
        return self.dm.children(did)
    
    '''
    def did2cids(self, **kwargs):
        options = {'did' : None, 'mid' : None}
        options.update(kwargs)
        
        if options['did']:
            return self.dm.cids(options['did'], children=True)
            
        if options['mid']:
            return self.mm.get(options['mid'])
    '''

#    self.col.close()
        

class Tools(str):
    
    import sqlite3, json
    
    def __init__(self, col):
        self.col = col
        self.db  = self.sqlite3.connect(self.col)


    def all_decks(self):
        '''Returns a list of dicts with all deck info'''
    
        # name, extendRev, collapsed, browserCollapsed,
        # newToday, timeToday, extendNew, conf, revToday
        # lrnToday, id, mod

        results = []
    
        decks = self.db.execute("SELECT decks FROM col")                     
        decks = self.json.loads(decks.fetchone()[0])

        for id, deck in decks.items():
            results.append(deck)

        return results


    def deck_info(self, **kwargs):
        '''Returns deck info by -// name or did //-,
           if by name can be more than one deck
           to account for parent decks unless
           the full deck name is provided.'''
       
        options = {'did' : None, 'name' : None}
        options.update(kwargs)
        #self.db.row_factory = sqlite3.Row
        
        decks = self.db.execute("SELECT decks FROM col")
        decks = self.json.loads(decks.fetchone()[0])
    
        results = []
    
        for id, deck in decks.items():
            if options['did']:
                if id == options['did']:   
                    return deck
            if options['name']:
                if deck['name'] == options['name']:
                    results.append(deck)

        return results[0]



    def all_configs(self):
        '''These are the deck options'''
        # name replayq lapse rev timer dyn
        # maxTaken usn new mod id autoplay
    
        configs = self.db.execute("SELECT dconf FROM col")    
        configs = self.json.loads(configs.fetchone()[0])
    
        results = []
    
        for id, conf in configs.items():
            results.append(conf)
    
        return results




    def model_info(self, mid=None):
        '''A lot of info here'''
        #raise Exception('are you sure?')
        # name tags did usn req flds sortf
        # tmpls mod latexPost latexPre
        # type id css
        for _ in range(2):
            try:
                models = self.db.execute("SELECT models FROM col")
                models = self.json.loads(models.fetchone()[0])
                break
            except OperationalError:
                self.db.execute("PRAGMA busy_timeout = 30000")
                pass
        else:
            raise Exception('database is busy')

        #models = self.db.execute("SELECT models FROM col")    
        #models = self.json.loads(models.fetchone()[0])
    

        for id, model in models.items():
            if id == mid:
                return model




    def card_info(self, **kwargs):

        # id nid did ord mod usn queue
        # due ivl factor reps lapses 
        # left odue odid flags data
    
    
        options = {'nid' : None, 'did' : None, 'count' : False}
        options.update(kwargs)
    
    
    
        # card count by deck id
        # card_info(db, did=DID, count=True)
    
    
        if options['did'] and options['count'] is True:
        
            cards_did = self.db.execute("SELECT COUNT(*) "
                                            "FROM cards "
                                            "WHERE cards.did = ?", (options['did'],) )
                    
            card_count = cards_did.fetchone()
            return card_count[0]
    
    
    
        # card_info(db, nid=NID)
    
        elif options['nid']:

            rows = self.db.execute("SELECT * FROM cards WHERE cards.nid = ?", (options['nid'],))
        
            colname = [ d[0] for d in rows.description ]
            for r in rows.fetchall():
                card = dict((colname[i], r[i]) for i in range(len(colname)))
                return card



        # card_info(db, did=DID)

        elif options['did']:

            results = []
        
            rows = self.db.execute("SELECT cards.id, nid, cards.did, ord, cards.mod, cards.usn, queue, due, ivl, factor, reps, lapses, left, odue, odid, cards.flags, cards.data "
                                 "FROM cards "
                                 "JOIN notes ON notes.id = cards.nid "
                                 "WHERE cards.did = ?", (options['did'],) )
        

            colname = [ d[0] for d in rows.description ]        
            for r in rows:
                card = dict((colname[i], r[i]) for i in range(len(colname)))
                results.append(card)
       
            return results



    def card_spec(self, v, **kwargs):
        '''Return a specific value. May not be
           needed, as this value is returned
           by card_info() along with all the 
           other values '''
           
        # card_spec(db, 'due', did='1419424106618')
        # card_spec(db, 'due', nid='1419441282918')
        # card_spec(db, 'queue', nid='1419441282918')
        # card_spec(db, 'due', cid='1419441341030')
        # card_spec(db, 'did', cid='1419441341030')

        results = []

        sel = {'v':('card_' + v)}

        options = {'cid' : None, 'nid' : None, 'did' : None}
        options.update(kwargs)
    
        if options['cid']:
            key, value = 'id', options['cid']
        elif options['nid']:
            key, value = 'nid', options['nid']
        elif options['did']:
            key, value = 'did', options['did']
    
    
        rows = self.db.execute("SELECT cards.id, cards.nid, cards.did, cards.ord, cards.mod, cards.usn, cards.queue, cards.due, cards.ivl, cards.factor, cards.reps, cards.lapses, cards.left, cards.odue, cards.odid, cards.flags, cards.data "
                             "FROM cards "
                             "JOIN notes ON notes.id = cards.nid "
                             "WHERE cards."+key+" = ?", (value,) )

        for card in rows:
            card_id, card_nid, card_did, card_ord, card_mod, card_usn, card_queue, card_due, card_ivl, card_factor, card_reps, card_lapses, card_left, card_odue, card_odid, card_flags, card_data = card
            results.append(vars()[sel['v']])
    
        return results


    def dids2cids(self, dids):
        return self.db.execute("select id from cards where did in " + dids)

    def cid2nid(self, card_id):
        row = self.db.execute("select nid from cards where id = ?", (card_id,)).fetchone()
        if row:
            return row['nid']
        return None
        
    def nid2cids(self, note_id, return_deck_id=False):
        # one to many relation
        
        card_ids = []
        deck_id = None
        for row in conn.execute("select id,did from cards where nid = ?", (note_id,)):
            card_ids.append(row['id'])
            deck_id = row['did']
        if return_deck_id:
            return card_ids, deck_id
        return card_ids
        
        
    def note_info(self, **kwargs):
        # id guid mod usn tags flds sfld csum flags data mid
        # note_info(db, nid='1232312', count=True)

    
        options = {'nid' : None, 'count' : False}
        options.update(kwargs)
    

        if options['count'] is True:        
            notes = db.execute("SELECT count() FROM notes")
            total_notes = notes.fetchone()[0]
            return total_notes
        
                
        elif options['nid']:

            rows = self.db.execute("SELECT * FROM notes WHERE notes.id = ?", (options['nid'],))
        
            colname = [ d[0] for d in rows.description ]
            for r in rows.fetchall():
                return dict((colname[i], r[i]) for i in range(len(colname)))

        else:
            '''A lot of info (ALL NOTES)'''
            raise Exception('are you sure?')
            results = []
            rows = self.db.execute("SELECT * FROM notes")
            colname = [ d[0] for d in rows.description ]
    
            for r in rows.fetchall():
                note = dict((colname[i], r[i]) for i in range(len(colname)))
                results.append(note)
        
            return results



    def note_spec(self, v, **kwargs):
        '''Return a specific value. May not be
           needed, as this value is returned
           by note_info() along with all the 
           other values '''
           
        # id guid mod usn tags flds sfld csum flags data mid
    
        # note_spec(db, 'mid', nid=1264521038872)
        # note_spec(db, 'tags', nid=1264521038872)
        # note_spec(db, 'id', mid=1204533978) # all note ids with mid

        #guid: f#z!8<!TCo
        #id: 1264521038872
        results = []
    
        sel = {'v':('note_' + v)}

        options = {'nid' : None, 'tags' : None, 'mid' : None}
        options.update(kwargs)
    
        if options['nid']:
            key, value = 'id', options['nid']
        elif options['tags']:
            key, value = 'tags', options['tags']
        elif options['mid']:
            key, value = 'mid', options['mid']
        
        try:
            rows = self.db.execute("SELECT notes.id, notes.guid, notes.mod, notes.usn, notes.tags, notes.flds, notes.sfld, notes.csum, notes.flags, notes.data, notes.mid "
                                 "FROM notes "
                                 "WHERE notes."+key+" = ?", (value,) )
        except UnboundLocalError:
            return None
            
        for note in rows:
            note_id, note_guid, note_mod, note_usn, note_tags, note_flds, note_sfld, note_csum, note_flags, note_data, note_mid = note
            results.append(vars()[sel['v']])
    
        return results
        

    
    def cnt_cards(self, did, name):
        cnt = self.card_info(did=did, count=True)
        if cnt > 0:
            return cnt
        else:
            matches = self._match_(name)
            #afx = AnkiFx(self.col)
            #matches = afx.children(did)
            return self.sum_cards(matches)
            

        
    def _stat(self, did, multi=False):
        cards = self.card_info(did=did)
        new = learning = review = 0
        for c in cards:
    
            if c['queue'] == 2:
                review += 1
            elif c['queue'] == 0:
                new += 1
            elif (c['queue'] == 1) or (c['queue'] == 3):
                learning += 1
        
        if multi is True:
            return {'new': new, 'learning': learning, 'review': review}
            
        if not (new == 0) and (learning == 0) and (review == 0):
            return {'new': new, 'learning': learning, 'review': review}
        else:
            return None
    
    
    
    def multi_stat(self, decks):
        from collections import Counter
        results = []

        for d in decks:
            stats = self._stat(d['id'], multi=True)
            results.append(stats)
        
        combine = Counter()
        for dic in results:
            combine.update(dic)
        
        return dict(combine)
        
        
        
    def deck_stats(self, did, name):
        
        stats = self._stat(did)
        
        if stats is None:
            matches = self._match_(name)
            return self.multi_stat(matches)
            
        return stats



   
    def base_name(self, name):
        return name.rsplit('::', 1)[0]
        #return name.split('::')[0]


    def _match_(self, base):
        '''match deck name against all names
        return all children if base name'''

        # name, extendRev, collapsed, browserCollapsed,
        # newToday, timeToday, extendNew, conf, revToday
        # lrnToday, id, mod
        
        results = []
        all_decks = self.all_decks()
        
        for d in all_decks:
            did  = d['id']        
            name = d['name']

            if base in name:
                results.append({'id': did, 'name': name})

        return results
        
        '''
        results = []
        key = [dk] #['name']
    
        for d in all_decks:
            d1 = {k: d[k] for k in (key)}
            d2 = {k:v for k, v in d1.items() if dv in str(v)}
        
            if len(d2.keys()):
                results.append(d2)

        return results
        '''


    def sum_cards(self, matches):
        
        cnt = []
        for match in matches:
            cnt.append(self.card_info(did=match['id'], count=True))
        
        return sum(cnt)
        
        '''
        for match in matches:
            name, did = match
            cnt.append(self.card_info(did=did, count=True))
        
        return sum(cnt)
        '''
        
    def cids(self, did, utils):
    
        dids = [did]
        DECK = self.deck_info(did=did)
        NAME = DECK['name']
        kids = self._match_(NAME)
        kid_list = ()
        for k in kids:
            deck, name = k.values()
            kid_list = kid_list + ((deck, name),)
        
        for id, name in kid_list:
            dids.append(id)
        
        _list = list(self.dids2cids(utils.ids2str(dids)))
        return [i for sub in _list for i in sub]
        
        
        
    def deck_notes(self, did):
        import re, os
        from anki import utils
        
        #afx = AnkiFx(self.col)
        #cids = afx.did2cids(did=did)
        cids = self.cids(did, utils)
        
        components = self.col.split(os.sep)
        mediadir = ('/'.join(components[:-1]) + '/collection.media')
        
        nids = []
        for cid in cids:
            card = self.card_spec('nid', cid=cid)
            nids.append(card[0])
        
        notes = []
        for nid in nids:
    
            ndict = {'nid': None, 'flds': None, 'tags': None, 'mid': None, 'mname': None, 'img': None}

            # note info for each note id
            note = self.note_info(nid=nid)

            # readable note fields, strip HTML
            flds = filter(None, note['flds'].split('\x1f'))
            m = lambda i: [re.findall('src="([^"]+)"', f, re.DOTALL) for f in i]
            img = [x[0] for x in m(flds) if x]
            f = lambda x: [utils.stripHTMLMedia(i) for i in x]
            flds = f(flds)
            
            #f = lambda x: [utils.stripHTMLMedia(i) for i in x]
            #flds = f(filter(None, note['flds'].split('\x1f')))

            # from note model id, retrieve model fields
            mid = str(note['mid'])

            #model = afx.did2cids(mid=mid)    
            model = self.model_info(mid=mid)

            # get field names for model
            mflds = [mfld['name'] for mfld in model['flds']]
    
            ndict['nid']   = nid
            #ndict['flds']  = (' '.join(flds)).encode('utf-8')
            ndict['flds']  = flds
            ndict['tags']  = note['tags']
            ndict['mid']   = mid
            ndict['mname'] = model['name']
            if img:
                ndict['img']   = '{}/{}'.format(mediadir, img[0])
    
            notes.append(ndict)

        return notes
        
    def create_tags(self, nid, tags):
        import time

        try:
            tags = [t.replace('#', '') for t in tags[0].split()]
        except AttributeError:
            tags = None
                
        if tags is None:
            tagsstr = ''
        else:            
            tagsstr = ' {} '.format(' '.join(tags))

        self.db.execute('UPDATE notes SET tags=?,mod=?,usn=? WHERE id=?', (tagsstr, int(time.time()), -1, nid))
        self.db.commit()
        self.db.close()
        return tags