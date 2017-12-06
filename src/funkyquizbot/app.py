#!/usr/bin/env python

import time
import random

import pickle
import json

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from envparse import env, ConfigurationError # pip install envparse
env.read_envfile()

import gettext
gettext.install('funkyquizbot', env('TRANSLATIONS_PATH')) # now we have _() to wrap translations in

from flask import Flask, request, g, current_app
from werkzeug.local import LocalProxy

import fbmq
from fbmq import Attachment, Template, QuickReply

from funkyquizbot import data
from funkyquizbot.data import Datastore

APIVERSION = '0.1'
SECRET_CHALLENGE = env('SECRET_CHALLENGE')
SECRET_URI = '/{}'.format(env('SECRET_URI'))
PAGE_ACCESS_TOKEN = env('PAGE_ACCESS_TOKEN')

app = Flask(__name__)
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler('python.log', maxBytes=1024 * 1024 * 100, backupCount=20)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
app.logger.addHandler(file_handler)

page = fbmq.Page(PAGE_ACCESS_TOKEN)
page.greeting(_("Welcome to this grand quiz!"))
page.show_starting_button("GET_STARTED_BUTTON")

def setup_quizes():
    quizes = getattr(g, 'quizes', None)
    if quizes is None:
        quizes = g.quizes = getquizdata()
    return quizes

quizes = LocalProxy(setup_quizes)

def setup_quizprizes():
    p = getattr(g, 'quizprizes', None)
    if p is None:
        p = g.quizprizes = getquizprizes()
    return p

quizprizes = LocalProxy(setup_quizprizes)

def setup_giphys():
    giphys = getattr(g, 'giphys', None)
    if giphys is None:
        giphys = g.giphys = getgiphys()
    return giphys

giphys = LocalProxy(setup_giphys)

def setup_seq_dupes():
    seen_seq = getattr(g, 'seen_seq', None)
    if seen_seq is None:
        seen_seq = g.seen_seq = {}
    return seen_seq

SEEN_SEQ = LocalProxy(setup_seq_dupes)

@app.route(SECRET_URI, methods=['GET'])
def handle_verification():
    'Get a GET request and try to verify it'
    app.logger.debug('About to read a challenge')
    token = request.args.get('hub.verify_token')
    if request.args.get('hub.mode', '') == 'subscribe' and \
        token is not None and token == SECRET_CHALLENGE:
        return request.args.get('hub.challenge', 'Oops')
    else:
        return 'You dont belong here'

@app.route(SECRET_URI, methods=['POST'])
def handle_message():
    'Get a POST request and treat it like an incoming message'
    app.logger.debug('Incoming payload')
    postdata = request.get_data(as_text=True)

    page.handle_webhook(postdata) # fbmq distributes according to @decorators
    return 'OK' # return quickly

@page.after_send
def after_send(payload, response):
    """:type event: fbmq.Payload"""
    app.logger.debug("complete")

def receipt(payload, response):
    "a callback that receives a message receipt"
    app.logger.debug('response : ' + response.text)

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

@page.callback(['GET_STARTED_BUTTON'])
def get_started_callback(payload, event):
    app.logger.debug('Get started button: {!r} - {!r}')
    menu(event, menutext=_("Yea, let's do something!"))

@page.handle_message
def message_handler(event):
    """:type event: fbmq.Event"""
    sender_id = event.sender_id
    recipient_id = event.recipient_id
    time_of_message = event.timestamp
    message = event.message
    message_text = message.get("text")
    app.logger.debug('New msg from %s: %r', sender_id, message)
    seq = message.get("seq", 0)
    message_id = message.get("mid")
    app_id = message.get("app_id")
    metadata = message.get("metadata")
    seq_id = sender_id + ':' + recipient_id

    app.logger.debug('previous sequence ids: {!r}'.format(SEEN_SEQ))
    if SEEN_SEQ.get(seq_id, -1) >= seq:
        app.logger.info("Ignore duplicated request")
        return None
    else:
        app.logger.debug('new sequence id registered {} -> {}'.format(seq_id, seq))
        SEEN_SEQ[seq_id] = seq
    page.typing_on(sender_id)
    if message_text is None:
        app.logger.debug("message is none, is this a thumbs up?")
        if message.get('sticker_id') == 369239263222822:
            # we got a thumbs up
            emojis = '👾💪🙌😤🙄🤔🥊🔥🛀🚽🔫🐰'
            page.send(sender_id, random.choice(emojis))
    elif message_text.lower() in ['quiz',]:
        quiz(event)
    elif event.is_postback:
        app.logger.debug("this is postback, someone else must handle it")
    elif event.is_quick_reply:
        app.logger.debug("this is quickreply, someone else must handle it")
    else:
        menu(event)

def menu(event, menutext=None):
    "show a menu of available options"
    if menutext is None:
        menutext = _("Yo! What are you up to?")
    sender_id = event.sender_id
    message = event.message_text
    MENU_OPTIONS = {'startquiz':_('Start a quiz'),
                    'talk':_('Talk to the show producers'),
                    'watchshow':_('Watch the show')}
    buttons = []
    for value,text in MENU_OPTIONS.items():
        buttons.append(
            QuickReply(title=text, payload=encode_payload('MENU', {'menu':value}))
        )
    # TODO: quick_replies is limited to 11, prune incorrect answers if too many
    app.logger.debug("sending menu: %s", buttons)
    page.send(sender_id, menutext, quick_replies=buttons)
    page.typing_off(sender_id)

