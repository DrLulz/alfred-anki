# -*- coding: utf-8 -*-
# Copyright 2013-2014 Regents of the University of Minnesota
# Available under the terms of the MIT License: http://opensource.org/licenses/MIT

import requests
import json
import sys
import pprint
from urllib import urlretrieve
import os.path
import re
import string
import time
from dateutil.parser import *
from dateutil.tz import *
from datetime import *
import calendar

import o2a_settings

import anki, anki.exporting

# From http://www.andrew-seaford.co.uk/generate-safe-filenames-using-python/
## Make a file name that only contains safe charaters  
# @param inputFilename A filename containing illegal characters  
# @return A filename containing only safe characters  
def makeSafeFilename(inputFilename):     
    try:  
        safechars = string.letters + string.digits + " -_."  
        return filter(lambda c: c in safechars, inputFilename).replace(" ","_")
    except:  
	   return ""    
    pass  

def main():
    omeka_repositories = o2a_settings.REPOSITORIES
    my_collections = []
    for api_endpoint in omeka_repositories:
        title_element = requests.get(api_endpoint + "elements?name=Title&element_set=1").json()
        title_element_id = title_element[0]['id']
        omeka_collections = requests.get(api_endpoint + "collections").json()
        for omeka_collection in omeka_collections[1:]:
            collection_name = omeka_collection['element_texts'][0]['text']
            omeka_collection['title'] = collection_name
            collection_filename = makeSafeFilename(collection_name).lower()
            omeka_collection['anki_package'] = "%s.apkg" % collection_filename
            collection_tag = re.sub('[^0-9a-zA-Z]+', '', collection_name.split(":")[0].lower().strip())
            omeka_collection['tags'] = [collection_tag]
            omeka_items = requests.get(omeka_collection['items']['url']).json()
            print "Found collection %s with %s items" % (collection_name, len(omeka_items))
            if len(omeka_items) >= 1:
                # Check to see if collection on server was modified since apkg was created
                collection_modified = parse(omeka_collection['modified'])
                omeka_collection['modified_date'] = collection_modified.strftime("%Y-%m-%d %H:%M")
                my_collections.append(omeka_collection)
                apkg_filename = os.path.join(o2a_settings.OUTPUT_DIR, "%s.apkg" % collection_filename)
                if os.path.isfile(apkg_filename):
                    apkg_modified = datetime.fromtimestamp(os.path.getmtime(apkg_filename), tzlocal())
                    apkg_needs_update = apkg_modified < collection_modified
                else:
                    apkg_needs_update = True
                if apkg_needs_update:
                    # Create a new deck, which Anki calls a Collection
                    anki_collection = anki.storage.Collection(os.path.join(o2a_settings.OUTPUT_DIR, "%s.anki2" % collection_filename))
                    for item in omeka_items:
                        # Get the text of the item's 'Title' element
                        item_title = [element['text'] for element in item['element_texts'] if element['element']['id'] == title_element_id][0]
                        print item_title
                        item_files = requests.get(item['files']['url']).json()
                        item_file_dict = {f['original_filename']:f for f in item_files}
                        for item_file in item_files:
                            # Check to see if item is an image, and is not the annotated version of some other file
                            if ('image' in item_file['mime_type']) and ('_marked' not in item_file['original_filename']):
                                # Create a new card - a "note" in Anki terms
                                anki_note = anki_collection.newNote()
				card_back = ""
                                #card_back += "<h3>%s</h3>" % item_title
                                anki_note.tags = [collection_tag]
                                
                                # Fetch image file
                                image_filename = os.path.join(o2a_settings.OUTPUT_DIR, item_file['filename'])
                                print "Downloading file %s" % item_file['filename']
                                file_image = urlretrieve(item_file['file_urls']['original'])
                                
                                # Add image to the media in this card deck
                                anki_collection.media.addFile(file_image[0])
                                
                                # Look to see if there is a "_marked" version of this image
                                if "/" in item_file['original_filename']:
                                    base_filename = item_file['original_filename'].rsplit("/",1)[1]
                                else:
                                    base_filename = item_file['original_filename']
                                marked_filename = base_filename.replace(".jpg", "_marked.jpg")
                                
                                # If so, download the _marked file and add to the collection
                                if marked_filename in item_file_dict:
                                    marked_file = item_file_dict[marked_filename]
                                    print "Downloading marked file %s" % marked_file['filename']
                                    marked_file_image = urlretrieve(marked_file['file_urls']['original'])
                                    anki_collection.media.addFile(marked_file_image[0])
                                    card_back += "<img src='%s'>" % marked_file_image[0].rsplit("/",1)[1]
                                # If item has descriptive text, add it to the back of the card
                                if item_file['element_texts']:
                                    card_back += "<p>%s</p>" % item_file['element_texts'][0]['text']
                                
                                print "Card Back: " + card_back
                                anki_note.fields = ["<img src='%s'>" % file_image[0].rsplit("/",1)[1], card_back]
                                anki_collection.addNote(anki_note)
                                
                    print "Saving collection %s" % collection_name 
                    anki_collection.save()
                    anki_exporter = anki.exporting.AnkiPackageExporter(anki_collection)
                    print "Exporting to %s" % apkg_filename
                    anki_exporter.exportInto(apkg_filename)
                    
    json.dump(my_collections, open(os.path.join(o2a_settings.OUTPUT_DIR, "collections.json"), "w"))

if __name__ == "__main__":
    main()