#!/usr/bin/python
# encoding: utf-8
# DrLulz Apr-2015
########################################################
# The structure of this script is borrows *heavily*
# from the FuzzyFolders and Reddit workflows.
# https://github.com/deanishe/alfred-fuzzyfolders
# https://github.com/deanishe/alfred-reddit
# http://www.packal.org/users/deanishe
# http://www.deanishe.net/alfred-workflow/index.html


#from __future__ import unicode_literals, print_function
import os, sys, re, subprocess
from lib.workflow import (Workflow, ICON_NOTE, ICON_WARNING,
                      ICON_INFO, ICON_SETTINGS, ICON_ERROR, ICON_SYNC,
                      MATCH_ALL, MATCH_ALLCHARS)
from lib.workflow.background import run_in_background, is_running


__usage__ = """
anki.py <action> <query>

Usage:
    anki.py set <query>
    anki.py apath <query>
    anki.py list <query>

Arguments:
    <query>     Search query

Options:
    -h, --help      Show this help text

"""

log = None
DELIMITER = '‣'
ICON = 'icon.png'
UPDATE_SETTINGS = {'github_slug': 'DrLulz/alfred-anki'}


def get_col():
    #Try to locate Anki's collection path automatically
    import glob

    default_locations = [os.environ['HOME']+'/Anki/User 1/collection.anki2',
                         os.environ['HOME']+'/.anki/User 1/collection.anki2',
                         'collection.anki2']

    for location in default_locations:
        if os.path.exists(location):
            return location

    home_path = os.path.expanduser('~')
    pattern = (home_path + '/**' + '/Anki' + '/*' + '/collection.anki2')
    col_path = glob.glob(pattern)
    
    if col_path:
        return col_path[0]
    else:
        return None



class Anki_WF(object):

    def __init__(self, wf):
        self.wf = wf
        self.query = None
        self.apath = self.wf.settings.get('anki_path', None)
        
        
    def run(self, args):

        self.args = args


        # --------------------------------------------
        # If Anki collection path isn't set, blow up
         
        if not self.apath and not self.args.get('apath'):
            self.apath = get_col()
            if self.apath is None:
                self.wf.add_item(
                    title    = "Run ':apath', or press return to set the collection path",
                    arg      = 'trigger apath',
                    valid    = True,
                    icon     = ICON_WARNING)
                self.wf.send_feedback()
                return 0
            elif self.apath:
                self.wf.settings['anki_path'] = self.apath
            return


        # --------------------------------------------
        # Updates

        if wf.update_available:
            wf.add_item('A newer version is available',
                        '↩ to install update',
                        autocomplete='workflow:update',
                        icon='icons/update-available.png')
                        
                        
        self.query = args['<query>']
#        log.debug('------------> QUERY:{!r}'.format(self.query))


        actions = ('set', 'apath', 'list')

        for action in actions:
            if args.get(action):
                methname = 'do_{}'.format(action.replace('-', '_'))
                meth = getattr(self, methname, None)
                if meth:
                    return meth()
                else:
                    break

        raise ValueError('Unknown action : {}'.format(action))


    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Show all decks in Anki collection

    def do_list(self):
        
        
        # --------------------------------------------
        # Parse query

        # :anki ‣dq ‣cq ‣q
        # :anki ‣ deck (delim1) card (delim2) card options
        
        m = re.match(u'([^‣]+)(‣)?([^‣]+)?(‣)?([^‣]+)?', self.query)
        dq, delim1, cq, delim2, q = m.groups()

#        log.debug('------------> Deck Query:{!r}'.format(dq))
#        log.debug('------------> Delim1:{!r}'.format(delim1))
#        log.debug('------------> Card Query:{!r}'.format(cq))
#        log.debug('------------> Delim2:{!r}'.format(delim2))
#        log.debug('------------> Note Query:{!r}'.format(q))
        
        
        # --------------------------------------------
        # Start searching for available decks
        
        if not delim1:
            
            decks = wf.cached_data('decks', None, max_age=0)
            
            
            if not wf.cached_data_fresh('decks', max_age=43200):
                cmd = ['/usr/bin/python', wf.workflowfile('background.py'), 'decks']
