
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


class QuizQuestion:
    "A question with one correct and multiple incorrect answers"

    def __init__(self, qid, question, answer, *incorrectanswers):
        self.qid = qid # question id
        self.question = question
        self.correct = answer
        self.incorrectanswers = [a for a in incorrectanswers[0] if len(a) > 0] # remove empty values
        #logger.debug("created QuizQuestion: %r %r %r", question, answer, self.incorrectanswers)

    def __str__(self):
        return '#{} - {}? {} ({} decoys)'.format(self.qid, 
                                                 self.question, 
                                                 self.correct, 
                                                 len(self.incorrectanswers))

class Datastore:
    "A wrapper for functions to get different datasets, e.g. for quiz, prizes etc "
    def __init__(self):
        self.g = pygsheets.authorize(service_file=env('CREDENTIALS_FILE'))

    def quizquestions(self):
        "Get quiz questsions"
        sheet = self.g.open_by_key(env('SHEET_ID_QUIZ')).sheet1
        logger.debug('about to get new quiz questions')
        return [QuizQuestion(i, row[0], row[1], row[2:]) for i, row in enumerate(sheet.get_all_values()) if not row[0].startswith('#')]

    def quizprizes(self):
        "Get quiz prizes"
        sheet = self.g.open_by_key(env('SHEET_ID_PRIZES')).sheet1
        logger.debug('about to get new quiz prizes')
        return sheet.get_all_values()

