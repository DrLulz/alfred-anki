### Requirements:

- [Alfred](http://www.alfredapp.com)
- [Anki](http://ankisrs.net)

### Commands:

- :anki
- :aset
	- :apath

### Anki Terminology:

- Collection = Group of Decks
- Notes = Collection of Facts
- Cards = Representation of Facts
- A note has a one to many relationship with cards, while a card can have only one associated note.

### Custom Dark Theme:

- Cards (notes) created from the workflow use this theme.
- Once the first card is created (from within workflow) the theme is available within Anki. The theme comes loaded with jQuery v1.11.2 and plugins [Zoom](http://www.jacklmoore.com/zoom/), [Magnific Popup](http://dimsemenov.com/plugins/magnific-popup/), [Panzoom](http://timmywil.github.io/jquery.panzoom/) (mobile only), and [Noty](http://ned.im/noty/#/about).
- You can find it in Anki under `Tools > Manage Note Types > Alfred Dark`.
- If creating cards from inside Anki the theme has optional fields.
    - `Front`, `F Note`
        - Front side, and optional note
    - `Back`, `B Note`
        - Back side and optional note
    - `class`
        - The theme default is to center all text.
        - To adjust text to the left enter `left` in the class field.
    - `Noty`
        - Show an optional note on the back-side of the card.
        - Good for reinforcement.
    - `http`
        - Entering a URL in this field displays a link in the bottom right on the back-side.
        - Accepts `www.site.com` without `http`
    - `video`
            - Accepts `youtube` and `vimeo` urls.
            - Link to the video is displayed in the upper left on the back-side.

### Workflow Progression:

#### 1. **:aset**

- As of now contains two actionable items.
    - Update collection (manual collection refresh)
    - Set Anki collection path (redirects to **:apath**)
- **:apath**
    - The workflow looks for the Anki collection in the most typical locations.  
    - If the path *is not* found the user will be prompted to enter the path manually. 
        - The default directory is `/Users/OSX_NAME/Documents/ANKI_USER/collection.anki2`
        - The default `ANKI_USER` created when Anki is first run is `User 1`. If you have changed this, enter your Anki user name.
    - If the path *is* found **:apath** is only useful if needing to switch between collections.

#### 2. **:anki**

- Search the collection for a deck
    - Search by name, or deck id
    - If the deck doesn’t exist you can create a new deck with the query as the title.
- Select deck
- Search for notes within selected deck
    - Search by facts, or tags
    - If the card is not found you can create a basic, two-sided card (cloze additions on the to-do list). The theme is the custom dark theme described above.
- Select card
    - Currently the only option after selecting a card is to modify its tags.
    - tags are entered as `#tag1 #tag2 #tag3`

### Credits:

- This workflow uses the python workflow library Alfred-Workflow (by deanishe).
- The internal structure borrows *heavily* from the FuzzyFolders and Reddit workflows (also by deanishe).
- The `new_card.py` was written by (guess who) deanishe, as a demo for my edification.

### TO-DO:

    - Anki Sync
    - File Action to import csv’s
    - Sort decks by new, reviewing, missed
    - More robust display of deck/card statistics
    - Open Anki to a specific deck
    - Choose model (theme) when adding cards
    - Allow for cloze cards
    - Rename decks
