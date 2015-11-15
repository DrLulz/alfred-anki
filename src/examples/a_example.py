import time
import urllib, httplib
import json
from aqt import mw
from aqt.utils import showInfo
from aqt.qt import *
import os
import sqlite3
import anki.sync
import anki.hooks
import re
from datetime import datetime

DEBUG = False
actives = {}

def get_current_col():
    return mw.col or mw.syncer.thread.col

def get_decks():
    """Returns all decks available in Anki"""
    current_col = get_current_col()
    return [Deck(deck_name,
                 current_col.decks.byName(deck_name)['id'])
                 for deck_name in current_col.decks.allNames(dyn=False)]

def get_deck_name(did):
    """Returns deck name based on Anki deck ID"""
    current_col = get_current_col()
    return current_col.decks.get(did, default=False)['name']

def get_last_review_time(did):
    current_col = get_current_col()
    (last_review_epoch,) = current_col.db.first("select max(r.id) from revlog r join cards c on r.cid = c.id where c.did = ?", int(did))
    return last_review_epoch or 0

def get_time():
    """Returns the timestamp associated with this action"""
    return actives.get('now', int(time.time()))

def format_ts(ts_millis):
    if not ts_millis:
        return None
    d = datetime.fromtimestamp(float(ts_millis)/1000)
    return d.strftime('%d %b %Y, %I:%M%p')

class BeeminderValidator(object):
    #TODO verify token too -- haven't found a proper data type in beeminder's API yet

    USER = re.compile('^[\w]+$')
    SLUG = re.compile('^[\w-]+$')

    @classmethod
    def is_valid_slug(cls, slug):
        return cls.SLUG.match(slug) is not None

    @classmethod
    def is_valid_user(cls, user):
        return cls.USER.match(user) is not None

class BeeAnkiSettings(object):
    """Used to write/get settings associated with BeeAnki"""
    def __init__(self, settings_path):
        self.settings_path = settings_path
        self.settings = {}
        conn = sqlite3.connect(settings_path)
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS settings (k TEXT, v TEXT, PRIMARY KEY (k));')
        cur.execute('SELECT k, v FROM settings;')
        for row in cur:
            try:
                self.settings[row[0]] = json.loads(row[1])
            except ValueError: #handle this properly
                showInfo('could not read setting: {0}'.format(row[0]))
        conn.commit()
        conn.close()

    def _write(self):
        """Page current settings to internal db"""
        conn = sqlite3.connect(self.settings_path)
        cur = conn.cursor()
        try:
            for setting_key, section_value in self.settings.iteritems():
                try:
                    cur.execute('insert or replace into settings (k, v) values (?, ?);',
                                (setting_key, json.dumps(section_value)))
                except ValueError: #handle this properly
                    showInfo('could not read setting: {0}'.format(setting_key))
                    raise
                except Exception:
                    showInfo('exception with key {setting_key} and value {section_value}'.format(setting_key=setting_key, section_value=section_value))
                    raise
        except Exception:
            conn.rollback()
            conn.close()
            raise
        conn.commit()
        conn.close()

    def get(self, section):
        """Get a config section by section name"""
        return self.settings.get(section) or {}

    def store(self, name, settings):
        """Store BeeAnki settings for a particular section name"""
        self.settings[name] = settings
        self._write()

class SettingAware(object):
    """Indicates this object can be marshalled/unmarshalled from a settings value"""
    def get_setting_value(self):
        """Abstract method: serializes the current object into a settings dictionary"""
        pass

    @classmethod
    def build_settings(cls, **settings):
        """Serializes all primitives and SettingAware arguments passed"""
        built_settings = {}
        for key, value in settings.iteritems():
            if hasattr(value, 'get_setting_value'):
                built_settings[key] = value.get_setting_value()
            elif value is not None:
                built_settings[key] = value
            else:
                continue

        return built_settings

class BeeAnkiWidget(QWidget):
    """A screen in BeeAnki"""
    def __init__(self, width=300, title='BeeAnki'):
        super(BeeAnkiWidget, self).__init__()
        self.setWindowTitle(title)
        self.setMinimumWidth(width)

