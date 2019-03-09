#! /usr/bin/env python3
import glob
import re
import argparse
import os, os.path
import subprocess
import pypandoc
import tempfile
import copy
import fnmatch
import math
from PIL import Image, ImageFont, ImageDraw
from io import BytesIO
import base64
import yaml
import chordprobook.chords as chords
import chordprobook.instruments
import datetime
from weasyprint import CSS, HTML
from pkg_resources import resource_string


def extract_transposition(text):
    """ Find a transpose directive and get rid of it out of a string """
    tr_re = re.compile("{(tr|transpose): *(.*)}", re.IGNORECASE)
    tr_search = re.search(tr_re, text)
    standard_transpositions = [0]
    if tr_search != None:
        trans = tr_search.group(2).split(" ")
        standard_transpositions += [int(x) for x in trans]
        text = re.sub(tr_re, "", text)
    return text, standard_transpositions



def extract_book_filename(text, book = None):
    """ Find a custom chordpro directive: {book: } """
    book_re = re.compile("{(book:) *(.*?)}", re.IGNORECASE)
    book_search = re.search(book_re, text)
    book_filename = None
    if book_search != None:
        book_filename = book_search.group(2)
        text = re.sub(book_re, "", text)
    return text, book_filename

class TOC:
    ideal_songs_per_page = 40
    max_songs_per_page = 50

    def __init__(self, book, start_page):

        entries = []
        sets = []
        def chunked(iterable, n):
            """
            Split iterable into ``n`` iterables of similar size
            From: http://stackoverflow.com/questions/24483182/python-split-list-into-n-chunks
            """
            chunksize = int(math.ceil(len(iterable) / n))
            return [iterable[i * chunksize:i * chunksize + chunksize] for i in range(n)]


        song_count = 0
        num_entries = len(book.sets) + len([i for i in book.songs if not i.blank])
        if num_entries > TOC.max_songs_per_page:
            self.target_num_pages = int(math.ceil(num_entries / TOC.ideal_songs_per_page ))
        else:
            self.target_num_pages = 1

        page_count = start_page +  self.target_num_pages
        for song in book.sets:
            if not song.blank:
                sets.append("Set: %s <span style='float:right'>%s</span>    " % ( song.title, str(page_count)))
            page_count += song.pages

        # Make sure we don't have a song on the back of a setlist (so you can rip out the setlist)
        if len(book.sets) > 0 and  (self.target_num_pages + len(book.sets)) % 2 == 0:
            book.songs.insert(0, cp_song("", title="", blank=True))
            page_count += 1

        for song in book.songs:
            if not song.blank:
                song_count += 1
                entries.append("%s %s <span style='float:right'> %s</span>    " % (song.title, song.get_key_string(), str(page_count)))
                page_count += song.pages

        entries = sets + entries

        if num_entries > TOC.max_songs_per_page:
            self.pages = chunked(entries,self.target_num_pages)
        else:
            self.pages = [entries]


    def format(self):
        contents = ""
        for page in self.pages:
            contents += """
<div class='song'><div class='page'><div class='song-page'><div class='song-text'>
%s
</div></div></div></div>
            """ % "\n".join(page)
            return(contents)