#                log.debug('UPDATE DECKS CMD: {!r}'.format(cmd))
                run_in_background('decks', cmd)
                     
            
            if is_running('decks'):
                self.wf.add_item('Keep typing...', valid=False, icon=ICON)                
                self.wf.add_item('Updating deck info... wait one...', valid=False, icon=ICON_SYNC)


            def key_for_deck(deck):
                return '{} {}'.format(deck['title'], deck['id'])
                
            if self.query and decks:
                decks = wf.filter(dq, decks, key_for_deck, match_on=MATCH_ALL ^ MATCH_ALLCHARS)
        
            
            # --------------------------------------------
            # Offer to create a new deck if no matches
            
            if not decks:
                if not is_running('decks'):
                    new_deck = 'deck new "{}"'.format(dq)
            
                    self.wf.add_item(
                        title    = 'Deck not found. Create "{}"?'.format(dq),
                        subtitle = 'Press return to create new deck.',
                        arg      = new_deck,
                        valid    = True,
                        icon     = ICON_WARNING)
            
                self.wf.send_feedback()
                return 0
            
            
            # --------------------------------------------
            # Loop through decks and send to Alfred
            
            for deck in decks:
                self.wf.add_item(
                    title        = deck['title'],
                    subtitle     = 'Cards:{}   New:{}   Review:{}'.format(deck['cards'], deck['new'], deck['review']),
                    autocomplete = wf.decode('{} ‣'.format(deck['title'])),
                    uid          = wf.decode(deck['id']),
                    icon         = ICON)

            self.wf.send_feedback()


        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        # Deck selected, Searching cards
        
        if delim1 and not delim2:
            def did_wrapper():
                from lib.atools import Tools
                at = Tools(self.apath)
                did = at.deck_info(name=dq.strip())
                return did['id']
            
            did = wf.cached_data('did', did_wrapper, max_age=1)
            log.debug('------------> SELECTED DID:{!r}'.format(did))
            did = str(did)


            cards = wf.cached_data(did, None, max_age=0)
    
            if not wf.cached_data_fresh(did, max_age=43200):
                     cmd = ['/usr/bin/python', wf.workflowfile('background.py'), 'cards']
#                     log.debug('UPDATE CARDS CMD: {!r}'.format(cmd))
                     run_in_background('cards', cmd)
        
        
            if is_running('cards'):
                self.wf.add_item('Updating cards... wait one...', valid=False, icon=ICON_SYNC)         

            
            # --------------------------------------------
            # Prompt user to search cards
            
            if not cq:
                self.wf.add_item(
                    title    = 'Search for cards...',
                    subtitle = '',
                    arg      = did,
                    valid    = False,
                    icon     = ICON)

    
            def key_for_card(card):
                tags = ' '.join(list('#' + t for t in card['tags'].split()))
