#!/usr/bin/python
# encoding: utf-8

import os
from lib.workflow import Workflow
from lib.atools import Tools

__usage__ = """
background.py <action>

Usage:
    background.py decks
    background.py cards

Arguments:
    <name>     Deck name

Options:
    -h, --help      Show this help text

"""


# --------------------------------------------
# Process decks for Alfred

def db_decks(at):

    results =[]
    decks = at.all_decks()

    for d in decks:
        deck = {'id': None, 'title': None, 'cards': None, 'new': None, 'review': None}

        deck['id']    = str(d['id'])
        deck['title'] = d['name']
        deck['cards'] = str(at.cnt_cards(d['id'], d['name']))

        stats = at.deck_stats(deck['id'], deck['title'])
        n, r, l = stats['new'], stats['review'], stats['learning']
        deck['new'] = n
        deck['review'] = r+l

        results.append(deck)
    
    return results


# --------------------------------------------
# Create thumbnail for Alfred results

def create_thumb(img, Image):
    cachedir = wf.cachedir
    size = (250, 250)
    name = img.split('/')[-1]
    
    thumb = '{}/thumbs/thumb-{}'.format(cachedir, name)
    log.debug('\n\nTHUMB PATH: {}'.format(thumb))
    
    if os.path.exists(thumb):
        return thumb
        
    mediadir = '/'.join(thumb.split('/')[:-1])
    if not os.path.exists(mediadir):
        os.makedirs(mediadir)
    
    im = Image.open(img)
    im.thumbnail(size)
    im.save(thumb)
    return thumb
    

# --------------------------------------------
# Process cards for Alfred

def db_cards(at, did):
    
    results = []
    notes = at.deck_notes(did)
    
    for n in notes:
        note = {'nid': None, 'flds': None, 'tags': None, 'mid': None, 'mname': None, 'img': None}
        
        flds = u' '.join(n['flds'])
        
        note['nid']   = n['nid']
        note['flds']  = wf.fold_to_ascii(flds)
        note['tags']  = n['tags']
        note['mid']   = n['mid']
        note['mname'] = n['mname']
        if n['img']:
            from PIL import Image
            img = create_thumb(n['img'], Image)
            note['img']   = img
        
        results.append(note)
    
    return results


def main(wf):
    from docopt import docopt
    args = docopt(__usage__, argv=wf.args)
    
    log.debug('wf.args : {!r}'.format(wf.args))
    log.debug('args : {!r}'.format(args))

    
    # --------------------------------------------
    # Update Decks
    
    if args.get('decks'):

        def wrapper():
            return db_decks(at)

        decks = wf.cached_data('decks', wrapper, max_age=1)
        log.debug('{} anki decks cached'.format(len(decks)))
        print('Collection updated')
        
        
    # --------------------------------------------
    # Update Cards
    
    if args.get('cards'):
        
        did = wf.cached_data('did', None, max_age=0)

        def wrapper():
            return db_cards(at, str(did))

        cards = wf.cached_data(did, wrapper, max_age=1)
        log.debug('{} anki cards cached'.format(len(cards)))
        print('Deck updated')



if __name__ == '__main__':
    wf = Workflow(libraries=[os.path.join(os.path.dirname(__file__), 'lib')])
    log = wf.logger
    at = Tools(wf.settings.get('anki_path', None))    
    wf.run(main)