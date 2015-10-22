#! /usr/bin/env python3
import glob
import re
import argparse
import os
import subprocess
import pypandoc
import tempfile
from chorddiagram import ChordChart

class transposer:
   
    __note_indicies = {"C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "D#": 3,
                     "E" : 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "Ab": 8,
                     "G#": 8, "A" : 9, "Bb": 10, "A#": 10, "B": 11}
        
    __notes = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    
    def __init__(self, offset = 0):
        self.offset = offset
    
    def transpose_chord(self, chord_string):
        return re.sub("([A-G](\#|b)?)",(lambda x: self.transpose_note(x.group())), chord_string)
               
    def __getNoteIndex(self, note):
        return self.__note_indicies[note] if note in self.__note_indicies else none
    
   
    def transpose_note(self, note):   
        note_index = self.__getNoteIndex(note)
        new_note = (note_index + self.offset ) % 12
        return self.__notes[new_note] if  note_index != None else note
    
def extract_title(text, title = None):
    """Find a chordpro title and get rid of it out of a string"""
    title_re = re.compile("{(ti:|title:|t:) *(.*?)}", re.IGNORECASE)
    title_search = re.search(title_re, text)
    if title_search != None:
        title = title_search.group(2)
        text = re.sub(title_re, "", text)
    return text, title

def extract_book_filename(text, book = None):
    """Find a custom chordpro directive {book: }"""
    book_re = re.compile("{(book:) *(.*?)}", re.IGNORECASE)
    book_search = re.search(book_re, text)
    book_filename = None
    if book_search != None:
        book_filename = book_search.group(2)
        text = re.sub(book_re, "", text)
    return text, book_filename

class cp_song:
    def __init__(self, song, title="Song", transpose=0, blank = False, path = None, grids = None):
        self.blank = blank
        self.grids = grids
        self.text = song
        self.key = None
        self.pages = 1
        self.original_key = None
        self.title = title
        self.path = path
        self.chords_used = []
        self.transpose = transpose
        self.transposer = transposer(transpose)
        self.__find_title()
        if self.title == None:
            self.title = title
        self.__find_key()
        self.__find_transpositions()
        self.__format_tab()
        self.__format_chorus()
        self.format()    
        

    def __find_title(self):
        self.text, self.title = extract_title(self.text, title=self.title)

    def __find_transpositions(self):
        tr_re = re.compile("{(tr|transpose): *(.*)}", re.IGNORECASE)
        tr_search = re.search(tr_re, self.text)
        self.standard_transpositions = [0]
        if tr_search != None:
            standard_transpositions = tr_search.group(2).split(" ")
            self.standard_transpositions += [int(x) for x in standard_transpositions]
            self.text = re.sub(tr_re, "", self.text)
            
    def __find_key(self):
        key_re = re.compile("{key: *(.*)}", re.IGNORECASE)
        key_search = re.search(key_re, self.text)
        if key_search != None:
            self.original_key = key_search.group(1)
            self.key = self.transposer.transpose_chord(self.original_key)
            self.text = re.sub(key_re, "", self.text)
            

    def __format_chorus(self):
        in_chorus = False
        new_text = ""
        for line in self.text.split("\n"):
            if re.match("{(soc|start_of_chorus|sob|start_of_bridge)}", line):
                in_chorus = True
            elif re.match("{(eoc|end_of_chorus|eob|end_of_bridge)}", line):
                in_chorus = False
            else:
                if in_chorus:
                    new_text += ">"
                new_text += line + "\n"
        if in_chorus:
            new_text +=  "\n\n"
        self.text = new_text
        
    def __format_tab(self):
        in_tab = False
        new_text = ""
        for line in self.text.split("\n"):
            if re.match("{(sot|start_of_tab)}", line):
                in_tab = True
                new_text += "\n\n```\n"
            elif re.match("{(eot|end_of_tab)}", line):
                in_tab = False
                new_text += "```\n"
            else:
                if not in_tab:
                    #Highlight chords
                    line = line.replace("][","] [")
                    line = re.sub("\[(.*?)\]","**[\\1]**",line)
                new_text += line + "\n"
        if in_tab:
            new_text +=  "```"
        self.text = new_text
     
        
    def format(self, transpose=None):
        """ Create a markdown version of the song, transposed if necessary """
        if transpose != None:
            self.transposer = transposer(transpose)
            
        def format_chord(chord):
            if self.transposer.offset != 0:
                chord = self.transposer.transpose_chord(chord)
            chord_normal = self.grids.normalise_chord_name(chord)
            if not chord_normal in self.chords_used:
                self.chords_used.append(chord_normal)
        
            return("[%s]" % chord)
                
        song =  self.text
        #Add four spaces to mid-stanza line ends to force Markdown to add breaks
        song = re.sub("(.)\n(.)", "\\1    \\n\\2", song)
        
        #TAB
        #song = re.sub("{(sot|eot|start_of_tab|end_of_tab)}","```", song)
        # Subtitle
        # Remove comments (as in remarks, not {c: })
        song = re.sub("\n#.*","", song)
        song = re.sub("{(st:|subtitle:) *(.*)}","\n*\\2*", song)
        
        #Comments / headings
        song = re.sub("{(c:|comment:) *(.*)}","**\\2**", song)

        #Chords
        song = re.sub("\[(.*?)\]",lambda m: format_chord(m.group(1)),song)
            
        key_string = self.get_key_string()
        title = "%s %s" % (self.title, key_string)
        grid_md = "<div class='grids'>"
        if self.grids != None:
            for chord_name in self.chords_used:
                grid_md += self.grids.grid_as_md(chord_name)
        grid_md += "</div>"   
      
        song = "# %s\n%s\n<div class='song-page'><div class='song-text'>\n%s\n\n</div></div>" % (title, grid_md, song)
       
        song, pages = re.subn("{(new_page|np)}", "<!-- new_page -->", song)
        if pages > 0:
            self.pages = pages + 1
        self.md = song
        
    def to_html(self):
        #TODO STANDALONE
        self.format()
        song = """
<div class='song'>
<div class='page'>

%s

</div>
</div>
</div>
        """ % self.md
        song = song.replace("<!-- new_page -->", "\n</div></div></div><div class='page'><div class='song-page'><div class='song-text'>")
        return pypandoc.convert(song, 'html', format='md')

    def to_stand_alone_html(self):
        return html_book.format(self.to_html(), title = self.title, stand_alone= True)
        
    def get_key_string(self, trans = None):
        if self.original_key != None:
            self.key = self.transposer.transpose_chord(self.original_key)
        return "(Key of %s)" % self.key if self.key != None else ""

