#!/usr/bin/env python

import os.path
import tempfile
import time
import pathlib
from urllib.parse import quote

import asyncio
import uuid

from asyncio import coroutine

from aiohttp import web

from envparse import env, ConfigurationError

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

@page.handle_message
def message_handler(event):
    """:type event: fbmq.Event"""
    sender_id = event.sender_id
    message = event.message_text
    print('New msg from {}: {}'.format(sender_id, message))
    page.typing_on(sender_id)
    page.send(sender_id, "thank you! your message is '%s'" % message, callback=receipt)
    # Send a gif
    #page.send(sender_id, Attachment.Image('https://media.giphy.com/media/3o7bu57lYhUEFiYDSM/giphy.gif'))

    # ask a question
    buttons = [
        Template.ButtonPostBack("Ja", "ANSWER_YES"),
        Template.ButtonPostBack("Nei", "ANSWER_NO"),
    ]
    page.send(sender_id, Template.Buttons("Er Cantona i live?", buttons))

    page.typing_off(sender_id)

@page.callback(['ANSWER_.+'])
def callback_answer(payload, event):
    "A callback for any ANSWER payload we get. "
    print('Got ANSWER: {} <- {}'.format(payload, event))

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

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.WARNING)
    # start server
    web.run_app(
        app,
        port=8000
    )