class Deck(SettingAware):
    """A deck representation in BeeAnki"""
    def __init__(self, name, did, metadata=None):
        self.did = did
        self.name = name
        self.metadata = metadata or DeckMeta()

    @classmethod
    def from_settings(cls, settings):
        """Returns a Deck based on a deck settings dictionary"""
        metadata_settings = settings.get('metadata')
        if metadata_settings:
            metadata = DeckMeta.from_settings(metadata_settings)
        else:
            metadata = None
        return cls(get_deck_name(settings['did']),
                   settings['did'], metadata=metadata)

    def get_setting_value(self):
        """Serializes this deck to a settings dictionary"""
        return self.build_settings(name=self.name,
                                   did=self.did,
                                   metadata=self.metadata)

class DeckMeta(SettingAware):
    """Deck metadata representation in BeeAnki"""
    def __init__(self, last_sync_ts=None, last_sync_info=None,
                 last_sync_goal=None, 
                 current_sync_goal=None, tracking_opt=None):
        self.last_sync_ts = last_sync_ts
        self.last_sync_info = last_sync_info
        self.last_sync_goal = last_sync_goal
        self.current_sync_goal = current_sync_goal
        self.tracking_opt = tracking_opt

    @classmethod
    def from_settings(cls, settings):
        """Returns a DeckMetadata object based on a settings dictionary representation"""
        last_sync_ts = settings.get('last_sync_ts')
        last_sync_info = settings.get('last_sync_info')
        last_sync_goal = settings.get('last_sync_goal')
        current_sync_goal = settings.get('current_sync_goal')
        tracking_opt = settings.get('tracking_opt')
        return cls(last_sync_ts=last_sync_ts,
                   last_sync_info=last_sync_info,
                   last_sync_goal=last_sync_goal,
                   current_sync_goal=current_sync_goal,
                   tracking_opt=tracking_opt)

    def get_setting_value(self):
        """Serializes this DeckMetadata object into a settings dictionary value"""
        return self.build_settings(last_sync_ts=self.last_sync_ts,
                                   last_sync_info=self.last_sync_info,
                                   last_sync_goal=self.last_sync_goal,
                                   current_sync_goal=self.current_sync_goal,
                                   tracking_opt=self.tracking_opt)

class DeckInfo(BeeAnkiWidget):
    """A widget to display information and metadata associated with a deck"""
    def __init__(self, deck):
        super(DeckInfo, self).__init__(title='Deck Info')
        self.deck = deck
        self.layout = QFormLayout()
        self._add_fields()
        self.setLayout(self.layout)

    def _add_fields(self):
        """Adds info fields"""
        meta = self.deck.metadata
        labels = ['Last Sync Time', 'Synced Info',
                  'Last Sync Goal',
                  'Latest Review Time', 'Current Sync Goal']
        try:
            latest_rev_time = get_last_review_time(self.deck.did)
        except Exception:
            latest_rev_time = 0
        fields = [format_ts(meta.last_sync_ts), 
                  meta.last_sync_info,
                  meta.last_sync_goal, 
                  format_ts(latest_rev_time),
                  meta.current_sync_goal
                 ]
        for label, field in zip(labels, fields):
            self.layout.addRow(label + ': ', QLabel(str(field)
                               if field else 'N/A'))
    