class cp_song_book:
    def __init__(self, songs = [], keep_order = False, title="Songbook"):
        self.songs = songs
        self.keep_order = keep_order
        self.title = title

    def to_md(self):
        md = "---\ntitle: %s\n---\n" % self.title
        for song in self.songs:
            md += song.md
        return md
        
    def order_by_setlist(self, setlist):
        new_order = []
        for potential_song in setlist.split("\n"):
            if potential_song.strip() != "" and not potential_song.startswith("#"):
                restring = potential_song.replace(" ", ".*?").lower()
                regex = re.compile(restring)
                found_song = False
                for song in self.songs:
                    if re.search(regex, song.title.lower()) != None:
                        new_order.append(song)
                        found_song = True
                if not found_song:
                    new_order.append(cp_song("{title: %s (not found)}" % potential_song))
        self.songs = new_order
        
    def reorder(self, start_page, old = None, new_order=[], waiting = []):
        """Reorder songs in the book so two-page songs start on an even page
           Unless this is a set-list in which case insert blanks. Recursive."""
        
        def make_blank():
            new_order.append(cp_song("{title:This page intentionally left blank}", blank=True))
        if old == None:
            old = self.songs

        if old == []:            
            if start_page % 2 == 1 and waiting != []:
                make_blank()
            self.songs = new_order + waiting
            
            return
        if  start_page % 2 == 0:
            #We're on an even page so can output all the two-or-more-page songs
            for s in waiting:
                new_order.append(s)
                start_page += s.pages
            waiting = []
            
            #Also OK to start any other song here so append head of list
            new_order.append(old[0])
            start_page += old[0].pages
        elif old[0].pages % 2 == 0:
            # Have a two page spread, so save it
            if self.keep_order:
                make_blank()
                new_order.append(old[0])
            else:
                waiting.append(old[0])
        else:
            new_order.append(old[0])
            start_page += old[0].pages
        self.reorder(start_page, old[1:], new_order, waiting)    
                    
                
