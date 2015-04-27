#!/usr/bin/python
# encoding: utf-8

from __future__ import print_function, unicode_literals, absolute_import
import sys
from lib.workflow import Workflow, ICON_INFO, ICON_WARNING

log = None

DEFAULT_SETTINGS = {}
UPDATE_SETTINGS = {}
HELP_URL = ''

ICON = 'icon.png'


def main(wf):

    # --------------------------------------------
    # nid cached from anki.py(301)
    # ori_tags cached from proxy.py(117)
    
    nid = wf.cached_data('nid', max_age=0)
    ori_tags = wf.cached_data('ori_tags', max_age=0)
    
    # format ori_tags to match against query
    try:
        ori_list = ['#{}'.format(t.strip()) for t in ori_tags.split()]
        ori_display = ' '.join('#{}'.format(t.strip()) for t in ori_tags.split())
    except AttributeError:
        ori_list = []
        ori_display = ' '
        
    query = wf.args
    mod_list = query[0].split()
    
    # compare original tags with query
    _del = set(ori_list).difference(mod_list)
    _add = set(mod_list).difference(ori_list)
    
#    log.debug('------------> NID 4 TAGS:{!r}'.format(nid))
#    log.debug('------------> ORI_TAGS:{!r}'.format(ori_tags))
#    log.debug('------------> ORI_LIST:{!r}'.format(ori_list))
#    log.debug('------------> ORI_DISPLAY:{!r}'.format(ori_display))
#    log.debug('------------> QUERY:{!r}'.format(query))
#    log.debug('------------> DEL:{!r}'.format(_del))
#    log.debug('------------> ADD:{!r}'.format(_add))

    
    # --------------------------------------------
    # If user changed the tags
    
    if _del != _add:
        
        # check if tag is prefixed with #
        for tag in query[0].split():
            if not tag.startswith('#'):
                wf.add_item("Tag '{}' must be prefixed with #".format(tag), 
                            '#{}'.format(tag), 
                            valid=False, 
                            icon=ICON_WARNING)
                wf.send_feedback()
                return 0
                
        # cache the tag modifications
        wf.cache_data('user_tags', query)
        
        wf.add_item('Commit changes',
                    valid=True,
                    arg=str(nid),
                    icon=ICON)


    # display new tags if any
    if list(_add):
        wf.add_item('Add: {}'.format(' '.join(_add)),
                    valid=False,
                    icon='icons/plus.png')

    # display removals if any
    if list(_del):
        wf.add_item('Remove: {}'.format(' '.join(_del)),
                    valid=False,
                    icon='icons/minus.png')
    
    # if all tags will be removed 
    if not query:
        wf.add_item('Remove: {}'.format(' '.join(_del)),
                    valid=False,
                    icon='icons/minus.png')
        wf.send_feedback()
    
    
    wf.send_feedback()

if __name__ == '__main__':
    wf = Workflow(default_settings=DEFAULT_SETTINGS,
                  update_settings=UPDATE_SETTINGS,
                  help_url=HELP_URL)
    log = wf.logger
    sys.exit(wf.run(main))
