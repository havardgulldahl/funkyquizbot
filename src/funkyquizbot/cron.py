#!/usr/bin/env python
"Run every xx minutes to refresh local cache"

import time

import pickle
from funkyquizbot import data
from funkyquizbot.data import Datastore

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

from envparse import env, ConfigurationError # pip install envparse
env.read_envfile()

if __name__ == '__main__':
    datastore = Datastore()
    logger.info("Getting quizes, prizes and giphys")
    with open(env('CACHEFILE_QUIZQUESTIONS'), 'wb') as f:
        pickle.dump(datastore.quizquestions(), f)
    logger.debug("wrote quizquestions to {}".format(env('CACHEFILE_QUIZQUESTIONS')))
    with open(env('CACHEFILE_QUIZPRIZES'), 'wb') as f:
        pickle.dump(datastore.quizprizes(), f)
    logger.debug("wrote quizprises to {}".format(env('CACHEFILE_QUIZPRIZES')))
    with open(env('CACHEFILE_GIPHYS'), 'wb') as f:
        pickle.dump(datastore.giphys(), f)
    logger.debug("wrote gipyys to {}".format(env('CACHEFILE_GIPHYS')))