class html_book:
    
    def format(html, contents = "",  title="Untitled", for_print=True, stand_alone=False):
        script = """
function fill_page() {

$("div.page").each(function() {
 var page = $(this);
 var page_height = page.height();
 var song_page = page.children("div.song-page");
 var text = song_page.children("div.song-text");
 var text_height = text.height();
 var grids_height = page.children("div.grids").height();
 var heading_height = page.children("h1").height();
 var chord_grids = page.children("div.grids").children("img").length;
 //grids_height = 200;
 var height_remaining = page_height - grids_height - heading_height;

 var i = 0;
 console.log("GRIDS", grids_height);
 if (text.length > 0)
 {
  
    song_page.height( height_remaining);
   // Make text bigger until it is too big
   while( height_remaining * %(cols)s > text.height()) {
    text.css('font-size', (parseInt(text.css('font-size')) + 1) +"px" );
    i++;
  
    if (i > 50) {break}
    }
   // Make text smaller until it is just right
   while( height_remaining * %(cols)s  < text.height()) {
    
     text.css('font-size', (parseInt(text.css('font-size')) - 1) +"px" );
      i++;

       if (i > 100) {break}
    }
    console.log(page.find("h1").html(), "PAGE HEIGHT TO MATCH", height_remaining, "CONTENTS HEIGHT", text.height(), "FONT SIZE", text.css('font-size') );
  }
});

};
$(function() {
  fill_page()
});

"""
        web_template = """
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>%s</title>
<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.11.3/jquery.min.js"></script>
<script>
%s

</script>
<style>
.page {
    height: 100%%;
    width: 100%%;  
    font-size: 12pt;
    border-style: solid;
    border-width: 1px;
    overflow: hidden;
    -webkit-column-count: 2;
    border-bottom: thick dotted #ff0000;
    page-break-inside: avoid;
    position: relative;
    
}

.page p {
 -webkit-column-break-inside:avoid;
}

blockquote {
-webkit-column-break-inside:avoid;
margin-left: 0px;
margin-right: 0px;
background-color: #CCFF33;
}


h1 {
    -webkit-column-span: all;
     padding: 0px 0px 0px 0px;
     margin: 0px 0px 0px 0px;
     -webkit-margin-before: 0px;
     -webkit-margin-after: 0px;
}
h2 {
     padding: 0px 0px 0px 0px;
     margin: 0px 0px 0px 0px;
     -webkit-margin-before: 0px;
     -webkit-margin-after: 0px;
}

h3 {
     padding: 0px 0px 0px 0px;
     margin: 0px 0px 0px 0px;
     -webkit-margin-before: 0px;
     -webkit-margin-after: 0px;    
}
div {
    padding: 0px 0px 0px 0px;
    margin: 0px 0px 0px 0px;
    border-color: #FFFFFF;
    border-style: solid;
    border-width: 1px;
}
p {
  -webkit-margin-before: .5em;
     -webkit-margin-after: .5em;
}
@media print  
{
    .page{
        page-break-inside: avoid;
      

    }
}
</style>
</head>
<body>

%s


%s

</body>
</html>
"""
        frontmatter = """
<div class='song'>
<div class='page'>

<h1>%s</h1>
</div>
</div>
<div class='song'>
<div class='page'>
<div class='song-page'>
<div class='song-text'>
%s
</div>
</div>
</div>
</div>

        """


        print_template = """
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>%s</title>
<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.11.3/jquery.min.js"></script>
<script>
%s
</script>

<style>
.page {
width: 21cm;
height: 29cm;
padding: .2cm;
margin: .2cm;
border-style: solid;
border-width: 1px;
border-color: #FFFFFF;
page-break-inside: avoid;
position: relative;
}
div.grids img {

}
div.song-page {
padding: 0cm;
margin: 0cm;
border-style: solid;
border-width: 1px;
overflow: hidden;
border-color: #FFFFF;
page-break-inside: avoid;
font-size: 2px;
}


img {
     padding: 0px 0px 0px 0px;
     margin: 0px 0px 0px 0px;
     -webkit-margin-before: 0px;
     -webkit-margin-after: 0px;
}
h1 {
     padding: 0px 0px 0px 0px;
     margin: 0px 0px 0px 0px;
     -webkit-margin-before: 0px;
     -webkit-margin-after: 0px;
}
div {

    border-style: solid;
    border-width: 1px;
    border-color: #FFFFFF;
}
@media print  
{
    div.page{
        page-break-inside: avoid;
    }
    div.song-page{
        page-break-inside: avoid;
    }
}
</style>
</head>
<body>

%s


%s
</body>
</html>
"""
        if for_print:
             web_template = print_template
             cols = "1"
        else:
            cols = "2"
        if stand_alone:
            frontmatter = ""
        else:
            frontmatter = frontmatter % (title, contents)
            
        return web_template % (title, script % {'cols': cols}, frontmatter, html)
        
        

    