class DeckEdit(BeeAnkiWidget):
    """The deck editing screen"""
    TRACKING_OPTIONS = ['Hours', 'Minutes', 'Seconds']
    TRACKING_OFFSET = {'Hours': 1.0/(3600*1000),
                           'Minutes': 1.0/(60*1000),
                           'Seconds': 1.0/1000
                          }

    def __init__(self, app_settings, main_deck_screen,
                 did=None, goal_name=None, deck_name=None,
                 tracking_option=None, new=True):
        super(DeckEdit, self).__init__(title='Deck')
        self.app_settings = app_settings
        self.main_deck_screen = main_deck_screen
        self.layout = QVBoxLayout()
        self.decks = self.filter_relevant_decks(get_decks()) if new else get_decks()
        self.name = self.get_names_dropdown(selected=deck_name)
        self.goal_name = QLineEdit(goal_name)
        self.tracking_options = self.get_tracking_options(selected=tracking_option)
        self.form = self.add_fields()
        self.setLayout(self.layout)
        self.current_selection = tracking_option if \
                                 tracking_option in DeckEdit.TRACKING_OPTIONS else None

    def filter_relevant_decks(self, deck_list):
        """If a new deck/goal is being added to BeeAnki, this limits 
           the available options based on decks that haven't already
           been added"""
        saved_decks = self.app_settings.get('DeckEdit')
        if not saved_decks:
            return deck_list
        filtered_decks = [deck for deck in deck_list
                          if unicode(deck.did) not in saved_decks]
        return filtered_decks

    @classmethod
    def from_settings(cls, settings, main_deck_screen, did):
        deck_settings = settings.get('DeckEdit')
        deck = deck_settings.get(unicode(did), None)
        if deck:
            meta = DeckMeta.from_settings(deck['metadata'])
            return cls(settings, main_deck_screen,
                       did=did, goal_name=meta.current_sync_goal,
                       deck_name=get_deck_name(did),
                       tracking_option=meta.tracking_opt, new=False)
        else:
            raise Exception('No stored deck found with deck id: {0}'.format(did))

    def get_deck(self):
        selected_idx = self.name.currentIndex()
        selected_deck = self.name.itemData(selected_idx)
        name = selected_deck.name
        did = selected_deck.did
        goal_name = str(self.goal_name.text())
        tracking = self.current_selection
        current_settings = self.app_settings.get('DeckEdit')
        current_deck_settings = current_settings.get(unicode(did)) if current_settings else None
        last_sync_ts = None
        if current_deck_settings:
            last_sync_ts = current_deck_settings.get('last_sync_ts')
        if last_sync_ts:
            meta = DeckMeta(current_sync_goal=goal_name,
                            tracking_opt=tracking,
                            last_sync_ts=last_sync_ts)
        else:
            meta = DeckMeta(current_sync_goal=goal_name,
                            tracking_opt=tracking,
                            last_sync_ts=get_last_review_time(did))
        return Deck(name, did, meta)

    def add_fields(self):
        form = QWidget()
        form_layout = QFormLayout()
        form.setLayout(form_layout)
        form_layout.addRow('Name', self.name)
        form_layout.addRow('Goal Name', self.goal_name)
        form_layout.addRow('Tracking', self.tracking_options)
        save_button = QPushButton('Save')
        save_button.clicked.connect(self.save_deck)
        buttons = QWidget()
        button_row = QHBoxLayout()
        buttons.setLayout(button_row)
        button_row.addWidget(save_button)
        self.layout.addWidget(form)
        self.layout.addWidget(buttons)
        return form_layout

    def get_names_dropdown(self, selected=None):
        names = QComboBox()
        sel_idx = None
        for i, deck in enumerate(self.decks):
            names.addItem(deck.name, deck)
            if deck.name == selected:
                sel_idx = i
        if sel_idx != None:
            names.setEnabled(False)
            names.setCurrentIndex(sel_idx)
        return names

    def get_tracking_options(self, selected=None):
        group_box = QWidget()
        button_list = QVBoxLayout()
        radio_boxes = [QRadioButton(name) for name in DeckEdit.TRACKING_OPTIONS]
        if selected is None:
            radio_boxes[0].setChecked(True)
        for box, name in zip(radio_boxes, DeckEdit.TRACKING_OPTIONS):
            button_list.addWidget(box)
            if str(box.text()) == selected:
                box.setChecked(True)
            box.toggled.connect(self.select_tracking(name))
        group_box.setLayout(button_list)
        return group_box

    def select_tracking(self, name):
        def update_selected(checked):
            if checked:
                self.current_selection = name
        return update_selected

    def save_deck(self):
        #TODO this should really be a signal for a DeckMain slot..
        current_deck = self.get_deck()
        if not BeeminderValidator.is_valid_slug(current_deck.metadata.current_sync_goal):
            showInfo('Please correct goal name: it must consist of alphanumeric characters and dashes')
            return
        self.main_deck_screen.deck_edited(self)
        #TODO refactor DeckEdit hardcoded string
        deck_settings = self.app_settings.get('DeckEdit')
        deck_settings[unicode(current_deck.did)] = current_deck.get_setting_value()
        self.app_settings.store('DeckEdit', deck_settings)
        self.close()

    @classmethod
    def remove_deck(cls, deck, settings):
        deck_settings = settings.get('DeckEdit')
        try:
            del deck_settings[unicode(deck.did)]
            settings.store('DeckEdit', deck_settings)
        except KeyError:
            pass