@page.callback(['MENU_.+'], types=['QUICK_REPLY'])
def callback_menu(payload, event):
    "A callback for any MENU payload we get. "
    sender_id = event.sender_id
    page.typing_on(sender_id)
    prefix, metadata = decode_payload(payload)
    app.logger.debug('Got MENU: {} '.format(metadata['menu']))
    if metadata['menu'] == 'startquiz':
        quiz(event)
    elif metadata['menu'] == 'watchshow':
        tpl = Template.Generic([
                Template.GenericElement(env('WEBPAGE_TITLE'),
                    subtitle=env('WEBPAGE_SUBTITLE'),
                    item_url=env('WEBPAGE_URL'),
                    image_url=env('WEBPAGE_LOGO'),
                    buttons=[
                        Template.ButtonWeb(_('Watch it now'), env('WEBPAGE_URL'))
                    ])
        ])
        page.send(sender_id, tpl)
    elif metadata['menu'] == 'talk':


def quiz(event, previous=None):
    "start or continue a quiz"
    sender_id = event.sender_id
    message = event.message_text
    # Send a gif

    page.typing_on(sender_id)
    # the first question is special
    if previous is None:
        # a brand new quiz
        page.send(sender_id, _("Welcome to a brand new quiz! If you get seven in a row, you get a prize"))
        previous = [ ]  # a list to keep previous quiz id's 
    else:
        if len(previous) == 7:
            app.logger.debug('we have made 7 in a row, send a prize')
            send_prize(event, previous)
            return None
    # ask a question
    try:
        quiz = random.choice(quizes) # get a random quiz
        while quiz.qid in previous:
            quiz = random.choice(quizes) # we've had this ques before, get a new onone
    except IndexError:
        # no quizes in list, yikes
        page.send(sender_id, _("We have no available quizes for you, pls try again later 8)"))
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
    app.logger.debug("sending quiz: %s", quiz)
    page.send(sender_id, quiz.question, quick_replies=buttons)
    page.typing_off(sender_id)


def send_prize(event, previous=None):
    "send a prize"
    sender_id = event.sender_id
    message = event.message_text
    page.typing_on(sender_id)
    page.send(sender_id, _("Wow, you're on a nice streak. Here's a prize!"))
    for p in quizprizes:
        app.logger.debug('Prize: {!r}: {} is_embargoed: {}'.format(p.url, p.embargo, p.is_embargoed))
    # Send a gif prize
    try:
        prize = random.choice([q for q in quizprizes if not q.is_embargoed])
    except IndexError:
        app.logger.warning('No prizes that are not embargoed!')
        page.send(sender_id, '8)')
    if prize.media_type == 'image':
        att = Attachment.Image(prize.url)
    elif prize.media_type == 'video':
        att = Attachment.Video(prize.url)
    elif prize.media_type == 'text':
        att = prize.url
    page.send(sender_id, att)

def get_giphy(context):
    "Get a random giphy that fits the context 'CORRECT'/'WRONG'"
    try:
        return random.choice([x for x in giphys if x.context == context])
    except IndexError: # no giphs available
        return None

@page.callback(['ANSWER_.+'], types=['QUICK_REPLY'])
def callback_answer(payload, event):
    "A callback for any ANSWER payload we get. "
    sender_id = event.sender_id
    page.typing_on(sender_id)
    prefix, metadata = decode_payload(payload)
    app.logger.debug('Got ANSWER: {} (correct? {})'.format(metadata, 'YES' if metadata['correct'] else 'NON'))
    if random.random() > 0.9: # ten percent of the time, send a gif
        giph = get_giphy('CORRECT' if metadata['correct'] else 'WRONG')
        if giph is not None:
            page.send(sender_id, Attachment.Image(giph.url))

    # TODO check how many we have correct
    if not metadata['correct']:
        # wrong answer
        menu(event, menutext=_("Ouch. Wrooooong!:poop: ... Try again!"))
    else:
        # answer is correct, you may continue
        page.send(sender_id, _("Right on!"))
        _prev = metadata['previous']
        notfinished = 7 > len(_prev)
        if notfinished:
            page.send(sender_id, _("You have {} correct questions, only {} to go!").format(len(_prev),
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

def getpickles(env_key):
    "Helper to unpickle from file at env_key, returns empty list on errors"
    try:
        return pickle.load(open(env(env_key), 'rb'))
    except FileNotFoundError:
        app.logger.warning('Could not load cached values from "{}"->{!r}'.format(env_key, env(env_key)))
        return []

def getquizdata():
    "Background task to periodically update quizes"
    quizes = getpickles('CACHEFILE_QUIZQUESTIONS')
    app.logger.debug("Read {} questions".format(len(quizes)))
    return quizes

def getquizprizes():
    "Background task to periodically update quizesprizes"
    quizprizes = getpickles('CACHEFILE_QUIZPRIZES')
    app.logger.debug("Read {} prizes".format(len(quizprizes)))
    return quizprizes

def getgiphys():
    "Background task to periodically update giphys"
    giphys = getpickles('CACHEFILE_GIPHYS')
    app.logger.debug("Read {} giphys".format(len(giphys)))
    return giphys

if __name__ == '__main__':
    # start server
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)