output = "markdown"


    
def convert():
    default_output_file = "songbook"
    default_title = 'Songbook!'
    parser = argparse.ArgumentParser()
    parser.add_argument('files', type=argparse.FileType('r'), nargs="*", default=None, help='List of files')
    parser.add_argument('-a', '--alphabetically', action='store_true', help='Sort songs alphabetically')
    parser.add_argument('-g', '--grids', default=None, help='Show chord grids for the given tuning, supported tunings so far are GCEA for uke or EADGBE for guitar')
    parser.add_argument('-k',
                        '--keep-order',
                        action='store_true',
                        help='Preserve song order for playing as a setlist (inserts blank pages to keep multi page songs on facing pages')
    parser.add_argument('--a4', action='store_true', default=True, help='Format for printing (web page output)')
    parser.add_argument('-e', '--epub', action='store_true', help='Output epub book')
    parser.add_argument('-f', '--file-stem', default=default_output_file, help='Base file name, without extension, for output files')
    parser.add_argument( '--html', action='store_true', default=True, help='Output HTML book, defaults to screen-formatting use --a4 option for printing (PDF generation not working unless you chose --a4 for now')
    parser.add_argument('-w', '--word', action='store_true', help='Output .docx format')
    parser.add_argument('-p', '--pdf', action='store_true', help='Output pdf', default=True)
    parser.add_argument('-r', '--reference-docx', default = None, help="Reference docx file to use (eg with Heading 1 having a page-break before)")
    parser.add_argument('-o','--one-doc', action='store_true', help='Output a single document per song: assumes you want A4 PDF')
    parser.add_argument('-b',
                        '--book-file',
                        action='store_true',
                        help ="""First file contains a list of files, each line optionally followed by a transposition (+|-)\d\d?
                                 eg to transpose up one tone:
                                 song-file.cho +2, you can also add a title line: {title: Title of book}""")
    parser.add_argument('-s',
                        '--setlist',
                        default=None,
                        help ='Use a setlist file to filter the book, one song per line and keep facing pages together. Setlist lines can be one or more words from the song title , you can also add a setlist line: {title: Title of setlist}')
    parser.add_argument('--title', default=default_title, help='Title to use for the book, if there is no title in a book file or setlist file')
    


   

    args = vars(parser.parse_args())
    
    out_dir = "."
    os.makedirs(out_dir, exist_ok=True)
    songs = []
    output_file =  args["file_stem"]

    # Do we want chord grids?
    if args["grids"] != None:
        #TODO - relative to this file!
        chart = ChordChart()
        chart.load_tuning(args['grids'])
    else:
        chart = None
    #Is there a setlist file?
    if args["setlist"] == None:
        list = None
    else:
       list = open(args["setlist"]).read()
       #TODO: annotations such as who is leading this song
       #TODO: Transpose
       list, bookfile = extract_book_filename(list)
       if bookfile != None and not args["book_file"]:
           #No book file passed so use the one we found in the setlist
           args["files"] = [open(bookfile,'r')]
           args["book_file"] = True
           
       
    
    if args["files"] != None:
       if args["book_file"]:
            book_file = args["files"][0]
            book_dir, book_name = os.path.split(book_file.name)
            #base output path on book unless user passed a different name
            if args["file_stem"] == default_output_file:
                output_file, _ = os.path.splitext(book_name)
                output_file = os.path.join(book_dir, output_file)
            text = book_file.read()
            text, args["title"] = extract_title(text, args["title"] )
            for line in text.split("\n"):
                # Do we need to transpose this one?
                trans = re.search("((\+|-)?\d+)$", line)
                t = 0
                if trans != None:
                    t = int(trans.group(0))
                    line = re.sub("(?i)((\+|-)?\d+)$", "", line)
                line = re.sub("(?i)^#.*","", line) #Lose comments
                line = line.strip()
                if line != "":
                    song_path = os.path.join(book_dir, line.strip())
                    songs.append(cp_song(open(song_path).read(), transpose=t, path=song_path, grids = chart))
       else:
           for f in args['files']:
                songs.append(cp_song(f.read(), path=f.name, grids=chart))
    else:
        print("ERROR: You need to pass one or more files to process")
  
    # Make all the input files into a book object
    book = cp_song_book(songs, keep_order = args['keep_order'], title=args["title"])

    # If there's a setlist file use it
    if args["setlist"] != None:
       #Let the setlist override titles set elsewere
       list, args["title"] = extract_title(list, args["title"] )
       book.order_by_setlist(list)
       if args["book_file"] or args["file_stem"] == default_output_file:
            set_dir, set_name = os.path.split(args["setlist"])
            output_file, _ = os.path.splitext(set_name)
            output_file = os.path.join(set_dir, output_file)

    if args["alphabetically"]:
        songs.sort(key= lambda song: re.sub("(?i)^(the|a|\(.*?\)) ", "", song.title.lower()))
        
    title = args['title']
    if  args['epub']:
        epub_path = output_file + ".epub"
        xtra =[ "--toc-depth=1","--epub-chapter-level=1"] #, "--epub-stylesheet=songbook.css"] 
        pypandoc.convert(book.to_md(), "epub", format="md", outputfile=epub_path, extra_args=xtra)
        #subprocess.call(["open", epub_path])
 
    if  args["word"]:
        word_path = output_file + ".docx"
        xtra = ["--toc", "--data-dir=.", "--toc-depth=1"]
        if args["reference_docx"] != None:
            xtra.append('--reference-docx=%s' % args["reference_docx"])
        pypandoc.convert(book.to_md(), "docx", format="md", outputfile=word_path, extra_args=xtra)
        #subprocess.call(["open", word_path])
        
   
    #PDF is generated from HTML, BTW
    if args['one_doc']: #Assume standalone PDF
      for song in book.songs:
        if song.path != None:
            for trans in song.standard_transpositions:
                if trans != 0:
                    song.format(transpose = trans)

                if song.key != None:
                        suffix_string = "_key_%s" % song.key
                else:
                    suffix_string = "_" + str(trans) if trans != 0 else ""

                temp_file = tempfile.NamedTemporaryFile(suffix=".html")
                html_path = temp_file.name
                open(html_path, 'w').write(song.to_stand_alone_html())
                pdf_path = "%s%s.pdf" % (song.path, suffix_string )
                command = ['wkhtmltopdf', '--enable-javascript', '--print-media-type', html_path, pdf_path]
                subprocess.call(command)
        
    elif args['html'] or args['pdf']:
        html_path = output_file + ".html"
        contents = "# Contents\n\n"
        #TODO Depends on template so should be passed as an option
        start_page = 3
        book.reorder(start_page) 
        all_songs = ""
        page_count = start_page
        #Make a table of contents
        #TODO - LINK!
        #TODO - Move this to book class
        for song  in book.songs:
            if not song.blank:
                contents += "<p>%s <span style='float:right'>%s</span></p>" % (song.title, str(page_count)) 
                song.format()
            page_count += song.pages
            all_songs += song.to_html()
        contents += "</table>"

        open(html_path, 'w').write( html_book.format(all_songs,
                                                      title=title,
                                                      for_print = args['a4'],
                                                      contents=pypandoc.convert(contents,
                                                                                "html",
                                                                                format="md")))

        if args['pdf']:
            pdf_path = output_file + ".pdf"
            print("Outputting PDF:", pdf_path)
            command = ['wkhtmltopdf', '--enable-javascript', '--print-media-type', '--outline', '--outline-depth', '1', '--default-header', html_path, pdf_path]
            subprocess.call(command)
            #subprocess.call(["open", pdf_path])
        
if __name__ == "__main__":
    convert()
