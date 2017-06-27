#!/bin/bash
xgettext --language=Python --keyword=_ --output=translations/messages.pot funkyquizbot/*.py
msginit --input=translations/messages.pot --locale=nb_NO