class DeckLog(SettingAware):

    def __init__(self, did, **kwargs):
        self.did = did
        self.logged_items = kwargs

    @classmethod
    def from_settings(cls, did, settings):
        deck_log = settings.get('DeckLog')
        current_log = deck_log.get(unicode(did))
        if current_log:
            return cls(did, **current_log)
        else:
            return cls(did)

    def get_setting_value(self):
        return self.build_settings(self.did, **self.logged_items)


class DeckListItem(QListWidgetItem):
    def __init__(self, deck):
        super(DeckListItem, self).__init__(deck.name)
        self.deck = deck

class DeckMain(BeeAnkiWidget):

    deck_removed = pyqtSignal(Deck, BeeAnkiSettings)

    def __init__(self, app_settings, available_decks=None):
        super(DeckMain, self).__init__(title='AnkiBee DeckMain')
        self.app_settings = app_settings
        self.layout = QFormLayout()
        self.available_decks = available_decks or []
        self.qdecks = self.build_deck_qlist()
        self.buttons = self.build_buttons()
        self.build_rows()
        self.setLayout(self.layout)
        self.init_services()
        self.active_deck = None

    @classmethod
    def from_settings(cls, settings):
        available = []
        deck_settings = settings.get('DeckMain')
        dids = deck_settings.get('available_decks') if deck_settings else []
        deck_reference = get_decks()
        for deck in deck_reference:
            if deck.did in dids:
                available.append(deck)
        return cls(settings, available)

    def build_rows(self):
        self.layout.addRow('Decks', self.qdecks)
        self.layout.addRow('', self.buttons)

    def build_buttons(self):
        add_button = QPushButton('Add')
        edit_button = QPushButton('Edit')
        remove_button = QPushButton('Remove')
        info_button = QPushButton('Info')
        add_button.clicked.connect(self.add_deck)
        edit_button.clicked.connect(self.edit_deck)
        info_button.clicked.connect(self.info_deck)
        remove_button.clicked.connect(self.remove_deck)
        buttons = QWidget()
        button_row = QHBoxLayout()
        buttons.setLayout(button_row)
        button_row.addWidget(add_button)
        button_row.addWidget(edit_button)
        button_row.addWidget(remove_button)
        button_row.addWidget(info_button)
        return buttons

    def build_deck_qlist(self):
        qdecks = QListWidget()
        #TODO: O(n^2), but likely small n
        available_dids = [deck.did for deck in self.available_decks]
        decks = [deck for deck in get_decks() if deck.did in available_dids]
        for deck in decks:
            qdecks.addItem(DeckListItem(deck))
        qdecks.currentItemChanged.connect(self.selection_changed)
        return qdecks

    def get_setting_value(self):
        settings = {}
        dids = [deck.did for deck in self.available_decks]
        settings['available_decks'] = dids
        return settings

    def add_deck(self, pos):
        #TODO handle this case better
        if len(get_decks()) == len(self.app_settings.get('DeckEdit')):
            showInfo('exhausted all possible decks')
            return
        deck_edit_window = DeckEdit(self.app_settings, self)
        self._show_deck_edit(deck_edit_window)

    def edit_deck(self, pos):
        did = self.qdecks.currentItem().deck.did
        deck_edit_window = DeckEdit.from_settings(self.app_settings, self, did)
        self._show_deck_edit(deck_edit_window)

    def remove_deck(self, pos):
        popped_list_item = self.qdecks.takeItem(self.qdecks.currentRow())
        #TODO don't update availabe decks here, have the qdecks emit a signal instead
        removed_deck = popped_list_item.deck
        self.available_decks = [cdeck for cdeck in self.available_decks
                                if cdeck.did != removed_deck.did]
        self.save_settings()
        self.deck_removed.emit(removed_deck, self.app_settings)

    def info_deck(self, pos):
        selections = self.qdecks.selectedItems()
        cur_deck = selections[0] if selections else None
        if cur_deck:
            did_key = unicode(cur_deck.deck.did)
            deck_settings = self.app_settings.get('DeckEdit').get(did_key)
            if not deck_settings:
                raise Exception("Could not find any settings for selected deck (deck ID: {0})".format(did_key))
            deck_info_window = DeckInfo(deck=Deck.from_settings(deck_settings))
            self.active_deck = deck_info_window
            self.active_deck.show()

    def _show_deck_edit(self, deck_window):
        self.active_deck = deck_window
        self.active_deck.show()

    def init_services(self):
        self.deck_removed.connect(DeckEdit.remove_deck)

    def selection_changed(self, current, prev):
        pass

    #TODO refactor to share code with buildqdecks function
    def update_deck_list(self):
        if not self.qdecks:
            return #not built yet
        qdecks = self.qdecks
        qdecks.clear()
        #this really should look at the decks in the settings, not this available_decks variable
        for deck in self.available_decks:
            qdecks.addItem(DeckListItem(deck))
        qdecks.currentItemChanged.connect(self.selection_changed)

    def save_settings(self):
        deck_main_settings = self.app_settings.get('DeckMain')
        self.app_settings.store('DeckMain', self.get_setting_value())

    def deck_edited(self, deck_editor):
        deck = deck_editor.get_deck()
        current_decks = [c.did for c in self.available_decks]
        if deck.did not in current_decks:
            self.qdecks.addItem(DeckListItem(deck))
            self.available_decks.append(deck)
            self.save_settings()