class directive:
    """Simple data structure for a directive, with name and optional value"""
    title, subtitle, artist, composer, lyricist, time, tempo, key, start_chorus, end_chorus, start_tab, end_tab, start_bridge, end_bridge, transpose, new_page, define, grids, comment, instrument, tuning, dirs, files, version, page_image = range(0, 25)
    directives = {
        "t": title,
        "title": title,
        "st": subtitle,
        "subtitle": subtitle,
        "artist": artist,
        "composer": composer,
        "lyricist": lyricist,
        "time": time,
        "tempo": tempo,
        "key": key,
        "start_of_chorus": start_chorus,
        "soc": start_chorus,
        "end_of_chorus": end_chorus,
        "eoc": end_chorus,
        "start_of_tab": start_tab,
        "sot": start_tab,
        "end_of_tab": end_tab,
        "eot": end_tab,
        "start_of_bridge": start_bridge,
        "sob": start_bridge,
        "end_of_bridge": end_bridge,
        "eob": end_bridge,
        "transpose": transpose,
        "tr": transpose,
        "new_page": new_page,
        "np": new_page,
        "define": define,
        "grids": grids,
        "comment": comment,
        "c": comment,
        "instrument": instrument,
        "tuning": tuning,
        "dirs": dirs,
        "files": files,
        "version": version,
        "page_image": page_image,
        "pi": page_image,
    }


    def __init__(self, line):
        """ Takes a line of text as input """
        line = line.strip()
        self.type = None
        if line.startswith("{") and line.endswith("}"):
            name, _, self.value = line[1:-1].partition(":")
            name = name.lower()
            if name in directive.directives:
                self.type = directive.directives[name]
                self.value = self.value.strip()


def normalize_chord_markup(line):
        """ Put space around chords before and after word boundaries but not within words """
        line = re.sub("(\w)(\[[^\]]*?\])( |$)","\\1 \\2\\3", line)
        line = re.sub("(^| )(\[[^\]]*?\])(\w)","\\1\\2 \\3", line)
        return line


