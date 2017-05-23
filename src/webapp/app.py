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

env.read_envfile()

APIVERSION = '0.1'
SECRET_CHALLENGE = env('SECRET_CHALLENGE')
SECRET_URI = '/{}'.format(env('SECRET_URI'))
PAGE_ACCESS_TOKEN = env('PAGE_ACCESS_TOKEN')

loop = asyncio.get_event_loop()
app = web.Application(loop=loop)

async def handle_verification(request):
    'Get a GET request and try to verify it'
    #audioname = request.match_info.get('audioname', None) # match path string, see the respective route
    app.logger.debug('About to read a challenge')
    challenge = request.query.get('hub.challenge')
    if challenge is not None and challenge == SECRET_CHALLENGE:
        return web.Response(text=challenge)
    else:
        return web.Response(status=400, text='You dont belong here')

app.router.add_get(SECRET_URI, handle_verification)

async def handle_message(request):
    'Get a POST request and treat it like an incoming message'
    app.logger.debug('About to read a message')
    postdata = await request.text()
    page.handle_webhook(postdata, message=msg_handler)

app.router.add_post(SECRET_URI, handle_message)

def after_send(payload, response):
  """:type event: fbmq.Payload"""
  print("complete")

def msg_handler(event):
  """:type event: fbmq.Event"""
  sender_id = event.sender_id
  message = event.message_text
  page.send(sender_id, "thank you! your message is '%s'" % message)


page = fbmq.Page(PAGE_ACCESS_TOKEN, after_send=after_send)

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG)
    # start server
    web.run_app(
        app,
        port=8000
    )