class OptionsPanel(BeeAnkiWidget, SettingAware):

    def __init__(self, app_settings):
        super(OptionsPanel, self).__init__(title='Options')
        self.app_settings = app_settings
        options_panel_settings = self.app_settings.get('OptionsPanel')
        self.syncer = BeeAnkiSync(self.app_settings, self)

        #stored options
        self.sync_enabled = options_panel_settings.get('sync_enabled', False)
        self.user_name = options_panel_settings.get('user_name')
        self.token = options_panel_settings.get('token')

        #gui references
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.user_name_line = QLineEdit(self.user_name)
        self.sync_options = self.get_sync_options(sync_enabled=self.sync_enabled)
        self.token_line = QLineEdit(self.token)
        self.user_name_line.editingFinished.connect(self.update_settings)
        self.token_line.editingFinished.connect(self.update_settings)
        self.init_panel()

    @classmethod
    def from_settings(cls, settings):
        return cls(settings)

    def get_setting_value(self):
        params = {}
        if self.user_name:
            params['user_name'] = self.user_name
        if self.token:
            params['token'] = self.token
        params['sync_enabled'] = self.sync_enabled

        return self.build_settings(**params)

    def init_panel(self):
        form = QWidget()
        form_layout = QFormLayout()
        form.setLayout(form_layout)
        form_layout.addRow('Sync when Anki does?', self.sync_options)
        form_layout.addRow('User Name', self.user_name_line)
        form_layout.addRow('Token', self.token_line)
        buttons = QWidget()
        button_row = QHBoxLayout()
        buttons.setLayout(button_row)
        sync_button = QPushButton('Sync Now')
        sync_button.clicked.connect(self.syncer.sync_all)
        button_row.addWidget(sync_button)
        self.layout.addWidget(form)
        self.layout.addWidget(buttons)

    def get_sync_options(self, sync_enabled=False):
        group_box = QWidget()
        button_list = QHBoxLayout()
        yes_button = QRadioButton('Yes')
        no_button = QRadioButton('No')
        button_list.addWidget(yes_button)
        button_list.addWidget(no_button)
        if sync_enabled:
            yes_button.setChecked(True)
        else:
            no_button.setChecked(True)
        yes_button.toggled.connect(self.enable_sync)
        no_button.toggled.connect(self.disable_sync)
        group_box.setLayout(button_list)
        return group_box

    def _set_sync_option(self, sync_option):
        self.sync_enabled = sync_option
        self.update_settings()

    def enable_sync(self):
        self._set_sync_option(True)

    def disable_sync(self):
        self._set_sync_option(False)

    def update_settings(self):
        old_user = self.user_name
        self.user_name = str(self.user_name_line.text())
        self.token = str(self.token_line.text())
        if self.user_name and not BeeminderValidator.is_valid_user(self.user_name):
            if self.user_name != old_user:
                showInfo('Invalid Beeminder username: must be alphanumeric')
            return
        self.app_settings.store('OptionsPanel',
                                self.get_setting_value()
                               )

