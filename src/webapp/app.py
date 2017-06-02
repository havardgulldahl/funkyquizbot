#!/usr/bin/env python

import time
import random

import json

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from envparse import env, ConfigurationError # pip install envparse
env.read_envfile()

from flask import Flask, request
from flask_apscheduler import APScheduler # pip install Flask-APScheduler

from .data import Datastore

import fbmq
from fbmq import Attachment, Template, QuickReply


APIVERSION = '0.1'
SECRET_CHALLENGE = env('SECRET_CHALLENGE')
SECRET_URI = '/{}'.format(env('SECRET_URI'))
PAGE_ACCESS_TOKEN = env('PAGE_ACCESS_TOKEN')

app = Flask(__name__)
page = fbmq.Page(PAGE_ACCESS_TOKEN)

quizes = []
data = None

@app.route(SECRET_URI, methods=['GET'])
def handle_verification():
    'Get a GET request and try to verify it'
    logger.debug('About to read a challenge')
    token = request.args.get('hub.verify_token')
    if request.args.get('hub.mode', '') == 'subscribe' and \
        token is not None and token == SECRET_CHALLENGE:
        return request.args.get('hub.challenge', 'Oops')
    else:
        return 'You dont belong here'

@app.route(SECRET_URI, methods=['POST'])
def handle_message():
    'Get a POST request and treat it like an incoming message'
    logger.debug('Incoming payload')
    postdata = request.get_data(as_text=True)

    page.handle_webhook(postdata) # fbmq distributes according to @decorators
    return 'OK' # return quickly

@page.after_send
def after_send(payload, response):
    """:type event: fbmq.Payload"""
    logger.debug("complete")

def receipt(payload, response):
    "a callback that receives a message receipt"
    logger.debug('response : ' + response.text)

def encode_payload(prefix, data):
    """Return a <data> as a string, prefixed with <prefix>, for use as callback payload.
    Raises ValueError if content is invalid as a payload. E.g. length>1000."""
    r = """{}___{}""".format(prefix, json.dumps(data))
    # do some formal checks, as per
    # https://developers.facebook.com/docs/messenger-platform/send-api-reference/postback-button
    if len(r) > 1000:
        # postback content has max length of 1000
        raise ValueError
    return r

def decode_payload(s):
    "Decode a payload encoded with encode_payload(). Returns (prefix, data)"
    prefix, data = s.split('___', 2)
    return (prefix, json.loads(data))

@page.handle_message
def message_handler(event):
    """:type event: fbmq.Event"""
    sender_id = event.sender_id
    message = event.message_text
    logger.debug('New msg from %s: %r', sender_id, message)
    page.typing_on(sender_id)
    if message is None:
        logger.debug("message is none, is this a thumbs up?")
    elif message.lower() in ['quiz',]:
        quiz(event)
    elif event.is_postback:
        logger.debug("this is postback, someone else must handle it")
    elif event.is_quick_reply:
        logger.debug("this is quickreply, someone else must handle it")
    else:
        page.send(sender_id, "thank you, '%s' yourself! type 'quiz' to start it :)" % message, callback=receipt)

def quiz(event, previous=None):
    "start or continue a quiz"
    sender_id = event.sender_id
    message = event.message_text
    # Send a gif
    #page.send(sender_id, Attachment.Image('https://media.giphy.com/media/3o7bu57lYhUEFiYDSM/giphy.gif'))

    # the first question is special
    if previous is None:
        # a brand new quiz
        page.send(sender_id, "Welcome to a brand new quiz! If you get seven in a row, you get a prize")
        previous = [ ]  # a list to keep previous quiz id's 
    else:
        if len(previous) >= 7:
            # we have made 7 in a row
            send_prize(event, previous)
            return
    # ask a question
    try:
        quiz = random.choice(quizes) # get a random quiz
        while quiz.qid in previous:
            quiz = random.choice(quizes) # we've had this ques before, get a new onone
    except IndexError:
        # no quizes in list, yikes
        page.send(sender_id, "We have no available quizes for you, pls try again later 8)")
        return
    previous.append(quiz.qid) # remember what we've seen|
    buttons = []
    for text in quiz.incorrectanswers:
        buttons.append(
            QuickReply(title=text, payload=encode_payload('ANSWER', {'previous':previous, 'correct':False}))
        )
    # TODO: quick_replies is limited to 11, prune incorrect answers if too many
    buttons.append(
        QuickReply(title=quiz.correct, payload=encode_payload('ANSWER', {'previous':previous, 'correct':True})),
    )
    random.shuffle(buttons) # hide  correct answer
    logger.debug("sending quiz: %s", quiz)
    page.send(sender_id, quiz.question, quick_replies=buttons)
    page.typing_off(sender_id)


def send_prize(event, previous=None):
    "send a prize"
    sender_id = event.sender_id
    message = event.message_text
    page.typing_on(sender_id)
    page.send(sender_id, "wow, you're on a nice streak. Here's a prize!")
    # Send a gif prize
    page.send(sender_id, Attachment.Image('https://media.giphy.com/media/3o7bu57lYhUEFiYDSM/giphy.gif'))

@page.callback(['ANSWER_.+'])
def callback_answer(payload, event):
    "A callback for any ANSWER payload we get. "
    sender_id = event.sender_id
    page.typing_on(sender_id)
    prefix, metadata = decode_payload(payload)
    logger.debug('Got ANSWER: {} (correct? {})'.format(metadata, 'YES' if metadata['correct'] else 'NON'))
    page.send(sender_id, "Your reply was {}".format('CORRECT' if metadata['correct'] else 'INCORRECT :('))
    # TODO check how many we have correct
    if metadata['correct']:
        # answer is correct, you may continue
        _prev = metadata['previous']
        page.send(sender_id, "you have {} correct questions, only {} to go!".format(len(_prev),
                                                                                    7-len(_prev)))
        quiz(event, _prev)

@page.handle_delivery
def delivery_handler(event):
    """:type event: fbmq.Event
    This callback will occur when a message a page has sent has been delivered."""
    sender_id = event.sender_id
    watermark = event.delivery.get('watermark', None)
    messages = event.delivery.get('mids', [])
    #logger.debug('Message from me ({}) delivered: {}'.format(sender_id, messages or watermark))

@page.handle_read
def read_handler(event):
    """:type event: fbmq.Event
    This callback will occur when a message a page has sent has been read by the user.
    """
    sender_id = event.sender_id
    watermark = event.read.get('watermark', None)
    #logger.debug('Message from me ({}) has been read: {}'.format(sender_id, watermark))

optin_handler = message_handler

def getquizdata():
    "Background task to periodically update quizes"
    global quizes, data
    logger.debug(
        "Get new quizquestions, currently we have {!r}".format(quizes)
    )
    quizes = data.quizquestions()

class Config(object):
    JOBS = [
        {
            'id': 'getquizdata',
            'func': 'webapp.app:getquizdata',
            'args': (),
            'trigger': 'interval',
            'seconds': 60
        },
    ]
    SCHEDULER_API_ENABLED = False # REST api to jobs
    SCHEDULER_TIMEZONE = 'Europe/Oslo'

app.config.from_object(Config())
data = Datastore()
# get quizes
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

if __name__ == '__main__':
    # start server
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)
