#!/usr/bin/python
# encoding: utf-8

import os, subprocess
from lib.workflow import Workflow
from lib.workflow.background import run_in_background
from lib.atools import Tools, AnkiFx

__usage__ = """
proxy.py <action> [card | col | new | tags | apath] [<name>|<nid>]

Usage:
    proxy.py deck [new] [<name>]
    proxy.py update [col]
    proxy.py card [new | tags] [<nid>]
    proxy.py trigger [card | tags | apath]

Arguments:
    <name>     Deck name
    <nid>      Note ID

Options:
    -h, --help      Show this help text

"""

DELIMITER = '‣'

ALFRED_SCRIPT = 'tell application "Alfred 2" to search "{}"'

def _applescriptify(text):
    """Replace double quotes in text"""
    return text.replace('"', '" + quote + "')


def run_alfred(query):
    """Run Alfred with ``query`` via AppleScript"""
    script = ALFRED_SCRIPT.format(_applescriptify(query))
    log.debug('calling Alfred with : {!r}'.format(script))
    return subprocess.call(['osascript', '-e', script])
    


def main(wf):
    from docopt import docopt
    args = docopt(__usage__, argv=wf.args)
    
    log.debug('PROXY wf.args : {!r}'.format(wf.args))
    log.debug('PROXY args : {!r}'.format(args))


    # --------------------------------------------
    # Functions for background.py calls
    
    def update_decks():
        cmd = ['/usr/bin/python', wf.workflowfile('background.py'), 'decks']
        run_in_background('decks', cmd)
        
    def update_cards():
        cmd = ['/usr/bin/python', wf.workflowfile('background.py'), 'cards']
        run_in_background('cards', cmd)

    
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Update
    # proxy.py update [col]
    
    if args.get('update'):
        
        # called from anki.py(332)
        if args.get('col'):
            update_decks()
            print('Collection Updated')
    
    
    
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Run triggers passed from a Run Script
    # proxy.py trigger [card | tags | apath]
    
    if args.get('trigger'):
        
        
        # --------------------------------------------
        # New Card
        # called from anki.py(260)
        
        if args.get('card'):
            cmd = """osascript -e 'tell application "Alfred 2" to run trigger "add_card" \
                    in workflow "net.drlulz.alfred-anki" with argument "{}"'""".format('//')
            os.system(cmd)
            return 0
        
        
        # --------------------------------------------
        # New Tags
        # called from anki.py(308)
        # nid cached from anki.py(301)
        # cache ori_tags for call in new_tags.py(24)
        
        if args.get('tags'):
            
            at = Tools(apath)
            nid = wf.cached_data('nid')

            # retrieve cuurent tags if any
            def tags_wrapper():
                tags = at.note_spec('tags', nid=nid)
#                log.debug('------------> PROXY TAGS WRAPPER:{!r}'.format(tags))
                if tags:
                    return tags[0]
                else:
                    return None
            
            ori_tags = wf.cached_data('ori_tags', tags_wrapper, max_age=1)
#            log.debug('------------> PROXY TAGS NID:{!r}'.format(nid))
#            log.debug('------------> PROXY TAGS ORI_TAGS:{!r}'.format(ori_tags))

            # format retrieved tags and use for trigger argument
            try:
                ori_display = ' '.join('#{}'.format(t.strip()) for t in ori_tags.split())
            except AttributeError:
                ori_display = ''

            cmd = """osascript -e 'tell application "Alfred 2" to run trigger "add_tags" \
                    in workflow "net.drlulz.alfred-anki" with argument " {}"'""".format(ori_display)
            os.system(cmd)
            return 0


        # --------------------------------------------
        # apath
        # Open wf script filter to set collection path
        # called from anki.py(85) & anki.py(325)
        
        if args.get('apath'):
            run_alfred(':apath {}'.format(DELIMITER))
            return 0
        
        
        
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------ 
    # Deck functions
    # proxy.py deck [new] [<name>] (possible later additions, thus [])
    
    if args.get('deck'):
        
        
        # --------------------------------------------
        # New Deck
        # called from anki.py(181)
        # deck name passed as argument
        
        if args.get('new'):
            afx = AnkiFx(apath)
            afx.create_deck(args['<name>'])
            print('Created {}'.format(args['<name>']))
            update_decks()

#            log.debug('------------> PROXY DECK NEW NAME:{!r}'.format(args['<name>']))
            return 0


    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Card functions
    # proxy.py card [new | tags] [<nid>]
    
    if args.get('card'):
        
        
        # --------------------------------------------
        # New Card
        # called from anki.py(260) -> proxy.py(90) ->
        # did cached from anki.py(217)
        # user_sides from new_card.py(72)
        # send to lib/atools.py

        if args.get('new'):
            afx = AnkiFx(apath)   
            did = wf.cached_data('did')
            data = wf.cached_data('user_sides')
            afx.create_card(did, data)
            print('Created Card')
            update_cards()
            update_decks()
            
#            log.debug('------------> PROXY CARD NEW DID:{!r}'.format(did))
#            log.debug('------------> PROXY CARD NEW DATA:{!r}'.format(data))
            return 0


        # --------------------------------------------
        # nid cached in anki.py(301)
        # nid retrieved from new_tags.py(23)
        # nid sent as arg from new_tags.py(68)
        # user_tags cached in new_tags.py(66)
        
        if args.get('tags'):
            at = Tools(apath)
            nid = args['<nid>']
            data = wf.cached_data('user_tags', max_age=0)
            
            db_tags = at.create_tags(nid, data)
            print('Tagged: {}'.format(str(data[0])))
            update_cards()
            
#            log.debug('------------> PROXY CARD TAGS NID:{!r}'.format(nid))
#            log.debug('------------> PROXY CARD TAGS CACHED DATA:{!r}'.format(data))
#            log.debug('------------> PROXY DB RETURNED TAGS:{!r}'.format(db_tags))
            return 0



if __name__ == '__main__':
    wf = Workflow(libraries=[os.path.join(os.path.dirname(__file__), 'lib')])
    log = wf.logger
    apath = wf.settings.get('anki_path', None)
    wf.run(main)