class cp_song:
    """ Represents a song, with the text, key, chord grids etc"""
    def __init__(self, song,
                 title="Song",
                 transpose=0,
                 blank = False,
                 path = None,
                 instruments = None,
                 instrument_name=None,
                 nashville=False,
                 major_chart=False,
                 lefty= False):
        self.blank = blank
        self.lefty = lefty
        if instruments == None:
            self.instruments = chordprobook.instruments.Instruments()
        else:
            self.instruments = instruments

        self.local_instruments = None
        # Look-up
        self.instrument_name = instrument_name
        self.local_instrument_names = []
        self.text = song
        self.key = None
        self.pages = 1
        self.original_key = None
        self.path = path
        self.dir = "."
        if self.path:
            self.dir, _ = os.path.split(self.path)

        self.notes_md = ""
        self.nashville = nashville
        self.major_chart = nashville and major_chart
        self.transpose = transpose if not nashville else False
        self.transposer = chords.transposer(transpose)
        self.standard_transpositions = [0]
        self.title = ""
        self.grids = None
        self.parse()
        self.md = ""
        self.formatted_title = ""
        if self.title == "":
            self.title = title


    def parse(self):
        """ Deal with directives and turn song into markdown"""
        in_tab = False
        in_block = False
        new_text = ""
        current_instrument = None
        for line in self.text.split("\n"):
            dir = directive(line)
            if dir.type == None:
                if not line.startswith('#'):
                    line = normalize_chord_markup(line)

                    if in_tab:
                        # Four spaces in Markdown means preformatted
                        pass
                    else:
                        # Highlight chords
                        line = line.replace("][","] [").strip()
                        line = re.sub('\[(.*?)\]','<span class="chord-bracket">[\\1]</span>', line)
                        if line.startswith("."):
                            line = re.sub("^\.(.*?) (.*)","<span class='\\1'>\\1 \\2</span>", line)

                    new_text += "%s\n" % line
            else:
                if dir.type == directive.comment:
                    if in_block:
                        new_text += "</div>"
                        in_block = False
                    if dir.value.startswith("."):
                        dir.value = dir.value[1:]
                        classs = dir.value.split(" ")[0]
                        if classs:
                            in_block = True
                            new_text += "<div class='%s'>" % classs


                    new_text += "\n**%s**\n" % dir.value

                elif dir.type == directive.title:
                    self.title += dir.value

                elif dir.type == directive.subtitle:
                    new_text += "\n**%s**\n" % dir.value

                elif dir.type == directive.artist:
                    new_text += '<div class="meta artist"><span class="key">Artist:</span> <span class="value">%s</span></div>' % dir.value

                elif dir.type == directive.composer:
                    new_text += '<div class="meta composer"><span class="key">Composer:</span> <span class="value">%s</span></div>' % dir.value

                elif dir.type == directive.lyricist:
                    new_text += '<div class="meta lyricist"><span class="key">Lyricist:</span> <span class="value">%s</span></div>' % dir.value

                elif dir.type == directive.time:
                    new_text += '<div class="meta time"><span class="key">Time:</span> <span class="value">%s</span></div>' % dir.value

                elif dir.type == directive.tempo:
                    new_text += '<div class="meta tempo"><span class="key">Tempo:</span> <span class="value">%s</span></div>' % dir.value

                elif dir.type == directive.key:
                    if self.original_key:
                         new_text += "%s\n" % line
                    else:
                        self.original_key = dir.value
                        self.key = self.transposer.transpose_chord(self.original_key)

                elif dir.type == directive.transpose:
                    trans = dir.value.split(" ")
                    self.standard_transpositions += [int(x) for x in trans]

                elif dir.type  == directive.start_chorus:
                    new_text += "<blockquote class='chorus'>\n"

                elif dir.type  == directive.start_bridge:
                    new_text += "<blockquote class='bridge'>\n"

                elif dir.type in [directive.end_chorus, directive.end_bridge]:
                    new_text += "</blockquote>\n"

                elif dir.type == directive.start_tab and not in_tab:
                    in_tab = True
                    new_text += "```\n"

                elif dir.type == directive.end_tab and in_tab:
                    new_text += "```\n"
                    in_tab = False


                elif dir.type == directive.new_page:
                    if in_block:
                        new_text += "</div>\n"
                        in_block = False
                    new_text +=  "\n<!-- new_page -->\n"
                    self.pages += 1

                elif dir.type == directive.page_image:
                    if in_block:
                        new_text += "</div>\n"
                        in_block = False
                    new_text += "<img src='file://%s/%s' width='680'/>"  % (self.dir, dir.value)


                elif dir.type == directive.instrument:
                    inst_name = dir.value
                    if self.local_instruments == None:
                        self.local_instruments = chordprobook.instruments.Instruments()
                    current_instrument = self.local_instruments.get_instrument_by_name(inst_name)
                    self.local_instrument_names.append(inst_name)
                    if current_instrument == None:
                        current_instrument = chordprobook.instruments.Instrument(name = inst_name)
                        console.log("Loading lefty instrument", inst_name)
                        current_instrument.chart = chords.ChordChart(lefty=self.lefty)
                        self.local_instruments.add_instrument(current_instrument)
                    else:
                        current_instrument.load_chord_chart()

                elif dir.type == directive.define:
                    if current_instrument != None:
                        current_instrument.chart.add_grid(line)



            self.text = new_text
            # Add four spaces to mid-stanza line ends to force Markdown to add breaks
            self.text = re.sub("(.)\n(.)", "\\1    \\n\\2", self.text)


    def format(self, transpose=None, instrument_name=None, stand_alone=True):
        """
        Create a markdown version of the song, transposed if necessary,
        does the last-minute formatting on the song incuding transposition
        and fetching chord grids """
        self.pages = 1
        if instrument_name == None:
            instrument_name = self.instrument_name
        self.local_grids = None
        self.grids = None

        if transpose:
            self.transpose = transpose
        #self.transpose = transpose
        if instrument_name != None:
            instrument = self.instruments.get_instrument_by_name(instrument_name)
            if instrument != None:
                instrument.load_chord_chart(lefty=self.lefty)
                self.grids = instrument.chart

            if  self.local_instruments != None and instrument_name in self.local_instrument_names:
                self.local_grids = self.local_instruments.get_instrument_by_name(instrument_name).chart

        if transpose and self.original_key:
            self.key = self.transposer.transpose_chord(self.original_key)

        key_string = self.get_key_string()
        title = "%s %s" % (self.title, key_string)

        self.chords_used = []

        # TODO Move this to a stand-alone-function
        nv = chordprobook.chords.ChordChart() if self.nashville and self.original_key else None

        def format_chord(chord):
            if nv:
               chord = nv.nashvillize(chord,key=key, major_chart=self.major_chart)
            else:
                if self.transposer.offset != 0:
                    chord = self.transposer.transpose_chord(chord)

                if self.grids != None:
                    clean_chord = self.grids.clean_chord_name(chord)
                    if not clean_chord in self.chords_used:
                        self.chords_used.append(clean_chord)

            return('[<span class="chord">%s</span>]' % chord)

        key = self.original_key
        song =  ""
        tr = chordprobook.chords.transposer(key=key, major_chart=self.major_chart)

        if self.major_chart:
            song += "*NOTE: Chart is for relative major key* \n"

        for line in self.text.split("\n"):
            dir = directive(line)
            if dir.type == directive.key:
                key = dir.value.strip()
                if self.original_key:
                    # TODO fix minors
                    tr = chordprobook.chords.transposer(key=key)
                    minor = " (minor)" if tr.minor else ""
                    if self.nashville:
                        chart = chords.ChordChart()
                        song += "\n### Modulate: %s (%+d semitones%s)  \n" % (chart.nashvillize(key,
                             self.original_key),
                             tr.offset - tr.get_note_index(self.original_key) % 12,
                             minor)
                    else:
                        song += "\n### Change key to %s\n" % self.transposer.transpose_chord(key)
            else:
                song += re.sub("\[(.*?)\]", lambda m: format_chord(m.group(1)), line) + "\n"
        if stand_alone and instrument_name != None:
            title = "%s (%s %s)" % (title, "Left-handed" if self.lefty else "", instrument_name)

        self.md = song
        self.formatted_title = title


    def to_final_md(self):
        """ Generate a markdown doc with chords, used by word processor export"""
        md = ""
        md += "# %s (%s)\n\n" % (self.title, self.key)
        if self.chord_md_with_name:
            for m in self.chord_md_with_name:
                md += " %s " % m
            md += "\n\n"
        md += self.md
        return md


    def to_html(self):
        # TODO STANDALONE

        # Deal with chords
        grid_md = ""
        chords_by_page = [[]]
        self.chord_md = [] # For keeping chords that will be displayed alongside text
        self.chord_md_with_name = [] # For keeping chords with names on the picture
        if self.grids != None:
            # Find which chords actually have grids to display
            for chord_name in self.chords_used:
                md = None
                # Have a local version of this chord?
                if self.local_grids:
                    md = self.local_grids.grid_as_md(chord_name)
                    md_name = self.local_grids.grid_as_md(chord_name, display_name=True)
                if md == None:
                    md = self.grids.grid_as_md(chord_name)
                    md_name = self.grids.grid_as_md(chord_name, display_name=True)

                if md != None:
                    self.chord_md.append((md, chord_name))
                    self.chord_md_with_name.append((md_name))

            # Too many to show down the right margin?
            chords_in_text =  (len(self.chord_md) > 12 * self.pages)

            if chords_in_text:
                self.md += "\n<!-- new_page -->\n"
                self.pages += 1
            else:
                chords_per_page = len(self.chord_md) / self.pages

            for md in self.chord_md:
                if chords_in_text:
                    self.md +=  "<figure style='display: inline-block'>%s<figcaption style='text-align:center'>%s</figcaption></figure>" % md
                else:
                    chord_string = "<p>%s</br>%s</p>" % md
                    if len(chords_by_page[-1]) < chords_per_page:
                        chords_by_page[-1].append(chord_string)
                    else:
                        chords_by_page.append([chord_string])

        song_pages = self.md.split("<!-- new_page -->")
        song = ""
        page_count = 0
        for page in song_pages:
            if page_count == 0:
                title = "<h1 class='song-title'>%s</h1>" % self.formatted_title
            else:
                title = ""
            if len(chords_by_page) > page_count:
                grid_md =  "<div class='grids'>%s</div>" % "</br>".join(chords_by_page[page_count])
            else:
                grid_md = ""
            song += "<div class='page'>%s %s <div class='song-page'><div class='song-text'>\n%s\n%s\n\n</div></div></div>" % ( title, grid_md, self.notes_md, page)
            page_count += 1

        song = """
<div class='song'>
%s
</div>
        """ % song

        self.formatted_md = song
        return pypandoc.convert(song, 'html', format='md')

    def to_stand_alone_html(self):
        return html_book.format(self.to_html(), title = self.title, stand_alone = True)

    def get_key_string(self, trans = None):
        if trans:
            self.transpose = trans
        if self.original_key and self.transpose:
            self.transposer = chords.transposer(self.transpose)
            self.key = self.transposer.transpose_chord(self.original_key)

        return "(%s)" % self.key if self.key != None else ""