#                log.debug('------------> CARD KEY FLDS:{!r}'.format(card['flds']))
#                log.debug('------------> CARD KEY TAGS:{!r}'.format(tags))
                return '{} {}'.format(card['flds'], tags)


            if cq and cards:
                cards = wf.filter(cq, cards, key_for_card, match_on=MATCH_ALL ^ MATCH_ALLCHARS)
        
            
            # --------------------------------------------
            # Offer to create new card in selected deck
            
            self.wf.add_item(
                title    = 'New Card',
                subtitle = 'Create card in {}'.format(dq),
                arg      = 'trigger card',
                valid    = True,
                icon     = ICON)
            
            
            if not cards:
                if cq:
                    self.wf.add_item(
                        title    = "Cant find '{}' in deck '{}'".format(cq, dq),
                        subtitle = "",
                        valid    = False,
                        icon     = ICON_WARNING)
                self.wf.send_feedback()
                return 0

            
            for card in cards:
                
                if card['img'] is None:
                    card['img'] = ICON

                tags = ' '.join(list('#' + t for t in card['tags'].split()))
        
                self.wf.add_item(
                    title    = (card['flds']).encode('utf-8'),
                    subtitle = tags,
                    autocomplete=wf.decode('{} ‣{} ‣'.format(dq, str(card['nid']))),
                    icon     = card['img'])

            self.wf.send_feedback()
        
        
        # --------------------------------------------
        # Save the note id in cache
        
        def nid_wrapper():
            return cq.strip()
        
        nid = wf.cached_data('nid', nid_wrapper, max_age=1)
        log.debug('------------> SELECTED NID:{!r}'.format(nid))
        
        
        # --------------------------------------------
        # Card selected, show options
         
        self.wf.add_item(
            title    = 'Modify tags for this card...',
            subtitle = 'press return',
            arg      = 'trigger tags',
            valid    = True,
            icon     = ICON)

        self.wf.send_feedback()
        return 0
      
        
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Settings

    def do_set(self):
        
        apath = {'title': 'Set anki collection path',
                 'subtitle': 'Example: /Users/.../Documents/Anki/.../collection.anki2',
                 'arg': 'trigger apath',
                 'uid': u'5c38d8fff8d80dab02f70318bfec8d',
                 'valid': True,
                 'icon': ICON_SETTINGS}

        update = {'title': 'Update collection',
                 'subtitle': 'Refresh cards in decks',
                 'arg': 'update col',
                 'uid': u'109818cfaccb5d1bb41df56c81995e',
                 'valid': True,
                 'icon': ICON_SETTINGS}
                 

        settings = [apath, update]
        
        for setting in settings:
            self.wf.add_item(
                title    = setting['title'],
                subtitle = setting['subtitle'],
                arg      = setting['arg'],
                uid      = setting['uid'],
                valid    = setting['valid'],
                icon     = setting['icon'])
        self.wf.send_feedback()
        return 0
    

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # If get_col() failed, user should set the collection path manually
    # the following aims to simplify this process
    
    def do_apath(self):
        apath = self.query
        m = re.match(u'(.+\/Anki\/.+\/)', apath)
        
        
        if not apath.endswith('.anki2'):
            
            if not 'Anki' in apath:
                self.wf.add_item(
                    title    = "Keep typing...",
                    subtitle = "",
                    valid    = False,
                    icon     = ICON_NOTE)
                self.wf.send_feedback()
                
            if m:
                self.wf.add_item(
                    title    = "The path must end with collection.anki2",
                    subtitle = "",
                    valid    = False,
                    icon     = ICON_WARNING)
                self.wf.send_feedback()
            
            if 'Anki' in apath:
                self.wf.add_item(
                    title    = "Now your anki user name (Default is User 1)...",
                    subtitle = "",
                    valid    = False,
                    icon     = ICON_INFO)
                self.wf.send_feedback()
        
        if apath.endswith('.anki2'):
     
            if not os.path.exists(apath):
                self.wf.add_item(
                    title    = "Aww snap! The path entered doesn't exist.",
                    subtitle = "",
                    valid    = False,
                    icon     = ICON_ERROR)
                self.wf.send_feedback()
                
            else:
                log.debug('------------> USER APATH: {!r}'.format(apath))
                self.wf.add_item(
                    title    = "That looks good!",
                    subtitle = apath,
                    arg      = apath,
                    valid    = True,
                    icon     = ICON_SETTINGS)
                self.wf.send_feedback()
                return 0

    

def main(wf):
    from docopt import docopt
    args = docopt(__usage__, argv=wf.args)
    
    log.debug('wf.args : {!r}'.format(wf.args))
    log.debug('args : {!r}'.format(args))
    
    awf = Anki_WF(wf)
    return awf.run(args)


if __name__ == '__main__':
    wf = Workflow(libraries=[os.path.join(os.path.dirname(__file__), 'lib')],
                  update_settings=UPDATE_SETTINGS)
    log = wf.logger
    sys.exit(wf.run(main))