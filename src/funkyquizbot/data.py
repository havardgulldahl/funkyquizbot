from datetime import datetime
from typing import Dict, Tuple, List, Type # requires python > 3.5
import enum

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from envparse import env, ConfigurationError # pip install envparse
import pygsheets # pip install pygsheets

CREDENTIALS_FILE = 'credentials.json' # your server gdrive credentials -  put it in .env
SHEET_ID_QUIZ = '' # put it in .env
SHEET_ID_PRIZES = '' # put it in .env
SHEET_ID_GIPHYS = '' # put it in .env

env.read_envfile() # read .env

# type annotation
Cells = List[str]

class Row:
    "A low level wrapper for storing rows from a sheet. Subclass this"
    def __init__(self, rowid: int, name: str, timestamp: str, cells: Cells):
        self.id = rowid
        self.name = name
        self.timestamp = timestamp
        self.cells = cells

    @staticmethod
    def must_skip(cells: Cells):
        if len(cells) == 0: return True
        if len(cells[0].strip()) == 0: return True
        if cells[0].strip().startswith('#'): return True
        return False

class QuizQuestion(Row):
    "A question with one correct and multiple incorrect answers"
    def __init__(self, rowid: int, name: str, timestamp: str, cells: Cells):
        super().__init__(rowid, name, timestamp, cells)
        self.qid = rowid # question id
        self.question = cells[0]
        self.correct = cells[1]
        self.incorrectanswers = [a for a in cells[2:] if len(a) > 0] # remove empty values

    def __str__(self):
        return '#{} - {}? {} ({} decoys)'.format(self.qid, 
                                                 self.question, 
                                                 self.correct, 
                                                 len(self.incorrectanswers))

class QuizPrize(Row):
    "A prize - an url to a secret video clip or image + embargo datestamp"
    def __init__(self, rowid: int, name: str, timestamp: str, cells: Cells):
        super().__init__(rowid, name, timestamp, cells)
        self.url = cells[0]
        self.media_type = cells[1]
        self.embargo = None
        try:
            self.embargo = datetime.strptime(cells[2], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                self.embargo = datetime.strptime(cells[2], "%Y-%m-%d")
            except ValueError:
                pass
        #self.extra = [a for a in cells[2:] if len(a) > 0] # remove empty values

    @property
    def is_embargoed(self):
        "return whether this prize is still embargoed or not. boolean"
        if self.embargo is None: return False
        return datetime.now() < self.embargo
        
    def __str__(self):
        return '#{} - {} ({}) embargo: {}'.format(self.id, 
                                                  self.url,
                                                  self.media_type, 
                                                  self.embargo)
class Giphy(Row):
    """A url to an animated gif, with zero or more tags
    Expected format:
        # url | # context: WRONG/CORRECT | # tags - zero or more cells
    """
    def __init__(self, rowid: int, name: str, timestamp: str, cells: Cells):
        super().__init__(rowid, name, timestamp, cells)
        self.url = cells[0]
        self.context = cells[1]
        self.tags = [a for a in cells[2:] if len(a) > 0] # remove empty values

    def __str__(self):
        return 'gif {} - {} {}'.format(self.id, self.url, self.tags)

class Datastore:
    "A wrapper for functions to get different datasets, e.g. for quiz, prizes etc "
    def __init__(self):
        self.g = pygsheets.authorize(service_file=env('CREDENTIALS_FILE'))

    def quizquestions(self):
        "Get quiz questsions"
        return self._getlines(env('SHEET_ID_QUIZ'), 'quiz questions', QuizQuestion)

    def quizprizes(self):
        "Get quiz prizes"
        return self._getlines(env('SHEET_ID_PRIZES'), 'quiz prizes', QuizPrize)

    def giphys(self):
        "Get giphys "
        return self._getlines(env('SHEET_ID_GIPHYS'), 'Giphys', Giphy)

    def _getlines(self, sheetId: str, name: str, factory: Type[Row]):
        "helper method to get data from gsheets"
        sheet = self.g.open_by_key(sheetId).sheet1 # get first sheet
        logger.debug('about to get new %s', name)
        timestamp = datetime.now().isoformat()
        return [factory(i, name, timestamp, row) for i, row in enumerate(sheet.get_all_values()) if not Row.must_skip(row) ]
