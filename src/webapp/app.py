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

from asyncio import coroutine

from aiohttp import web

from envparse import env, ConfigurationError

from data import Datastore

import fbmq
from fbmq import Attachment, Template, QuickReply

env.read_envfile()

APIVERSION = '0.1'
SECRET_CHALLENGE = env('SECRET_CHALLENGE')
SECRET_URI = '/{}'.format(env('SECRET_URI'))
PAGE_ACCESS_TOKEN = env('PAGE_ACCESS_TOKEN')

loop = asyncio.get_event_loop()
app = web.Application(loop=loop)
page = fbmq.Page(PAGE_ACCESS_TOKEN)

quizes = []
data = None

async def handle_verification(request):
    'Get a GET request and try to verify it'
    #audioname = request.match_info.get('audioname', None) # match path string, see the respective route
    app.logger.debug('About to read a challenge')
    token = request.query.get('hub.verify_token')
    if token is not None and token == SECRET_CHALLENGE:
        return web.Response(text=request.query.get('hub.challenge', 'Oops'))
    else:
        return web.Response(status=400, text='You dont belong here')

app.router.add_get(SECRET_URI, handle_verification)

async def handle_message(request):
    'Get a POST request and treat it like an incoming message'
    app.logger.debug('Incoming payload')
    postdata = await request.text()

    page.handle_webhook(postdata)
    """
                        # dispatch message to correct handler
                        message=message_handler,
                        delivery=delivery_handler,
                        optin=optin_handler,
                        read=read_handler,
    )
    """
    return web.Response(text='OK') # return quickly

app.router.add_post(SECRET_URI, handle_message)

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
    if message.lower() in ['quiz',]:
        quiz(event)
    else:
        page.send(sender_id, "thank you, '%s' yourself! type 'quiz' to start it :)" % message, callback=receipt)
    page.typing_off(sender_id)

def quiz(event):
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
    buttons = [
        QuickReply(title=quiz.correct, payload=encode_payload('ANSWER', {'reply':quiz.correct, 'correct':True})),
        #Template.ButtonPostBack("Ja", encode_payload('ANSWER', {'reply':'YES', 'correct':True})),
        #Template.ButtonPostBack("Nja", encode_payload('ANSWER', {'reply':'MAYBE', 'correct':False})),
        #Template.ButtonPostBack("NEi", encode_payload('ANSWER', {'reply':'NO', 'correct':False})),
    ]
    for text in [a for a in quiz.incorrectanswers if len(a) > 0]:
        buttons.append(
            QuickReply(title=text, payload=encode_payload('ANSWER', {'reply':text, 'correct':False}))
        )
    logging.debug("sending quiz: %s", quiz)
    page.send(sender_id, quiz.question, quick_replies=buttons)


@page.callback(['ANSWER_.+'])
def callback_answer(payload, event):
    "A callback for any ANSWER payload we get. "
    sender_id = event.sender_id
    prefix, data = decode_payload(payload)
    print('Got ANSWER: {} (correct? {})'.format(data['reply'], 'YES' if data['correct'] else 'NON'))
    page.send(sender_id, "Your reply was {}".format('CORRECT' if data['correct'] else 'INCORRECT :('))

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

async def getquizdata(app):
    "Background task to periodically update quizes"
    # https://aiohttp.readthedocs.io/en/stable/web.html#background-tasks
    global quizes, data
    while True:
        logging.debug(
            "Get new quizquestions, currently we have {!r}".format(quizes)
        )
        quizes = await data.quizquestions()
        await asyncio.sleep(600.0)
        #time.sleep(30.0)

async def start_background_tasks(app):
    " run short and long running background tasks in aiohttp server "
    app['quizfetcher'] = app.loop.create_task(getquizdata(app))

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    data = Datastore()
    # get quizes
    app.on_startup.append(start_background_tasks)
    # start server
    web.run_app(
        app,
        port=8000
    )
    loop.close()
