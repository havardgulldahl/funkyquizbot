#!/bin/bash

cd $HOME/bot;

source bin/activate;

PYTHONPATH=. python funkyquizbot/cron.py 2>&1 >cron.log