class cp_song_book:
    """Class to hold a set of songs and setlists"""
    transposition_options = ("all","0","1")
    transpose_all, do_not_transpose, transpose_first = transposition_options
    default_title = 'Songbook'
    def __init__(self, keep_order = False, title = None,
                 instruments = None, instrument_name = None,
                 path = ".", nashville = False, major_chart = False,
                 lefty = False, external_css = None,
                 header_font_name = None, header_font_size = None):
        self.version = None
        self.lefty = lefty
        self.title = title
        self.songs = [] #songs
        self.default_instrument_names = []
        if instruments == None:
            self.instruments = chordprobook.instruments.Instruments()
        else:
            self.instruments = instruments
        self.instrument_name_passed = instrument_name
        self.nashville = nashville
        self.major_chart = nashville and major_chart
        self.text = ""
        self.keep_order = keep_order
        self.sets = [] # Song-like objects to hold rip-out-able set lists
        self.auto_transpose = cp_song_book.do_not_transpose
        self.external_css = external_css
        self.header_font_name = header_font_name
        self.header_font_size = header_font_size
        # If we're passed a file, load it
        self.set_path(path)
        if os.path.isfile(path):
            with open(path) as p:
                self.load_from_text(p.read(), relative_to=self.dir)


    def set_path(self, path="."):
        self.path = path
        self.dir, self.filename = os.path.split(path)

    def sort_alpha(self):
        self.songs.sort(key= lambda song: re.sub("(?i)^(the|a|\(.*?\)) ", "", song.title.lower()))
        #self.songs.sort(key= lambda song: song.title.lower())


    def to_md(self):
        """ Generate Markdown version of a book """
        md = "---\ntitle: %s\n---\n" % self.title
        for song in self.songs:
            md += song.to_md()
        return md

    def __get_file_list(self, files, dir_list):
        """ Returns a list of files as in list of dirs and file-glob passed in files """
        if dir_list == []:
            dir_list = ['.']
        for dir in dir_list:
            for root, dirnames, filenames in os.walk(os.path.join(self.dir,dir.strip())):
                for filename in fnmatch.filter(filenames, files):
                     if not filename.startswith("."):
                        self.add_song_from_file(open(os.path.join(root, filename)))

    def add_song_from_text(self, text, name, transpose=0):
        path = os.path.join(self.dir, name)
        song = cp_song(text , path=path,
                       transpose=transpose,
                       instruments = self.instruments,
                       instrument_name=self.instrument_name_passed,
                       nashville=self.nashville,
                       major_chart=self.major_chart,
                       lefty = self.lefty)
        transpositions_needed = []
        if not self.nashville and self.auto_transpose == cp_song_book.transpose_all:
                transpositions_needed = song.standard_transpositions
        elif  not self.nashville and self.auto_transpose == cp_song_book.transpose_first and len(song.standard_transpositions) > 1:
                transpositions_needed = [song.standard_transpositions[1]]
        else:
            self.songs.append(song)


        # Add transposed versions of songs
        for trans in transpositions_needed:
            s = copy.deepcopy(song)
            s.transpose = trans
            s.format()
            self.songs.append(s)

    def add_song_from_file(self, file, transpose=0):
        """ Adds a song from a file to a book and works out how many transposed versions to add """
        with file as f:
           self.add_song_from_text(f.read(), os.path.abspath(f.name), transpose)


    def load_from_text(self, text, relative_to="."):
        """ Reads a book in from a sting containing paths or directives """

        self.text = text
        dir_list = []
        for line in self.text.split("\n"):
            line = line.strip()
            directiv = directive(line)
            if directiv.type == None:
                if not line.startswith("#") and not line == "":
                    # Assume this is a path
                    # Look for transpose TODO: use a proper parse method
                    transpose = 0
                    if "{" in line:
                        line, direct = line.split("{")
                        transpose_dir = directive("{" + direct)
                        if transpose_dir.type == directive.transpose:
                            trans = transpose_dir.value.split(" ")
                            transpositions = []
                            transpositions += [int(x) for x in trans]
                            transpose = transpositions[0]
                    song_path = os.path.join(self.dir, line.strip())
                    if os.path.isfile(song_path):
                        self.add_song_from_file(open(song_path), transpose)
                    else:
                        print("Can't find song %s" % song_path)
            else:
                if directiv.type == directive.title and self.title == None:
                    self.title = directiv.value
                elif directiv.type == directive.instrument:
                    self.default_instrument_names.append(directiv.value)
                elif directiv.type == directive.dirs:
                    dir_list.append(directiv.value)
                elif directiv.type == directiv.files:
                    self.__get_file_list(directiv.value, dir_list)
                elif directiv.type == directiv.version:
                    self.version = directiv.value
                elif directiv.type == directive.transpose:
                    if directiv.value.lower() in cp_song_book.transposition_options:
                        self.auto_transpose = directiv.value.lower()


    def format(self, instrument_name=None):
        if self.title == None:
            self.title = cp_song_book.default_title

        # Format songs, need to know how long they are
        for song  in self.songs:
            song.format(instrument_name = instrument_name, stand_alone=False)

        self.reorder(1, old=None, new_order=[], waiting=[])
        toc = TOC(self, 2)
        self.contents = toc.format()


    def __save(self, instrument_name, args, output_file):
        self.format(instrument_name=instrument_name)
        all_songs = self.sets_md

        if instrument_name != None:
            suffix = "%s_%s" % ("_lefty" if self.lefty else "", instrument_name.lower().replace(" ", "_"))
            title_suffix = " (for %s &nbsp;%s)" % ("Left-handed" if self.lefty else "", instrument_name)
        else:
            suffix = ""
            title_suffix = ""
        output_file += suffix
        version_string = ""

        if self.version:
            output_file += "-"
            if self.version.lower() == "auto":
                version_string = str(datetime.datetime.now())
                output_file +=  version_string.replace(" ", "_")
            else:
                version_string = self.version
                output_file +=  self.version.replace(" ", "_")

        # TODO - only generate this if HTML

        # Need to run this whatever the output_file# Now add formatted songs to output in the right order
        for song in self.songs:
            all_songs += song.to_html()

        title = self.title + title_suffix + " " + version_string
        if args['html']:
             html_path = output_file + ".html" # Save for the use
        else: # Use a temp dir
             temp_file = tempfile.NamedTemporaryFile(suffix=".html")
             html_path = temp_file.name

        if args['html'] or args['pdf']:
            with open(html_path, 'w') as html:
                html.write(html_book.format(all_songs,
                                            title=title,
                                            for_print = args['a4'],
                                            external_css = self.external_css,
                                            contents=pypandoc.convert(self.contents,
                                                                        "html",
                                                                        format="md")))
            if args['pdf']:
                pdf_path = output_file + ".pdf"
                print("Outputting PDF:", pdf_path, html_path)
                stylesheets = [
                    CSS(string=resource_string(__name__, "styles/print.css")),
                ]
                if self.external_css:
                    stylesheets.append(CSS(filename=self.external_css))
                HTML(html_path).write_pdf(pdf_path, stylesheets=stylesheets)

        if args['docx'] or args['odt'] or args['epub']:
            exts = []
            if args['docx']:
                exts.append('docx')
            if args['odt']:
                exts.append('odt')
            if args['epub']:
                exts.append('epub')

            for ext in exts:
                out_path = output_file + "." + ext
                if ext in ["docx","odt"]:
                    xtra = ["--toc","--toc-depth=1", "--data-dir=.", "--self-contained"]
                else:
                    xtra =["--toc", "--toc-depth=1","--epub-chapter-level=1"] #, "--epub-stylesheet=songbook.css"]

                if args['docx'] and args["reference_docx"] != None:
                    xtra.append('--reference-doc=%s' % args["reference_docx"])

                if args['odt'] and args["reference_odt"] != None:
                    xtra.append('--reference-doc=%s' % args["reference_odt"])
                # Format some markdown for the non-PDF output
                h = "% " + title + "\n\n"
                for song in self.songs:
                    h += song.to_final_md()

                print("Writing output doc", out_path)
                # Convert to HTML and then the word processor format (needed for images to work)
                pypandoc.convert(h, "html", format="markdown", outputfile=html_path, extra_args=["--self-contained"])
                pypandoc.convert(html_path, ext, format="html", outputfile=out_path, extra_args=xtra)


    def output(self, args, output_file):
        self.sets_md = ""
        for set in self.sets:
            set.format()
            self.sets_md += set.to_html()

        if self.instrument_name_passed == None:
            if self.nashville:
                self.__save(None, args, output_file)
            else:
                for instrument_name in  self.default_instrument_names + [None]:
                    self.__save(instrument_name, args, output_file)
        else:
            self.__save(self.instrument_name_passed, args, output_file)


    def order_by_setlist(self, setlist):
        """
        setlist: A string or path

        Use a setlist to order the book. Setlist will already have {title: } and {book: }
        directives removed by this point.

        Setlist uses markdown conventions, with ATX-style headers
        # Set 1

        ## Song name

        Notes on performance go here.

        ## Another song

        # Set 2

        ...
        """
        if os.path.exists(setlist):
            self.set_path(setlist)
            with open(setlist) as s:
                setlist = s.read()

        # First-up, do we already have songs in this book, if not look for some
        if self.songs == []:
            setlist, book_filename = extract_book_filename(setlist)
            if book_filename:
                book_path = os.path.join(self.dir, book_filename)
                with open(book_path) as b:
                    self.load_from_text(b.read())

        new_order = []
        current_set = None
        new_set = False
        current_song = None
        self.version = None
        for potential_song in setlist.split("\n"):
            potential_song = potential_song.strip()
            if potential_song != "":
                if potential_song.startswith("{") and potential_song.endswith("}"):
                    dir = directive(potential_song)
                    if dir.type == directive.title:
                        self.title = dir.value
                    elif dir.type == directive.version:
                        self.version = dir.value
                potential_song = re.sub("\s+", " ", potential_song)
                if potential_song.startswith("# "):
                    potential_song = potential_song.replace("# ","").strip()
                    # Use songs to represent sets, so each set gets a single page up front of the book
                    # the text of which will scale up nice and big courtesy of the song scaling algorithm
                    if current_song != None and current_set != None:
                        current_song.title = "%s {End of %s}" % (current_song.title, current_set.title)
                    current_set = cp_song("{title: %s}" % potential_song)
                    self.sets.append(current_set)
                    new_set = True

                elif potential_song.startswith("## "): # A song
                    song_name = potential_song.replace("## ", "").strip()
                    song_name, transpositions = extract_transposition(song_name)
                    song_name = song_name.strip()
                    restring = song_name.replace(" +", ".*?").lower()
                    regex = re.compile(restring)
                    found_song = False
                    for song in self.songs:
                        if re.search(regex, song.title.lower()) != None:
                            # Copy the song in case it is in the setlist twice with different treatment,
                            # such as keys or notes
                            prev_song = copy.deepcopy(current_song)
                            current_song = copy.deepcopy(song)

                            if transpositions == [0]:
                                transpositions = current_song.standard_transpositions
                            if new_set:
                                current_song.title = "%s {Start of %s}" % (song.title, current_set.title)
                                new_set = False
                            if len(transpositions) > 1 and transpositions[1] != 0:
                                current_song.format(transpose = transpositions[1])

                            if current_song.key != None:
                                song_name = "%s (in %s)" % (song_name, current_song.key)

                            new_order.append(current_song)
                            current_set.text +=  "## %s\n" % song_name
                            found_song = True
                            break

                    if not found_song:
                        current_song = cp_song("{title: %s (not found)}" % song_name)
                        new_order.append(current_song)
                        current_set.text +=  "## %s (NO CHART)\n" % song_name

                elif current_song != None:
                    current_song.notes_md += potential_song + "\n\n"
                    current_set.text +=  potential_song + "\n\n"

        self.songs = new_order



    def reorder(self, start_page, old = None, new_order=[], waiting = []):
        """ Reorder songs in the book so two-page songs start on an even page
           Unless this is a set-list in which case insert blanks. Recursive. """

        def make_blank():
            new_order.append(cp_song("", title="", blank=True))

        if old == None:
            old = self.songs

        if old == []:
            if start_page % 2 == 1 and waiting != []:
                make_blank()
            self.songs = new_order + waiting
            return

        if  start_page % 2 == 0:
            # We're on an even page so can output all the two-or-more-page songs
            for s in waiting:
                new_order.append(s)
                start_page += s.pages
            waiting = []

            # Also OK to start any other song here so append head of list

            new_order.append(old[0])
            start_page += old[0].pages

        elif old[0].pages % 2 == 0:
            # Have a two page spread, so save it
            if self.keep_order:
                make_blank()
                new_order.append(old[0])
                start_page += 1
            else:
                waiting.append(old[0])
        else:
            new_order.append(old[0])

            start_page += old[0].pages

        self.reorder(start_page, old[1:], new_order, waiting)


class html_book:
    def format(html, contents="", title="Untitled", for_print=True, stand_alone=False, external_css=None):
        external_styles = ""
        if external_css:
            if os.path.isfile(external_css):
                with open(external_css) as p:
                    external_styles = p.read()

        web_template = """
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
        <title>%(title)s</title>
    </head>
    <body>
        %(frontmatter)s
        %(html)s
    </body>
</html>
        """

        frontmatter = """
<div class='song'>
    <div class='page'>
        <div class='song-page'>
            <div class='song-text'>
                <h1 class="book-title">%(title)s</h1>
            </div>
        </div>
    </div>
</div>

%(contents)s
        """

        print_template = """
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
        <title>%(title)s</title>
        <style>%(stylesheet)s</style>
        <style>%(external_styles)s</style>
    </head>
    <body>
        %(frontmatter)s
        %(html)s
    </body>
</html>
        """

        if for_print:
             web_template = print_template
        if stand_alone:
            frontmatter = ""
        else:
            frontmatter = frontmatter % {
                'contents': contents,
                'title': title,
            }

        return web_template % {
            'external_styles': external_styles,
            'frontmatter': frontmatter,
            'html': html,
            'stylesheet': resource_string(__name__, "styles/web.css"),
            'title': title,
        }
