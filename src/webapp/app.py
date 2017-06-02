#!/usr/bin/env python

import os.path
import tempfile
import time
import random
import pathlib
from urllib.parse import quote

import asyncio
import uuid
import json

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from asyncio import coroutine # requires python>3.5

#from aiohttp import web # pip install aiohttp
from flask import Flask, request
from flask_apscheduler import APScheduler # pip install Flask-APScheduler

from envparse import env, ConfigurationError # pip install envparse

from data import Datastore

import fbmq
from fbmq import Attachment, Template, QuickReply

env.read_envfile()

APIVERSION = '0.1'
SECRET_CHALLENGE = env('SECRET_CHALLENGE')
SECRET_URI = '/{}'.format(env('SECRET_URI'))
PAGE_ACCESS_TOKEN = env('PAGE_ACCESS_TOKEN')

loop = asyncio.get_event_loop()
#app = web.Application(loop=loop)
app = Flask(__name__)
page = fbmq.Page(PAGE_ACCESS_TOKEN)

quizes = []
data = None

@app.route(SECRET_URI, methods=['GET'])
def handle_verification():
    'Get a GET request and try to verify it'
    #audioname = request.match_info.get('audioname', None) # match path string, see the respective route
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
    print("complete")

def receipt(payload, response):
    "a callback that receives a message receipt"
    print('response : ' + response.text)

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
    print('New msg from {}: {}'.format(sender_id, message))
    page.typing_on(sender_id)
    if message is None:
        print("message is none, is this a thumbs up?")
    elif message.lower() in ['quiz',]:
        quiz(event)
    elif event.is_postback:
        print("this is postback, someone else must handle it")
    elif event.is_quick_reply:
        print("this is quickreply, someone else must handle it")
    else:
        page.send(sender_id, "thank you, '%s' yourself! type 'quiz' to start it :)" % message, callback=receipt)
    page.typing_off(sender_id)

def quiz(event, previous=None):
    "start or continue a quiz"
    sender_id = event.sender_id
    message = event.message_text
    # Send a gif
    #page.send(sender_id, Attachment.Image('https://media.giphy.com/media/3o7bu57lYhUEFiYDSM/giphy.gif'))

    # ask a question
    try:
        quiz = random.choice(quizes)
    except IndexError:
        # no quizes in list, yikes
        page.send(sender_id, "We have no available quizes for you, pls try again later 8)")
        return
    buttons = []
    for text in quiz.incorrectanswers:
        buttons.append(
            QuickReply(title=text, payload=encode_payload('ANSWER', {'previous':text, 'correct':False}))
        )
    # TODO: quick_replies is limited to 11, prune incorrect answers if too many
    buttons.append(
        QuickReply(title=quiz.correct, payload=encode_payload('ANSWER', {'previous':quiz.correct, 'correct':True})),
    )
    random.shuffle(buttons) # hide  correct answer
    logger.debug("sending quiz: %s", quiz)
    page.send(sender_id, quiz.question, quick_replies=buttons)


@page.callback(['ANSWER_.+'])
def callback_answer(payload, event):
    "A callback for any ANSWER payload we get. "
    sender_id = event.sender_id
    prefix, data = decode_payload(payload)
    print('Got ANSWER: {} (correct? {})'.format(data, 'YES' if data['correct'] else 'NON'))
    page.send(sender_id, "Your reply was {}".format('CORRECT' if data['correct'] else 'INCORRECT :('))
    # TODO check how many we have correct
    if data['correct']:
        # answer is correct, you may continue
        quiz(event)

@page.handle_delivery
def delivery_handler(event):
    """:type event: fbmq.Event
    This callback will occur when a message a page has sent has been delivered."""
    sender_id = event.sender_id
    watermark = event.delivery.get('watermark', None)
    messages = event.delivery.get('mids', [])
    #print('Message from me ({}) delivered: {}'.format(sender_id, messages or watermark))

@page.handle_read
def read_handler(event):
    """:type event: fbmq.Event
    This callback will occur when a message a page has sent has been read by the user.
    """
    sender_id = event.sender_id
    watermark = event.read.get('watermark', None)
    #print('Message from me ({}) has been read: {}'.format(sender_id, watermark))

optin_handler = message_handler

def getquizdata():
    "Background task to periodically update quizes"
    global quizes, data
    while True:
        logger.debug(
            "Get new quizquestions, currently we have {!r}".format(quizes)
        )
        quizes = data.quizquestions()
        #await asyncio.sleep(600.0)
        time.sleep(5.0)

class Config(object):
    JOBS = [
        {
            'id': 'getquizdata',
            'func': '__main__:getquizdata',
            'args': (),
            'trigger': 'interval',
            'seconds': 60
        },
    ]
    SCHEDULER_API_ENABLED = False # REST api to jobs
    SCHEDULER_TIMEZONE = 'Europe/Oslo'

if __name__ == '__main__':
    app.config.from_object(Config())
    data = Datastore()
    # get quizes
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()
    # start server
    app.run(host='0.0.0.0', port=8000, debug=True, threaded=True)