class BeeAnkiSync(object):

    def __init__(self, app_settings, live_options_panel):
        self.app_settings = app_settings
        self.options = live_options_panel

    @classmethod
    def _ids_to_in_string(cls, ids):
        opening = "("
        closing = ")"
        id_strs = [str(i) for i in ids]
        id_group = ','.join(id_strs)
        res = opening + id_group + closing
        return res

    @classmethod
    def _time_per_decks(cls, dids, last_sync):
        current_col = get_current_col()
        if dids is not None:
            deck_filter = " and c.did in " + cls._ids_to_in_string(dids)
        else:
            deck_filter = ""
        (seconds_spent,) = current_col.db.first("""
            select sum(time) from revlog r join cards c on c.id = r.cid where r.id > ?
            """ + deck_filter
            , last_sync)
        seconds_spent = seconds_spent or 0
        return seconds_spent

    def sync_all(self):
        #TODO loop over the DeckEdit decks, create them, sync them, update metadata, store it
        deck_edit_settings = self.app_settings.get('DeckEdit')
        for did_str, deck_settings in deck_edit_settings.iteritems():
            did = int(did_str)
            stored_deck = Deck.from_settings(deck_settings)
            goal = stored_deck.metadata.current_sync_goal
            last_sync = stored_deck.metadata.last_sync_ts
            tracking_opt = stored_deck.metadata.tracking_opt
            #TODO this ignores tracking options.. these need to be revised any way
            time_val = 0
            if last_sync:
                unsynced_secs = self._time_per_decks([did], last_sync)
                offset = DeckEdit.TRACKING_OFFSET.get(tracking_opt)
                if offset is None:
                    raise Exception('Sorry, option {0} is not currently ' \
                                    'available for tracking goal: {1}'.format(tracking_opt, goal))
                time_val = float(unsynced_secs)*offset
                if time_val > 0:
                    self._sync(goal, time_val)
                    stored_deck.metadata.last_sync_info = str(time_val) + ' ' + tracking_opt
            stored_deck.metadata.last_sync_ts = get_last_review_time(did)
            stored_deck.metadata.last_sync_goal = goal
            deck_edit_settings[did_str] = stored_deck.get_setting_value()
            self.app_settings.store('DeckEdit', deck_edit_settings)

    def _sync(self, slug, sync_val):
        user = self.options.user_name
        token = self.options.token
        if not BeeminderValidator.is_valid_user(user) or not BeeminderValidator.is_valid_slug(slug):
            return False
        site = 'www.beeminder.com'
        api = '/api/v1/users/{user}/goals/{slug}/datapoints.json'.format(user=user, slug=slug)
        headers = {'Content-type': 'application/x-www-form-urlencoded', 'Accept': 'text/plain'}
        params = urllib.urlencode({'timestamp': get_time(),
                                'value': sync_val,
                                'comment': 'BeeAnki sync',
                                'auth_token': token
                                })
        con = httplib.HTTPSConnection(site)
        con.request('POST', api, params, headers)
        response = con.getresponse()
        if response.status != 200 and response.status != 201:
            raise Exception('Unable to sync time with Beeminder', response.status, response.read())
        con.close()
        return True


class BeeAnkiTabs(QTabWidget):

    def __init__(self, app_settings):
        super(BeeAnkiTabs, self).__init__()
        self.app_settings = app_settings

    def closeEvent(self, event):
        event.accept()

class UserMain(QWidget):
    """User config settings"""
    def __init__(self):
        super(UserMain, self).__init__()
        self.layout = QFormLayout()
        self.setLayout(self.layout)

def get_settings():
    if not actives.get('settings'):
        main_settings = BeeAnkiSettings(os.path.join(mw.pm.addonFolder(), 'beeanki.sqlite'))
        actives['settings'] = main_settings
    return actives['settings']

def sync_exit(obj, _old=None):
    res = _old(obj)
    current_col = get_current_col()
    if current_col:
        options_screen = OptionsPanel.from_settings(get_settings())
        if options_screen.sync_enabled:
            options_screen.syncer.sync_all()
    return res

def main():
    main_settings = get_settings()
    main_screen = DeckMain.from_settings(main_settings)
    options_screen = OptionsPanel.from_settings(main_settings)
    tabs = BeeAnkiTabs(main_settings)
    tabs.addTab(main_screen, 'Decks')
    tabs.addTab(options_screen, 'Options')
    actives['tabs'] = tabs
    actives['now'] = int(time.time())
    tabs.show()

action = QAction("beeanki", mw)
mw.connect(action, SIGNAL("triggered()"), main)
mw.form.menuTools.addAction(action)
anki.sync.Syncer.sync = anki.hooks.wrap(anki.sync.Syncer.sync, sync_exit, 'around')